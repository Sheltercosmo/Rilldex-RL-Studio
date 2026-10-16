"""Resolve metric observations against the current source and declared map input.

Independent source-bound observers need no semantic graph. A graph-bound record
must match that graph, or the same explicit observation input after a derived
projection rebuild. Neither a shared observer name nor equal scalar values prove
that two observations are interchangeable.
"""
from .schema import digest


def semantic_input_hash(document):
    # These fields are derived views; semantic_record recomputes its measures
    # from the original units, relations and inspection observations instead.
    return digest({k:v for k,v in document.items() if k not in {'sequence_patterns','plan_execution'}})


def matches_graph(record,graph):
    bound=record.get('graph_id') or record.get('observation_kind')=='semantic'
    if not bound:return True
    if not graph:return False
    if (record['source_hash']!=graph['source_hash'] or record['run_id']!=graph['run_id']
            or record['observer']!=graph['observer']):return False
    if record.get('graph_id')==graph['id']:return True
    annotation=record.get('annotation_hash')
    if not annotation:return False
    if record.get('observation_kind')=='semantic' and graph.get('metric_input_hash'):
        return annotation==graph['metric_input_hash']
    return annotation==graph.get('annotation_hash')


def resolve(store,*,catalog=None,observer=None,run_ids=None,metric=None,include_metrics=False):
    from .graph_store import catalog as graph_catalog
    from .rollout_metrics import VERSION
    catalog=catalog if catalog is not None else graph_catalog(store)
    graphs={(g['run_id'],g['observer']):g for g in catalog['graphs']}
    where=["json_extract(document,'$.schema')=?"];parameters=[VERSION]
    if observer is not None:where.append('observer=?');parameters.append(observer)
    if run_ids is not None:
        run_ids=list(run_ids)
        if not run_ids:return {'records':{},'unavailable':{}}
        where.append('run_id IN ('+','.join('?' for _ in run_ids)+')');parameters.extend(run_ids)
    projection='';projection_parameters=[]
    if metric is not None:
        projection=",json_extract(document,?) metric";projection_parameters=['$.metrics.'+metric]
    elif include_metrics:projection=",json_extract(document,'$.metrics') metrics"
    with store.connect() as c:
        rows=c.execute('''SELECT id,run_id,observer,created_at,
            json_extract(document,'$.source_hash') source_hash,
            json_extract(document,'$.graph_id') graph_id,
            json_extract(document,'$.annotation_hash') annotation_hash,
            json_extract(document,'$.observation_kind') observation_kind,
            json_extract(document,'$.observer_label') label'''+projection+
            ' FROM rollout_measurements WHERE '+' AND '.join(where)+' ORDER BY created_at,id',
            (*projection_parameters,*parameters)).fetchall()
    current={};unavailable={}
    for row in rows:
        row=dict(row);key=(row['run_id'],row['observer']);source=graphs.get((row['run_id'],'source'))
        if not source or row['source_hash']!=source['source_hash']:continue
        if not matches_graph(row,graphs.get(key)):
            unavailable[key]='The saved metric does not match the current map. Awaiting a matching observation.'
            continue
        current[key]=row
    return {'records':current,'unavailable':{k:v for k,v in unavailable.items() if k not in current}}
