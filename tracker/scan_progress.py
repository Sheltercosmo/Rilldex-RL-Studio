"""Read saved worker coverage without opening scan directories or calling models."""
from collections import Counter
import json

from .diagnostic_worker import _attempts


def snapshot(store, experiment=None, environment=None):
    with store.read_snapshot() as saved, saved.connect() as c:
        # Scalar metadata avoids loading full rollout traces on every refresh.
        current={r['id']:dict(r) for r in c.execute('''
            SELECT r.id, json_extract(r.document,'$.metadata.task_id') task,
                   json_extract(r.document,'$.metadata.experiment') experiment,
                   json_extract(r.document,'$.metadata.environment') environment,
                   json_extract(r.document,'$.adapter') adapter,
                   COALESCE(v.state,'imported_snapshot') source_state
            FROM runs r LEFT JOIN rollout_revisions v ON v.run_id=r.id
            WHERE v.run_id IS NULL OR NOT EXISTS (SELECT 1 FROM rollout_revisions newer
                WHERE newer.producer=v.producer AND newer.rollout_id=v.rollout_id AND newer.revision>v.revision)''')}
        def in_scope(row):
            return (not experiment or (not row.get('experiment') if experiment=='__unassigned__' else row.get('experiment')==experiment)) and (not environment or row.get('environment')==environment)
        workers=[]
        records=c.execute('SELECT document,updated_at FROM diagnostic_workers ORDER BY updated_at DESC LIMIT 50').fetchall()
        for record in records:
            d=json.loads(record['document']);config=d['config'];attempts=_attempts(saved,d['id'])
            counts=Counter();rows=[];superseded=0;recapture=set()
            for item in d['population']:
                meta=current.get(item['run_id'])
                if meta is None:
                    superseded+=1;continue
                if not in_scope(meta):continue
                capturing=meta['source_state'] not in {'complete','imported_snapshot'}
                newly_complete=not capturing and item['eligibility']=='waiting'
                if newly_complete:recapture.add(item['run_id'])
                a=attempts.get((item['run_id'],item['source_hash'])) or {}
                p=a.get('inspection_progress') or {}
                requests=p.get('requests_completed',p.get('requests',p.get('scan_requests')))
                inspected=max(p.get('pages_scanned',0),requests or 0)
                state=a.get('status','pending')
                status=('waiting' if capturing else 'not_scanned' if newly_complete else 'unavailable' if item['eligibility']=='ineligible'
                        else 'complete' if state=='complete' else 'failed' if state=='failed'
                        else 'partial' if inspected or a.get('measurement_id') else 'not_scanned')
                counts[status]+=1
                rows.append(dict(run_id=item['run_id'],task=meta['task'] or 'Rollout',status=status,last_state=state,
                    pages_scanned=p.get('pages_scanned'),pages_total=p.get('pages_total'),requests_completed=requests,
                    stage=p.get('stage'),new_calls=a.get('new_calls',0),provider_responses=a.get('provider_responses',0),
                    request_state=a.get('request_state'),
                    updated_at=a.get('finished_at') or a.get('updated_at') or a.get('started_at'),
                    reason=('Latest producer snapshot is not complete' if capturing else 'Completed source awaits the next worker inventory' if newly_complete
                            else item.get('reason') or a.get('reason') or a.get('error_type')),measurement_id=a.get('measurement_id')))
            selection=config['selection'];known={r['run_id'] for r in d['population']}
            def selected(meta):
                if selection['kind']=='explicit_latest':return meta['id'] in selection['run_ids']
                return (selection.get('experiment') is None or meta['experiment']==selection['experiment']) and (not selection.get('adapters') or meta['adapter'] in selection['adapters'])
            waiting=len(recapture)+sum(r['id'] not in known and selected(r) and in_scope(r) for r in current.values())
            if (experiment or environment) and not rows and not waiting:continue
            rows.sort(key=lambda r:({'partial':0,'failed':1,'not_scanned':2}.get(r['status'],3),r['task'],r['run_id']))
            workers.append(dict(id=d['id'],protocol=config['implementation'],protocol_version=config['protocol']['schema'],
                observer=config['protocol']['id'],workspace_path=d.get('workspace_path'),database_path=config['database_path'],selection=selection,
                inventory_at=d['scanned_at'],updated_at=max([record['updated_at']]+[r['updated_at'] for r in rows if r['updated_at']]),
                population=len(rows),counts=dict(counts),awaiting_inventory=waiting,superseded=superseded,rows=rows[:100],row_limit=100))
        return dict(workers=workers,limit=50,scope='Latest source revisions within each saved worker inventory; counts are scan coverage, not negative detections.')
