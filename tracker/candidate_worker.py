"""Connect a configured JSON-generating process to the semantic candidate queue.

The process receives a source-bound request on stdin and returns JSON on stdout.
It may call a user's generative API. It never receives Jev credentials or chooses
the winning annotation; that remains the bounded Jev decision stage.
"""
import json
import os
from pathlib import Path
import time
import uuid

from .schema import InputError, digest, dumps
from . import candidate_process
from .semantic_extraction import FileCandidates, partition, read, validate_proposals, write, PARTITION_STANDARD,ACTIVITY_ROUTING
from .readable_context import resolve_quote


CITATION_FORMATS = ('source-offsets/1', 'source-quotes/1', 'source-references/1')


def bind_candidate_response(request, body, producer, *, citation_format=None):
    """Attach caller-owned metadata without changing generated fields/evidence."""
    if not isinstance(body, dict):
        raise InputError('Candidate process did not return a JSON object')
    if not isinstance(producer, str) or not producer.strip():
        raise InputError('Candidate response needs an explicit producer name/version')
    if citation_format is not None and citation_format not in CITATION_FORMATS:
        raise InputError('Unknown configured candidate citation format')
    response = {**body, 'request_hash': digest(request), 'producer': producer}
    if citation_format is not None:
        if body.get('citation_format') not in (None, citation_format):
            raise InputError('Candidate citation format conflicts with configured format')
        response['citation_format'] = citation_format
    return response


