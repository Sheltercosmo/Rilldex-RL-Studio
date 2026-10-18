"""Budgeted diagnostic monitoring of latest producer snapshots.

The worker journal measures inspection coverage, not model behavior. Failed,
queued and ineligible sources never become zero-valued diagnostic results.
"""
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import time

from . import diagnostic_monitors as source_monitor
from .schema import InputError,digest,dumps
from .semantic_extraction import read,write,replay_decision
from .semantic_workspace import exclusive


class CallBudgetReached(Exception):pass


def implementation(name):
    if name=='source':return source_monitor
    if name=='chains':
        from . import diagnostic_chains
        return diagnostic_chains
    if name=='search':
        from . import diagnostic_search
        return diagnostic_search
    if name=='requirements':
        from . import requirement_diagnostics
        return requirement_diagnostics
    raise InputError('Unknown diagnostic implementation')


def selection(run_ids=None,experiment=None,adapters=None):
    if run_ids is not None:
        if experiment or adapters or not run_ids:raise InputError('Select explicit run IDs or latest-source filters')
        if any(not isinstance(i,str) or not i.isalnum() for i in run_ids):raise InputError('Invalid rollout ID')
        return {'kind':'explicit_latest','run_ids':sorted(set(run_ids))}
    if experiment is not None and (not isinstance(experiment,str) or not experiment.strip()):raise InputError('Invalid experiment filter')
    if adapters and any(not isinstance(a,str) or not a.strip() for a in adapters):raise InputError('Invalid adapter filter')
    return {'kind':'latest','experiment':experiment,'adapters':sorted(set(adapters or []))}


def initialize(store,root,selector,protocol_name):
    root=Path(root);module=implementation(protocol_name)
    path=root/'worker.json'
    frozen=read(path) if path.exists() else None
    selected_protocol=(module.protocol(frozen['protocol']['schema']) if frozen and protocol_name in {'search','requirements'}
                       and frozen['implementation']==protocol_name else module.protocol())
    config={'schema':'diagnostic-worker/1','implementation':protocol_name,'protocol':selected_protocol,
            'selection':selector,'database_path':str(store.path.resolve()),
            'eligibility':'Latest complete producer revisions or explicit imports; source inspection requires recorded action coverage'}
    if path.exists() and read(path)!=config:raise InputError('Worker protocol, source selection or database changed; use a new workspace')
    if not path.exists():write(path,config)
    worker_id='monitor-'+digest({'config':config,'workspace':str(root.resolve())})[:24]
    return worker_id,config,module


def inventory(store,selector,protocol_name='chains',protocol_version=None):
    # Read immutable source documents, without rebuilding every semantic map.
    # The query keeps in-progress/failed latest revisions visible for coverage.
    with store.connect() as c:
        rows=c.execute('''SELECT r.id,r.document,v.producer,v.rollout_id,v.revision,v.state
            FROM runs r LEFT JOIN rollout_revisions v ON v.run_id=r.id
            WHERE v.run_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM rollout_revisions newer WHERE newer.producer=v.producer
                AND newer.rollout_id=v.rollout_id AND newer.revision>v.revision)
            ORDER BY r.imported_at,r.id''').fetchall()
    selected=[];found=set()
    for row in rows:
        if selector['kind']=='explicit_latest' and row['id'] not in selector['run_ids']:continue
        run=json.loads(row['document']);meta=run['metadata']
        if not isinstance(run.get('id'),str) or not run['id'].isalnum() or run['id']!=row['id']:raise InputError('Invalid immutable rollout identity')
        if selector['kind']=='latest':
            if selector['experiment'] is not None and meta.get('experiment')!=selector['experiment']:continue
            if selector['adapters'] and run['adapter'] not in selector['adapters']:continue
        found.add(row['id']);state=row['state'] or 'imported_snapshot'
        item={'run_id':run['id'],'source_hash':digest(run),'source_state':state,
              'task_id':meta.get('task_id'),'environment':meta.get('environment'),'adapter':run['adapter'],
              'producer':row['producer'],'rollout_id':row['rollout_id'] or run['id'],'revision':row['revision'],
              'eligibility':'ready','reason':None,'_run':run}
        if state not in {'complete','imported_snapshot'}:
            item.update(eligibility='waiting',reason='Latest producer snapshot is not complete')
        elif run['adapter']=='verl-generation':
            item.update(eligibility='ineligible',reason='Flattened generation has no recorded action coverage')
        else:
            source=(implementation('search').source_from_run(run, protocol_version or implementation('search').DEFAULT_VERSION)
                    if protocol_name=='search' else source_monitor.from_run(run))
            if source['action_coverage']=='unavailable':item.update(eligibility='ineligible',reason='Recorded action coverage is unavailable')
            elif not source['trace'].strip():item.update(eligibility='ineligible',reason='No readable recorded trace')
            elif protocol_name not in {'search','requirements'} and len(source['task'])+len(source['trace'])>source_monitor.MAX_CHARS:
                item.update(eligibility='ineligible',reason='Source exceeds current protocol bound; no source was clipped')
            else:item['_source']=source
        selected.append(item)
    if selector['kind']=='explicit_latest' and found!=set(selector['run_ids']):
        raise InputError('One or more selected runs are missing or superseded by a newer producer revision')
    return selected


