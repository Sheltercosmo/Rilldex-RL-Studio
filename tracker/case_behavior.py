"""Saved monitor evidence over explicit rollout selections, independent of clocks."""
from collections import Counter, defaultdict
from copy import deepcopy
import json

from . import case_comparisons, graph_store, monitoring, monitor_comparisons
from .schema import InputError, digest, dumps

VERSION = 'case-behavior/1'
MAX_MONITORS = 24


def _priority(monitor):
    key=monitor.get('metric') or monitor.get('analysis',{}).get('measure')
    return (0 if key in {'recorded_success','recorded_reward'} else 1 if monitor.get('group')=='Behavior' else 2,
            monitor['name'],monitor['id'])


def _choices(definitions, sources, requested):
    return [dict(id=m['id'],name=m['name'],observer=m['observer'],enabled=m['enabled'])
            for m in sorted(definitions,key=_priority)
            if m['id'] in requested or any(monitoring.in_population(m,r) for r in sources)]


def options(store, doc):
    """Include newly registered code monitors without modifying a saved capture."""
    if doc.get('schema')!='case-investigation/1':raise InputError('Choose a saved rollout comparison')
    snapshot=doc['snapshot'];ids=set(snapshot['population']['baseline'])|set(snapshot['population']['current'])
    return dict(choices=_choices(monitoring.definitions(store),[r for r in snapshot['source_rows'] if r['id'] in ids],
                               snapshot.get('behavior',{}).get('monitor_ids',[])))


def _point(run, value, graph):
    v = value or dict(value=None,status='pending',reason='No saved measurement at capture')
    return dict(run_id=run['id'],task_id=run['metadata'].get('task_id'),capture_state=run['state'],
        policy_version=run['metadata'].get('policy_version'),value=v['value'],status=v['status'],
        reason=v.get('reason'),value_id=v.get('id'),graph_id=graph.get('id') if graph else None,
        map_observer=graph.get('observer') if graph else None,
        numerator=v.get('numerator'),denominator=v.get('denominator'),
        opportunities=v.get('opportunities'),unknown_opportunities=v.get('unknown'),
        evidence_ids=deepcopy(v.get('evidence_ids',[])))


def _same_tasks(points, sources, aggregation):
    groups = defaultdict(lambda:dict(baseline=[],current=[]))
    incomplete = dict(baseline=0,current=0)
    for side, rows in points.items():
        for p in rows:
            context = {k:sources[p['run_id']]['metadata'].get(k) for k in case_comparisons.CONTEXT}
            if any(v is None or v=='' for v in context.values()):
                incomplete[side]+=1;continue
            groups[dumps(context)][side].append(p)
    tasks = []; unmatched = dict(baseline=0,current=0)
    for key, sides in sorted(groups.items()):
        if not all(sides.values()):
            for side, rows in sides.items(): unmatched[side]+=len(rows)
            continue
        summaries = {side:monitor_comparisons.summarize(rows,aggregation) for side,rows in sides.items()}
        tasks.append(dict(context=json.loads(key),points=sides,**summaries,
            measured_on_both=all(s['value'] is not None for s in summaries.values())))
    measured = [t for t in tasks if t['measured_on_both']]
    values = {side:sum(t[side]['value'] for t in measured)/len(measured) if measured else None
              for side in ('baseline','current')}
    return dict(**values,delta=monitor_comparisons.delta(values['baseline'],values['current']),
        contexts=len(tasks),measured_contexts=len(measured),incomplete_context_rollouts=incomplete,
        without_counterpart=unmatched,tasks=tasks,
        weighting='Equal weight per task context with measured evidence on both sides. Within each task, the monitor retains its configured aggregation.')