class CommandCandidates(FileCandidates):
    def __init__(self, directory, command, producer, context_policy=None, timeout=120,*,partition_standard=PARTITION_STANDARD,partition_policy=None,contribution_readings=False,execution_budget=None,activity_routing=ACTIVITY_ROUTING,reading_protocol='contribution-readings/1',citation_format=None,cache_directories=()):
        super().__init__(directory,context_policy,partition_standard=partition_standard,partition_policy=partition_policy,contribution_readings=contribution_readings,activity_routing=activity_routing,reading_protocol=reading_protocol,cache_directories=cache_directories)
        if (not isinstance(command,list) or not command or any(not isinstance(x,str) or not x for x in command)
                or not isinstance(producer,str) or not producer.strip()):
            raise InputError('Candidate worker needs an explicit argument list and producer name/version')
        self.command=command;self.producer=producer;self.timeout=candidate_process.validate_timeout(timeout);self.generation_calls=0
        self.execution_budget=execution_budget
        if citation_format is not None and citation_format not in CITATION_FORMATS:
            raise InputError('Unknown configured candidate citation format')
        self.citation_format=citation_format

    def generate(self, run, req, *, validator=None):
        packet=self.packet(req)
        if self.execution_budget is not None:
            return self.execution_budget.invoke('candidate',req,lambda:self._generate(run,req,packet,validator),payload=packet)
        return self._generate(run,req,packet,validator)

    def packet(self, req):
        packet={'request_hash':digest(req),'request':req}
        if self.citation_format is not None:
            packet['response_metadata']={'request_hash':digest(req),'producer':self.producer,'citation_format':self.citation_format}
            packet['response_instructions']='Return the stage-specific candidate payload. The harness supplies response_metadata; do not generate those fields. Use the specified citation format without changing quoted source text. For source-references/1, {"subject":true} may cite the exact current contribution; it does not establish that the contribution supports your proposed meaning.'
        return packet

    def _generate(self, run, req, packet, validator=None):
        key=digest(req);start=time.monotonic()
        env={k:v for k,v in os.environ.items() if k.upper()!='JEV_API_KEY'}
        receipt={'schema':'candidate-worker-receipt/2','request_hash':key,'producer':self.producer,
                 'attempt_id':uuid.uuid4().hex,'started_at_ns':time.time_ns(),'status':'started',
                 'execution':'external_json_process','execution_policy':candidate_process.POLICY,
                 'selection':'candidate only; Jev has not selected it'}
        if self.citation_format is not None:receipt['configured_citation_format']=self.citation_format
        latest=self.directory/'receipts'/f'{key}.json'
        attempts=self.directory/'receipts'/'attempts'
        if latest.exists():
            previous=read(latest)
            previous_id=previous.get('attempt_id') if isinstance(previous,dict) else None
            if not isinstance(previous_id,str) or len(previous_id)!=32 or any(c not in '0123456789abcdef' for c in previous_id):
                previous_id='legacy-'+digest(previous)
            write(attempts/f'{previous_id}.json',previous)
        attempt=attempts/f'{receipt["attempt_id"]}.json'
        write(attempt,receipt);write(latest,receipt)
        try:
            self.generation_calls+=1
            result=candidate_process.run(self.command,input=dumps(packet),env=env,timeout=self.timeout)
            receipt['process']=result.details
            try:body=json.loads(result.stdout)
            except (ValueError,TypeError):raise InputError('Candidate process did not return a JSON object') from None
            if not isinstance(body,dict):raise InputError('Candidate process did not return a JSON object')
            # Identity comes from the harness, not a model guessing a hash.
            response=bind_candidate_response(req,body,self.producer,citation_format=self.citation_format)
            if validator is not None:
                validator(response)
            elif req.get('stage')=='content':
                validate_proposals(run,req,response)
            elif req.get('stage')=='activity_readings':
                from .contribution_readings import validate
                validate(run,req,response)
            else:
                proposals=response.get('partitions')
                if not isinstance(proposals,list) or not 1<=len(proposals)<=3:raise InputError('Worker needs 1–3 partition proposals')
                for proposal in proposals:
                    if 'units' in proposal:
                        spans=[]
                        for quote in proposal['units']:
                            ref=resolve_quote(run,req['prefix'],{'event_id':req['source']['event_id'],**quote})
                            if ref['event_id']!=req['source']['event_id']:raise InputError('Partition quote belongs to another source')
                            spans.append({'start':ref['start'],'end':ref['end']})
                        proposal['spans']=spans;proposal.pop('units')
                    units=partition(run,req['source'],proposal.get('spans'))
                    if req.get('candidate_description_contract'):
                        from .contribution_readings import descriptions
                        if not descriptions(proposal,len(units)):raise InputError('Described boundary candidates are required')
            write(self.directory/'responses'/f'{key}.json',response)
            receipt.update(status='candidate_ready',response_hash=digest(response))
            return response
        except candidate_process.CandidateProcessError as exc:
            receipt.update(status='failed',error=str(exc),provider_failure=exc.details)
            raise
        except OSError:
            receipt.update(status='failed',error='Candidate workspace could not be read or written')
            raise InputError(receipt['error']) from None
        except InputError as exc:
            receipt.update(status='failed',error=str(exc));raise
        except KeyboardInterrupt:
            receipt.update(status='interrupted',error='Candidate processing interrupted; remote work and usage may be unknown')
            raise
        except Exception:
            receipt.update(status='failed',error='Candidate processing failed; process output is not persisted')
            raise
        finally:
            receipt['elapsed_seconds']=round(time.monotonic()-start,3)
            write(attempt,receipt);write(latest,receipt)

    def content(self,run,ref,activity):
        proposal=super().content(run,ref,activity)
        if proposal['status']=='needs_candidates':
            self.generate(run,read(proposal['request_path']))
            proposal=super().content(run,ref,activity)
        return proposal

    def readings(self,run,ref):
        result=super().readings(run,ref)
        if result['status']=='needs_activity_readings':
            self.generate(run,read(result['request_path']))
            result=super().readings(run,ref)
        return result

    def partitions(self,run,window,*,needed=False):
        proposals,key=super().partitions(run,window,needed=needed)
        if needed and not proposals:
            self.generate(run,read(self.directory/'requests'/f'{key}.json'))
            proposals,key=super().partitions(run,window,needed=needed)
        return proposals,key
