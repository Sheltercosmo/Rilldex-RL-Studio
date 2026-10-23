"""Resumable, experimental work-content extraction on one fixed source unit.

This workflow returns inspectable source qualifications; it does not publish a
semantic graph or infer execution from a proposed action.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import uuid

from . import candidate
from tracker import work_content_bindings as scopes, work_content_stages as stages
from tracker.jev import DEFAULT_MODEL, JevClient
from tracker.schema import InputError, digest
from tracker.semantic_budget import BudgetReached, ExecutionBudget, limits, summary
from tracker.semantic_extraction import read, write
from tracker.semantic_workspace import exclusive

VERSION = 'scoped-workflow/1'


def parse_source(packet, unit_id, *, model='en_core_web_sm'):
    """Parse the fixed source with an already installed local spaCy pipeline."""
    from tracker import work_syntax_evidence
    request=scopes.request(packet,unit_id)
    bound=scopes.bind(packet,request,dict(contents=[],features=[]),'syntax source binding')
    try:
        import spacy
    except ImportError:
        raise InputError('Install the optional nlp extra and a spaCy pipeline in this worker environment') from None
    try:
        parser=spacy.load(model,exclude=['ner'])
    except OSError:
        raise InputError('The requested spaCy pipeline is not installed in this worker environment') from None
    return work_syntax_evidence.from_spacy(packet,bound,parser(request['unit']['source']['text']),
        library_version=spacy.__version__,model=model,model_version=parser.meta['version'])


class _Stopped(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


class ProgressSaveError(RuntimeError):
    """Local responses remain reusable when a downstream progress writer fails."""


def extract(packet, unit_id, directory, *, candidate_calls=0, decision_calls=0,
            input_bytes=0, candidate_transport=None, candidate_identity=None,
            decision_transport=None, retry_failed=False, max_repairs=1,
            direct_arguments=True, syntax=None, content_policy=None, on_progress=None, relations=None):
    """Generate contents, then features, then independently inspect each scope.

    Limits are workspace-lifetime allowances. Identical resumes reuse all saved
    completions, including invalid responses. Raise allowances to continue.
    Custom candidate transports accept {request_hash, request} and return
    {raw_output, usage}; name their version with candidate_identity.
    One optional contract repair per generation stage uses the same allowance;
    originals remain saved. It receives binding errors, never reference answers.
    New workspaces use the current content policy. A resume keeps its recorded
    policy automatically; it never regenerates old work under new instructions.
    """
    if content_policy is not None and content_policy not in stages.CONTENT_POLICIES:
        raise InputError('unknown content policy')
    if on_progress is not None and not callable(on_progress):
        raise InputError('on_progress must be callable')
    if relations is not None and type(relations) is not bool:raise InputError('relations must be a boolean')
    if type(max_repairs) is not int or not 0 <= max_repairs <= 3:
        raise InputError('max_repairs must be between zero and three')
    cap = limits(dict(candidate_requests=candidate_calls, jev_requests=decision_calls,
                      input_bytes=input_bytes))
    if candidate_transport is None:
        if candidate_identity is not None:
            raise InputError('A custom candidate identity requires a custom transport')
        config = candidate.settings()
        identity = dict(adapter=candidate.VERSION, endpoint=config['endpoint'], model=config['model'])
        candidate_transport = lambda payload: candidate.completion(payload, **config)
    else:
        if not isinstance(candidate_identity,str) or not 0 < len(candidate_identity.strip()) <= 240:
            raise InputError('Name the custom candidate provider and version')
        identity = dict(adapter='custom', producer=candidate_identity)
    producer = candidate_identity or 'scoped-'+digest(identity)[:20]
    decision_transport = decision_transport or JevClient()._post
    with exclusive(directory) as root:
        prior_result=read(root/'result.json') if (root/'result.json').exists() else {}
        policy=prior_result.get('relation_policy')
        if policy is not None and policy not in scopes.LOCAL_RELATION_POLICIES:raise InputError('Saved relationship protocol differs; use a new directory')
        if policy and relations is False:raise InputError('Resume with relationships enabled to retain the saved analysis')
        include_relations=bool(policy) if relations is None else relations
        relation_policy=policy or scopes.LOCAL_RELATIONS
        if content_policy is None:
            saved = read(root/'model.json') if (root/'model.json').exists() else None
            if saved is None:
                content_policy = stages.DEFAULT_CONTENT_POLICY
            else:
                matches = [policy for policy in stages.CONTENT_POLICIES
                    if digest(stages.scoped_content_request(packet,unit_id,syntax=syntax,content_policy=policy))
                    == saved.get('content_request_hash')]
                if len(matches) != 1:
                    raise InputError('Saved source or content protocol differs; use the original settings or a new directory')
                content_policy = matches[0]
        first = stages.scoped_content_request(packet,unit_id,syntax=syntax,content_policy=content_policy)
        pin = dict(schema=VERSION, packet_hash=digest(packet), unit_id=unit_id,
                   candidate=identity, decision_model=DEFAULT_MODEL, content_request_hash=digest(first))
        if direct_arguments:
            pin['argument_rule'] = 'direct_owner'
        if syntax is not None:
            pin['syntax_id'] = syntax['id']
        stages._write_records(root, {'model.json':pin, 'packet.json':packet})
        if syntax is not None:
            stages._write_records(root, {'syntax.json':syntax})
        prior = summary(root)['providers']
        used = dict(candidate_requests=prior.get('candidate',{}).get('attempts',0),
                    jev_requests=prior.get('jev',{}).get('attempts',0),
                    input_bytes=sum(p['input_bytes'] for p in prior.values()))
        if any(cap[k] < used[k] for k in cap):
            raise InputError('Lifetime limits cannot be below recorded usage; reuse or raise them')
        budget = ExecutionBudget(root, uuid.uuid4().hex, {k:cap[k]-used[k] for k in cap})
        result = dict(schema=VERSION, directory=str(root.resolve()), unit_id=unit_id,
                      lifetime_limits=cap, model=identity, bound=None, review=None,
                      stage='contents', status='running', content_policy=content_policy,
                      direct_arguments=direct_arguments,
                      limit='Experimental source qualifications. Candidate inventory and modes are not independently verified. No graph publication or execution inference.')
        if include_relations:result.update(relation_policy=relation_policy,relations=None)

        def publish():
            result['usage'] = summary(root)
            write(root/'result.json',result)
            if on_progress is not None:
                try:on_progress(deepcopy(result))
                except Exception as exc:
                    raise ProgressSaveError('Saving extraction progress failed; saved model responses can be reused on resume') from exc

        def obtain(kind, request, callback):
            key = digest(request)
            path = root/'responses'/kind/(key+'.json')
            if path.exists():
                saved = read(path)
                if saved.get('request') != request or saved.get('model_hash') != digest(pin):
                    raise InputError('Saved response belongs to another source, protocol or model')
                return saved['response']
            previous = [read(p) for p in (root/'attempts').glob('*.json')]
            if not retry_failed and any(a['provider']==kind and a['request_hash']==key for a in previous):
                raise _Stopped('retry_required', dict(provider=kind, request_hash=key,
                    message='A previous attempt has no saved response. Provider completion and billing may be unknown. Set retry_failed=True to authorize another attempt.'))
            payload = request if kind=='jev' else dict(request_hash=key, request=request)
            response = budget.invoke(kind,request,lambda:callback(payload),payload=payload)
            # Save before parsing or binding. Invalid completions also cost work.
            write(path,dict(request=request, model_hash=digest(pin), response=response))
            return response

        def propose(request, bind):
            current = request
            for attempt in range(max_repairs+1):
                response = obtain('candidate',current,candidate_transport)
                try:
                    return bind(candidate.parse_completion(response))
                except (InputError, ValueError, KeyError, TypeError) as exc:
                    if attempt == max_repairs:
                        raise
                    current = dict(request, repair=dict(attempt=attempt+1,
                        previous_request_hash=digest(current),
                        previous_output=response.get('raw_output'),
                        binding_error=str(exc)[:500],
                        instructions='Repair the JSON schema and exact source citations. Return only the response_format keys. Preserve content choices and meanings; no reference answers or semantic corrections are supplied.'))

        responses = {}
        publish()
        try:
            contents = propose(first,lambda body:stages.bind_scoped_contents(packet,first,body,producer,
                syntax=syntax,content_policy=content_policy))
            stages._write_records(root, {'contents.json':contents})
            result['bound'] = contents
            if contents['contents']:
                result['stage'] = 'features'
                publish()
                scope_proposals = content_policy == 'legacy'
                feature_request = stages.scoped_feature_request(packet,contents,syntax=syntax,scope_proposals=scope_proposals)
                bound = propose(feature_request,lambda body:stages.bind_scoped_features(
                    packet,contents,feature_request,body,producer,syntax=syntax,scope_proposals=scope_proposals))
            else:
                bound = contents
            stages._write_records(root, {'bound.json':bound})
            result['bound'] = bound
            result['stage'] = 'scopes'
            result['review'] = scopes.scope_membership_review(packet,bound,responses,direct_arguments=direct_arguments,syntax=syntax)
            publish()
            for fid, request in scopes.scope_membership_requests(packet,bound,direct_arguments=direct_arguments,syntax=syntax).items():
                response = obtain('jev',request,decision_transport)
                # Validate before adding to the review. Earlier valid features
                # survive an invalid or missing later response.
                updated = scopes.scope_membership_review(packet,bound,{**responses,fid:response},direct_arguments=direct_arguments,syntax=syntax)
                responses[fid] = response
                result['review'] = updated
                write(root/'review.json',updated)
                publish()
            if include_relations:
                relation_responses={}
                result.update(stage='relationships',relations=scopes.local_relation_review(packet,bound,relation_responses,policy=relation_policy))
                publish()
                for page,request in scopes.local_relation_requests(packet,bound,policy=relation_policy).items():
                    response=obtain('jev',request,decision_transport)
                    updated=scopes.local_relation_review(packet,bound,{**relation_responses,page:response},policy=relation_policy)
                    relation_responses[page]=response;result['relations']=updated
                    write(root/'relations.json',updated);publish()
            result.update(status='complete', stage='complete')
        except ProgressSaveError:
            raise
        except BudgetReached as exc:
            result.update(status='budget_reached', detail=exc.reason)
        except _Stopped as exc:
            result.update(status=exc.status, detail=exc.detail)
        except (Exception, KeyboardInterrupt) as exc:
            # Preserve progress without leaking provider error bodies or secrets.
            result.update(status='needs_review', detail=dict(error_type=type(exc).__name__,
                message='Inspect the saved completion and source binding. Resume reuses returned responses; changed candidates need a new workspace.'))
        if result['review'] is not None:
            write(root/'review.json',result['review'])
        publish()
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet',help='Saved work_mentions.packet JSON')
    parser.add_argument('unit_id')
    parser.add_argument('directory')
    parser.add_argument('--candidate-calls',type=int,default=0)
    parser.add_argument('--decision-calls',type=int,default=0)
    parser.add_argument('--input-bytes',type=int,default=0)
    parser.add_argument('--retry-failed',action='store_true')
    parser.add_argument('--max-repairs',type=int,default=1)
    parser.add_argument('--relations',action='store_const',const=True,default=None,
        help='Inspect local work relationships; resumes reuse saved decisions')
    parser.add_argument('--content-policy',choices=stages.CONTENT_POLICIES,
        help='Defaults to the current policy for new work, or the saved policy on resume')
    source=parser.add_mutually_exclusive_group()
    source.add_argument('--syntax',help='Saved parser-neutral syntax record')
    source.add_argument('--spacy-model',help='Name or path of an installed local spaCy pipeline')
    args = parser.parse_args(argv)
    try:
        packet=read(args.packet)
        syntax=read(args.syntax) if args.syntax else parse_source(packet,args.unit_id,model=args.spacy_model) if args.spacy_model else None
        result = extract(packet,args.unit_id,args.directory,
            candidate_calls=args.candidate_calls,decision_calls=args.decision_calls,
            input_bytes=args.input_bytes,retry_failed=args.retry_failed,max_repairs=args.max_repairs,
            syntax=syntax,content_policy=args.content_policy,relations=args.relations)
    except (InputError,ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({k:v for k,v in result.items() if k not in {'bound','review','relations'}},ensure_ascii=False))
    return 0 if result['status']=='complete' else 2


if __name__=='__main__':
    raise SystemExit(main())
