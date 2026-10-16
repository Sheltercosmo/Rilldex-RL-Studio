"""Exact training-use references connecting native logs to rollout evidence.

Numeric step equality, arrival order and experiment membership never create a
link. A native aggregate remains a batch/log value even if only some referenced
uses belong to a selected interval.
"""
from collections import defaultdict
from copy import deepcopy
import json

from .schema import InputError, dumps

VERSION='investigation-trainer-context/1'
BOUNDARY=('Links are producer-declared log context, resolved through exact training-use '
          'records and pinned source revisions. They do not establish each metric denominator '
          'or a sample contribution to an aggregate. Mixed-window and partial batches stay '
          'whole; no baseline/selected loss difference is inferred. Equal step numbers never join records.')


def _key(ref):return ref['producer'],ref['id'],ref['revision']


def _index(groups):
    index=defaultdict(list)
    for side,samples in groups.items():
        for sample in samples:
            if sample.get('join_status')!='matched' or not sample.get('run_id'):continue
            for r in sample.get('records',[]):
                if r['kind']!='use':continue
                key=(r['record_producer'],r['id'],r['revision'])
                item=dict(window=side,run_id=sample['run_id'],stage=r['data']['stage'],
                    learner_step=r['data'].get('learner_step'),batch_id=r['data'].get('batch_id'),
                    # Keep a compact exact reference, not another copy of native
                    # token tensors already retained in the training receipt.
                    use_record={k:deepcopy(r[k]) for k in ('id','revision','record_producer','kind','sample','evidence')})
                if item not in index[key]:index[key].append(item)
    return index


def _project(row,index):
    record=json.loads(row['document']);link=record.get('training_uses')
    references=[];windows=set();sources=set()
    for ref in (link or {}).get('records',[]):
        matches=index.get(_key(ref),[])
        # Conflicting source identities cannot establish one attribution.
        conflicting=len({(m['window'],m['run_id']) for m in matches})>1
        valid=[] if conflicting else matches
        references.append(dict(reference=deepcopy(ref),status='ambiguous_source_join' if conflicting else
            'matched' if valid else 'not_joined_to_selection',matches=deepcopy(valid)))
        windows.update(m['window'] for m in valid);sources.update(m['run_id'] for m in valid)
    return dict(producer=row['producer'],experiment=row['experiment'],record=record,
        references=references,windows=sorted(windows),run_ids=sorted(sources),
        matched_uses=sum(r['status']=='matched' for r in references),declared_uses=len(references),
        unmatched_uses=sum(r['status']!='matched' for r in references),
        declared_coverage=link['coverage'] if link else 'not_declared')


def capture(store,*,experiment,lineage,limit=500):
    """Capture native logs explicitly referencing uses in the frozen selection."""
    if type(limit) is not int or not 1<=limit<=2000:raise InputError('Select 1–2,000 native log records')
    groups={side:[{**sample,'run_id':r['run_id']} for r in window['rollouts'] for sample in r['samples']]
            for side,window in lineage['windows'].items()}
    index=_index(groups)
    with store.connect() as c:
        available=bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='trainer_telemetry_uses'").fetchone())
        if not available:return dict(schema=VERSION,records=[],truncated=False,record_limit=limit,
            selected_uses=len(index),referenced_selected_uses=0,unlinked_logs=None,boundary=BOUNDARY)
        unlinked=c.execute("""SELECT count(*) FROM trainer_telemetry WHERE experiment=?
            AND json_type(document,'$.training_uses') IS NULL""",(experiment,)).fetchone()[0]
        identities=[dict(producer=p,id=i,revision=r) for p,i,r in index]
        rows=c.execute('''WITH selected AS (
          SELECT json_extract(value,'$.producer') producer,json_extract(value,'$.id') id,
                 json_extract(value,'$.revision') revision FROM json_each(?))
          SELECT DISTINCT t.* FROM selected s JOIN trainer_telemetry_uses u
            ON u.experiment=? AND u.use_producer=s.producer AND u.use_id=s.id AND u.use_revision=s.revision
          JOIN trainer_telemetry t ON t.experiment=u.experiment AND t.producer=u.producer AND t.record_id=u.record_id
          ORDER BY t.received_at DESC,t.producer,t.record_id LIMIT ?''',
          (dumps(identities),experiment,limit+1)).fetchall() if identities else []
    records=[_project(r,index) for r in rows[:limit]]
    matched={_key(r['reference']) for log in records for r in log['references'] if r['status']=='matched'}
    return dict(schema=VERSION,records=records,truncated=len(rows)>limit,record_limit=limit,
        selected_uses=len(index),referenced_selected_uses=len(matched),unlinked_logs=unlinked,boundary=BOUNDARY)


def evidence(store,*,producer,experiment,record_id):
    """On-demand point evidence; available without a saved investigation."""
    from .training_lineage import snapshot
    with store.read_snapshot() as saved:
        with saved.connect() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='trainer_telemetry'").fetchone():
                raise InputError('This workspace has no native trainer logs')
            row=c.execute('SELECT * FROM trainer_telemetry WHERE producer=? AND experiment=? AND record_id=?',
                (producer,experiment,record_id)).fetchone()
        if row is None:raise InputError('Unknown native trainer log')
        linked='training_uses' in json.loads(row['document'])
        index=_index({'recorded':snapshot(saved,experiment=experiment)['samples']}) if linked else {}
        return dict(schema=VERSION,**_project(row,index),boundary=BOUNDARY)
