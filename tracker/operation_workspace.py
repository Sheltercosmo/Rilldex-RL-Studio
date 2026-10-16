"""A reusable, resumable operation-observation protocol across rollout snapshots."""
from copy import deepcopy
from pathlib import Path
import time

from . import operation_outcomes as outcomes, execution_reports
from .jev import DEFAULT_MODEL, SELECTION_POLICY
from .schema import InputError, digest
from .semantic_extraction import Pipeline, read, write, replay_decision
from .semantic_workspace import exclusive


class CallBudgetReached(Exception):
    pass


def protocol():
    definition={'schema':'operation-observer-protocol/1','outcome_harness':outcomes.VERSION,
        'executor_report_harness':execution_reports.VERSION,'model':DEFAULT_MODEL,
        'selection_policy':SELECTION_POLICY,'readable_context':deepcopy(execution_reports.POLICY),
        'mechanism_criteria':deepcopy(outcomes.DELIVERY),'outcome_criteria':deepcopy(outcomes.OUTCOMES),
        'candidate_constraint':'failed_requires_current_executor_error_report_when_complete',
        'scope':'Visible source-bound dispatch/response pairs; no generated semantic units or target identities'}
    return {**definition,'id':'operations-'+digest(definition)[:24]}


def initialize(root):
    path=Path(root)/'protocol.json';current=protocol()
    if path.exists():
        if read(path)!=current:raise InputError('Observation protocol changed; use a new workspace directory')
    else:write(path,current)
    return current


def load_protocol(root):
    value=read(Path(root)/'protocol.json')
    if value!=protocol():raise InputError('Workspace protocol differs from this observer implementation')
    return value


def frozen(root,run):
    rid=run['id']
    if not isinstance(rid,str) or not rid.isalnum():raise InputError('Invalid normalized rollout ID')
    folder=Path(root)/'runs'/rid/digest(run);path=folder/'source.json'
    if path.exists():
        if read(path)!=run:raise InputError('Frozen operation source changed')
    else:write(path,run)
    return folder


def latest_ids(store):
    # Watch complete producer snapshots and explicit imports. Ingestion errors
    # and still-growing snapshots are not treated as complete rollouts.
    return [r['id'] for r in store.list() if not r.get('ingestion') or r['ingestion']['state']=='complete']


def execute(store,root,run_ids,transport,*,max_new_calls=300,progress=None):
    if isinstance(max_new_calls,bool) or not isinstance(max_new_calls,int) or not 0<=max_new_calls<=100000:
        raise InputError('Use a new-call budget from 0 to 100,000')
    ids=list(dict.fromkeys(run_ids));calls=0;completed=[];pending=[]
    with exclusive(root):
        definition=initialize(root)
        for index,rid in enumerate(ids):
            run=store.get(rid,raw=True)['run'];folder=frozen(root,run)
            started=time.time_ns();receipt={'schema':'operation-execution/1','run_id':rid,
                'source_hash':digest(run),'protocol_id':definition['id'],'started_at_ns':started,
                'status':'running','provider_responses':0,'new_call_limit':max_new_calls}
            write(folder/'last-execution.json',receipt)
            def recorded(req):
                nonlocal calls
                if calls>=max_new_calls:raise CallBudgetReached()
                calls+=1
                response=transport(req)
                # Persist a received response even when subsequent shape/model
                # validation rejects it. Never persist transport exception text.
                write(folder/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                receipt['provider_responses']+=1
                if progress:progress({'run_id':rid,'stage':req['state']['stage'],'new_calls':calls})
                return response
            engine=Pipeline(folder,None,recorded)
            try:
                result,validation=outcomes.execute(run,engine)
                saved=store.record_operation_observation(run,definition,result,folder,validation)
                receipt.update(status='complete',observation_id=saved['id'],result_hash=digest(result))
                completed.append(saved)
            except CallBudgetReached:
                receipt['status']='call_budget_reached';pending=ids[index:]
            except (Exception,KeyboardInterrupt) as error:
                receipt.update(status='interrupted',error_type=type(error).__name__)
                raise
            finally:
                receipt.update(validated_new_decisions=engine.calls,finished_at_ns=time.time_ns())
                write(folder/'last-execution.json',receipt);write(folder/'executions'/f'{started}.json',receipt)
            if pending:break
        return {'protocol':definition,'new_calls':calls,'completed':completed,'pending_run_ids':pending,
                'status':'call_budget_reached' if pending else 'complete',
                'limits':'Operation evidence only; no semantic target identity, Plan completion or independent accuracy. New-call budget counts decision requests; the built-in Jev client does not retry internally.'}


def status(root):
    definition=load_protocol(root);rows=[]
    # This is an actual process-owned lock check, not an inference from a receipt.
    try:
        with exclusive(root):busy=False
    except InputError:busy=True
    for path in sorted((Path(root)/'runs').glob('*/*/source.json')):
        run=read(path);folder=path.parent
        if run['id']!=folder.parent.name or digest(run)!=folder.name:raise InputError('Frozen operation source changed')
        result_path=outcomes.path_for(folder,run)
        rows.append({'run_id':run['id'],'source_hash':digest(run),
            'complete_result_present':result_path.exists(),
            'saved_decision_files':len(list((folder/'decisions').glob('*.json'))),
            'last_execution':read(folder/'last-execution.json') if (folder/'last-execution.json').exists() else None})
    return {'protocol':definition,'workspace_busy':busy,'runs':rows,
            'limits':'Receipts describe past execution; only workspace_busy checks a live process lock. Result presence alone is not an audit.'}


def audit(root):
    with exclusive(root):
        definition=load_protocol(root);rows=[]
        for path in sorted((Path(root)/'runs').glob('*/*/source.json')):
            run=read(path);folder=path.parent
            if run['id']!=folder.parent.name or digest(run)!=folder.name:raise InputError('Frozen operation source changed')
            result_path=outcomes.path_for(folder,run);validation=None
            if result_path.exists():validation=outcomes.audit(run,read(result_path),folder)
            for packet in (folder/'decisions').glob('*.json'):
                saved=read(packet)
                if (packet.stem!=digest(saved['request']) or saved['request']['state']['source_hash']!=digest(run)
                        or saved['answers']!=replay_decision(saved)):
                    raise InputError('Saved operation decision changed')
            rows.append({'run_id':run['id'],'source_hash':digest(run),'validation':validation,
                         'status':'complete' if validation else 'incomplete'})
        report={'schema':'operation-workspace-audit/1','protocol':definition,'runs':rows,
                'limits':'Source and software consistency; semantic accuracy is not independently measured.'}
        write(Path(root)/'audit.json',report);return report