def plan(store,selector,protocol_name='chains'):
    """Read-only eligibility and request-size preview; no provider or workspace."""
    module=implementation(protocol_name);rows=[]
    for item in inventory(store,selector,protocol_name):
        row={k:v for k,v in item.items() if not k.startswith('_')}
        if item['eligibility']=='ready':
            source=item['_source'];row['source_chars']=len(source['task'])+len(source['trace'])
            row['scan_requests_before_cache']=(sum(1 for _ in module.requests(source))+sum(1 for _ in module.term_requests(source)) if protocol_name=='requirements'
                else len(list(module.pages(module.index(source, module.protocol()['schema'])))) if protocol_name=='search' else 1)
            row['published_result_reusable']=published_measurement(store,item,module.protocol()) is not None
        rows.append(row)
    return {'protocol':module.protocol(),'rows':rows,'model_api_calls':0,
            'estimate_scope':('Upper bound before requirement selection and cache reuse. Use --max-new-calls to bound spending.' if protocol_name=='requirements' else
                'Initial scan requests before cache reuse. Candidate enumeration, linking and validation require additional data-dependent calls. Use --max-new-calls to bound spending.')}


def _attempts(store,worker_id):
    with store.connect() as c:
        rows=c.execute('SELECT document FROM diagnostic_attempts WHERE worker_id=? ORDER BY created_at,id',(worker_id,)).fetchall()
    latest={}
    for row in rows:
        value=json.loads(row['document']);latest[(value['run_id'],value['source_hash'])]=value
    return latest


def _save_attempt(c,worker_id,receipt):
    stamp=datetime.now(timezone.utc).isoformat();value={'worker_id':worker_id,**receipt}
    c.execute('INSERT INTO diagnostic_attempts VALUES (?,?,?,?,?,?)',
        (digest(value),worker_id,value['run_id'],value['source_hash'],dumps(value),stamp))


def published_measurement(store,item,protocol,preferred_id=None):
    """Reuse a unique audited publication; do not choose among conflicting versions."""
    with store.connect() as c:
        rows=c.execute('SELECT id,document FROM rollout_measurements WHERE run_id=? AND observer=?',(item['run_id'],protocol['id'])).fetchall()
    matches=[]
    for row in rows:
        record=json.loads(row['document'])
        if digest(record)!=row['id']:raise InputError('Published diagnostic measurement changed')
        result=record.get('diagnostic_result',{})
        if (result.get('coverage',{}).get('scan_complete') is not False
                and record.get('observation_kind')=='diagnostics' and record.get('source_hash')==item['source_hash']
                and result.get('input_hash')==digest(item['_source']) and result.get('protocol')==protocol
                and record.get('annotation_hash')==digest(result)):
            matches.append(row['id'])
    if preferred_id in matches:return preferred_id
    return matches[0] if len(matches)==1 else None


def coverage(population,attempts):
    counts=Counter();rows=[]
    for item in population:
        attempt=attempts.get((item['run_id'],item['source_hash']))
        status=item['eligibility'] if item['eligibility']!='ready' else attempt['status'] if attempt else 'pending'
        counts[status]+=1
        rows.append({**item,'status':status,'attempt':attempt})
    return {'population':len(population),'eligible':sum(p['eligibility']=='ready' for p in population),
            'counts':dict(counts),'rows':rows,
            'interpretation':'Latest scanned population. Complete means an audited diagnostic result was stored, not correct behavior or a live worker. Failed/ineligible/pending sources are not negative detections.'}