def _versions(store, monitor, points, values, cache):
    result={};definitions={}
    for side,rows in points.items():
        counts=Counter();missing=0
        for p in rows:
            if not p['value_id']:missing+=1;continue
            value=values[p['run_id']]
            definition=dict(observer=monitor['observer'],kind=monitor['kind'],
                engine=monitor.get('analysis',{}).get('version') or monitor.get('custom',{}).get('version')
                    or value.get('graph_monitor_version') or monitoring.METRIC_VERSION)
            if p['graph_id']:
                if p['graph_id'] not in cache:
                    with store.connect() as c:
                        raw=c.execute('SELECT document FROM rollout_graphs WHERE id=?',(p['graph_id'],)).fetchone()
                    graph=json.loads(raw[0]) if raw else {}
                    cache[p['graph_id']]={k:graph.get(k) for k in ('schema','adapter_version')}
                    provenance=(graph.get('semantic_context') or {}).get('provenance') or {}
                    if provenance:
                        # Revision parents are input identities, not detector versions.
                        # Exact lineage remains available through the pinned graph.
                        cache[p['graph_id']]['provenance']={k:v for k,v in provenance.items() if k!='revision'}
                definition['graph']=cache[p['graph_id']]
            key=digest(definition);definitions[key]=definition;counts[key]+=1
        result[side]=dict(counts=dict(counts),without_receipt=missing)
    return dict(**result,definitions=definitions,
                same_recorded_versions=set(result['baseline']['counts'])==set(result['current']['counts'])
                    if result['baseline']['counts'] and result['current']['counts'] else None)


def capture(store, sources, members, monitor_ids=None):
    """Read only: never materialize monitors or substitute a newer source."""
    selected_ids=set(members['baseline'])|set(members['current'])
    by_id={r['id']:r for r in sources if r['id'] in selected_ids}
    definitions=monitoring.definitions(store)
    choices=[m for m in definitions if any(monitoring.in_population(m,r) for r in by_id.values())]
    if monitor_ids is not None and (not isinstance(monitor_ids,list) or len(monitor_ids)>MAX_MONITORS
            or any(not isinstance(i,str) for i in monitor_ids) or len(set(monitor_ids))!=len(monitor_ids)):
        raise InputError('Select up to 24 distinct saved monitors')
    all_ids={m['id'] for m in definitions}
    if monitor_ids is not None and any(i not in all_ids for i in monitor_ids):raise InputError('Unknown saved monitor')
    requested=monitor_ids if monitor_ids is not None else [m['id'] for m in sorted(choices,key=_priority) if m['enabled']][:MAX_MONITORS]
    catalog=graph_store.catalog(store,run_ids=sorted(by_id)) if requested else {'graphs':[]}
    graphs={(g['run_id'],g['observer']):g for g in catalog['graphs']}
    panels=[];versions={}
    for monitor in sorted((m for m in definitions if m['id'] in requested),key=_priority):
        runs=[r for r in by_id.values() if monitoring.in_population(monitor,r)]
        values=monitoring.current_values(store,monitor,runs,catalog=catalog)
        points={side:[_point(by_id[rid],values.get(rid),graphs.get((rid,monitor['observer'])) or graphs.get((rid,'source')))
                     for rid in members[side] if rid in by_id and monitoring.in_population(monitor,by_id[rid])]
                for side in ('baseline','current')}
        aggregation=monitoring.aggregation(monitor)
        summary={side:monitor_comparisons.summarize(rows,aggregation) for side,rows in points.items()}
        panels.append(dict(monitor=monitor,aggregation=aggregation,unit=monitoring.unit(monitor),points=points,
            **summary,delta=monitor_comparisons.delta(summary['baseline']['value'],summary['current']['value']),
            same_tasks=_same_tasks(points,by_id,aggregation),
            versions=_versions(store,monitor,points,values,versions),
            excluded={side:len(members[side])-len(points[side]) for side in points}))
    return dict(schema=VERSION,panels=panels,monitor_ids=requested,
        choices=_choices(definitions,list(by_id.values()),requested),
        not_selected=len([m for m in choices if m['id'] not in requested]),
        boundary='Saved measurements of these exact rollout revisions. All-rollout values retain each monitor’s aggregation; same-task values give equal weight to shared complete task contexts. These are descriptive comparisons, not causal effects or significance tests.')