def execute(store,root,transport,*,selector,protocol_name='chains',max_new_calls=100,retry_failed=False,progress=None):
    if type(max_new_calls) is not int or not 0<=max_new_calls<=100000:raise InputError('Use a request budget from 0 to 100,000')
    if type(retry_failed) is not bool:raise InputError('retry_failed must be boolean')
    calls=0;completed=[];failures=[];pending=[]
    with exclusive(root):
        root=Path(root);worker_id,config,module=initialize(store,root,selector,protocol_name)
        items=inventory(store,selector,protocol_name,config['protocol']['schema']);population=[{k:v for k,v in row.items() if not k.startswith('_')} for row in items]
        document={'id':worker_id,'config':config,'population':population,'scanned_at':datetime.now(timezone.utc).isoformat()}
        with store.connect() as c:
            c.execute('INSERT INTO diagnostic_workers VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document,updated_at=excluded.updated_at',
                      (worker_id,dumps(document),document['scanned_at']))
        previous=_attempts(store,worker_id)
        for item in items:
            if item['eligibility']!='ready':continue
            rid=item['run_id'];old=previous.get((rid,item['source_hash']))
            existing=published_measurement(store,item,config['protocol'],old.get('measurement_id') if old and old['status']=='complete' else None)
            if old and old['status']=='complete' and existing==old['measurement_id']:
                completed.append({'run_id':rid,'measurement_id':old['measurement_id'],'reused_published_result':True});continue
            if existing:
                receipt={'run_id':rid,'source_hash':item['source_hash'],'protocol_id':config['protocol']['id'],
                    'attempt_id':str(time.time_ns()),'status':'complete','new_calls':0,'provider_responses':0,
                    'measurement_id':existing,'reused_published_result':True,'finished_at':datetime.now(timezone.utc).isoformat()}
                with store.connect() as c:_save_attempt(c,worker_id,receipt)
                completed.append({'run_id':rid,'measurement_id':existing,'reused_published_result':True});continue
            if old and old['status']=='failed' and not retry_failed:
                failures.append({'run_id':rid,'error_type':old.get('error_type'),'held_for_explicit_retry':True});continue
            run=item['_run'];source=item['_source'];folder=root/'runs'/rid/item['source_hash']
            receipt={'run_id':rid,'source_hash':item['source_hash'],'protocol_id':config['protocol']['id'],
                'attempt_id':str(time.time_ns()),'status':'running','new_calls':0,'provider_responses':0,
                'started_at':datetime.now(timezone.utc).isoformat()}
            with store.connect() as c:_save_attempt(c,worker_id,receipt)
            try:
                path=folder/'source.json'
                if path.exists() and read(path)!=run:raise InputError('Frozen diagnostic source changed')
                write(path,run)
                def budgeted(req):
                    nonlocal calls
                    if calls>=max_new_calls:raise CallBudgetReached()
                    calls+=1;receipt['new_calls']+=1;receipt['last_request_hash']=digest(req)
                    response=transport(req);receipt['provider_responses']+=1
                    write(folder/'responses'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                    if progress:progress({'run_id':rid,'stage':req['state'].get('stage','source_detection'),'new_calls':calls})
                    return response
                result=(module.execute(source,folder,budgeted,version=config['protocol']['schema'])
                        if protocol_name in {'search','requirements'} else module.execute(source,folder,budgeted))
                if result.get('coverage',{}).get('scan_complete') is False:
                    # Publish actionable findings immediately; keep scanning on
                    # resume. A budget-limited absence never publishes zero.
                    receipt.update(status='pending',reason='Process request budget reached',
                        inspection_progress=result['coverage'],result_hash=digest(result),finished_at=datetime.now(timezone.utc).isoformat())
                    record=module.metric_record(run,source,result,folder) if result.get('findings') else None
                    from .rollout_metrics import save
                    with store.connect() as c:
                        c.execute('BEGIN IMMEDIATE')
                        if record:receipt['measurement_id']=save(c,record)
                        _save_attempt(c,worker_id,receipt)
                    pending.append(rid)
                    continue
                record=module.metric_record(run,source,result,folder)
                if (folder/'search-progress.json').exists():receipt['inspection_progress']=read(folder/'search-progress.json')
                # The successful attempt and its audited metric publish together.
                from .rollout_metrics import save
                with store.connect() as c:
                    c.execute('BEGIN IMMEDIATE');key=save(c,record)
                    receipt.update(status='complete',measurement_id=key,result_hash=digest(result),finished_at=datetime.now(timezone.utc).isoformat())
                    _save_attempt(c,worker_id,receipt)
                completed.append({'run_id':rid,'measurement_id':key,'reused_published_result':False})
            except CallBudgetReached:
                if (folder/'search-progress.json').exists():receipt['inspection_progress']=read(folder/'search-progress.json')
                receipt.update(status='pending',reason='Process request budget reached')
                pending.append(rid)
                with store.connect() as c:_save_attempt(c,worker_id,receipt)
            except KeyboardInterrupt:
                receipt.update(status='interrupted',error_type='KeyboardInterrupt')
                with store.connect() as c:_save_attempt(c,worker_id,receipt)
                raise
            except Exception as error:
                if (folder/'search-progress.json').exists():receipt['inspection_progress']=read(folder/'search-progress.json')
                receipt.update(status='failed',error_type=type(error).__name__)
                match=re.match(r'Jev request failed with HTTP (\d{3});',str(error))
                if match:receipt['http_status']=int(match.group(1))
                with store.connect() as c:_save_attempt(c,worker_id,receipt)
                failures.append({'run_id':rid,'error_type':type(error).__name__})
                # Authentication/rate/service failures are not source-specific.
                # Stop instead of billing every queued source for the same outage.
                if (receipt.get('http_status') in {401,403,429,500,502,503,504}
                        or str(error)=='Set JEV_API_KEY on the server before requesting semantic analysis'):
                    raise
            finally:
                receipt.setdefault('finished_at',datetime.now(timezone.utc).isoformat())
                write(folder/'executions'/f"{receipt['attempt_id']}.json",receipt)
                write(folder/'last-execution.json',receipt)
            # Keep examining sources after the budget: cached decisions may
            # finish a later rollout without spending a new request.
        summary=coverage(population,_attempts(store,worker_id))
        value={'worker_id':worker_id,'protocol':config['protocol'],'new_calls':calls,'completed':completed,
            'failed':failures,'pending_run_ids':pending,'coverage':summary,
            'status':'budget_reached' if pending else 'complete_with_failures' if failures else 'complete'}
        write(root/'last-scan.json',value)
        return value


def status(store,root):
    root=Path(root);config=read(root/'worker.json')
    worker_id,_,_=initialize(store,root,config['selection'],config['implementation'])
    try:
        with exclusive(root):busy=False
    except InputError:busy=True
    with store.connect() as c:row=c.execute('SELECT document FROM diagnostic_workers WHERE id=?',(worker_id,)).fetchone()
    document=json.loads(row['document']) if row else {'population':[],'scanned_at':None}
    return {'worker_id':worker_id,'workspace_busy':busy,'last_scanned_at':document['scanned_at'],
            'coverage':coverage(document['population'],_attempts(store,worker_id))}


def report(store):
    with store.connect() as c:rows=c.execute('SELECT document FROM diagnostic_workers ORDER BY updated_at DESC').fetchall()
    result=[]
    for row in rows:
        d=json.loads(row['document']);summary=coverage(d['population'],_attempts(store,d['id']))
        result.append({'worker_id':d['id'],'observer':d['config']['protocol']['id'],'selection':d['config']['selection'],
                      'last_scanned_at':d['scanned_at'],**summary})
    return result


def audit(store,root):
    with exclusive(root):
        root=Path(root);config=read(root/'worker.json')
        worker_id,_,module=initialize(store,root,config['selection'],config['implementation']);rows=[]
        for path in sorted((root/'runs').glob('*/*/source.json')):
            run=read(path);folder=path.parent
            if run['id']!=folder.parent.name or digest(run)!=folder.name:raise InputError('Frozen diagnostic source changed')
            source=(module.source_from_run(run, config['protocol']['schema'])
                    if config['implementation']=='search' else source_monitor.from_run(run))
            if (folder/'input.json').exists() and read(folder/'input.json')!=source:raise InputError('Frozen diagnostic input changed')
            validation=module.audit(source,read(folder/'result.json'),folder) if (folder/'result.json').exists() else None
            for packet in (folder/'decisions').glob('*.json'):
                saved=read(packet);state=saved['request']['state']
                if packet.stem!=digest(saved['request']) or state.get('input_hash',state.get('source_hash'))!=digest(source) or saved['answers']!=replay_decision(saved):
                    raise InputError('Diagnostic cached decision changed')
            rows.append({'run_id':run['id'],'source_hash':digest(run),'validation':validation})
        value={'worker_id':worker_id,'runs':rows,'scope':'Source integrity and decision replay; not semantic accuracy'}
        write(root/'audit.json',value);return value
