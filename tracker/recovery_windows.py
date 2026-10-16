"""Recovery over recorded, comparable checks; no source classification here.

Consumes the existing work-state projection. A positive may close a window
early; a negative needs all three comparable failing follow-up checks.
"""
from collections import Counter
from copy import deepcopy
from .schema import InputError,digest
from . import feedback_opportunities

VERSION='recovery-windows/1'
WINDOW=3
LIMITS=[
    'Recovery of a captured criterion after a recorded input change is not task success or a causal effect of a revision.',
    'The window is the next three recorded checks of the same criterion ID after the failed result, in the same actor and trajectory. Changed versions/scopes consume a slot but remain incomparable.',
    'A negative requires three comparable failed follow-up checks. Short windows, unknown results, changed criteria and passing results without a supported input change remain unknown.',
    'Producer state scope, criterion versions and stability assertions are not independently verified. Uncaptured dependencies or checks may change interpretation.',
    'Recorded feedback references are optional supporting evidence; missing links do not mean the agent ignored feedback.'
]


def project(state,graph):
    if (state['source_hash']!=graph['source_hash'] or state['run_id']!=graph['run_id']):raise InputError('Recovery input sources differ')
    events={n['properties']['id']:n['properties'] for n in graph['nodes'] if n['kind']=='event'}
    snapshots={s['id']:s for s in state['snapshots']};checks=state['checks'];edits=state['edits']
    feedback={r['response_event_id']:r for r in feedback_opportunities.project(graph)['observations']}
    nodes={n['id']:n for n in graph['nodes']};edge_index={e['id']:e for e in graph['edges']}
    def index(eid):return events[eid]['index'] if eid in events else -1
    def lane(eid):
        e=events[eid];return e['actor'],e['trajectory_id']
    def check_issues(q):
        issues=[];s=snapshots.get(q.get('snapshot_id'));scope=q.get('required_objects',[])
        if not s:issues.append('input_snapshot_missing')
        if not q.get('criterion_version'):issues.append('criterion_version_missing')
        if not scope or s and any(k not in s['objects'] for k in scope):issues.append('input_scope_missing')
        if q.get('state_stable') is not True:issues.append('input_stability_unestablished')
        if index(q.get('result_event_id'))<=index(q['action_id']):issues.append('result_not_recorded_after_dispatch')
        if any(index(q['action_id'])<index(e['result_event_id'])<index(q.get('result_event_id')) and
            lane(e['action_id'])==lane(q['action_id']) and set(e['changed_objects'])&set(scope) for e in edits):issues.append('input_changed_during_check')
        return issues
    records=[];excluded=[]
    for fail in checks:
        if fail['result']!='failed':continue
        result=events.get(fail.get('result_event_id'))
        if not result or result.get('agent_visibility')=='not_established':
            excluded.append({'action_id':fail['action_id'],'reason':'failed_result_not_visible'});continue
        failure_issues=check_issues(fail)
        future=[q for q in checks if index(q['action_id'])>index(fail['result_event_id']) and
            lane(q['action_id'])==lane(fail['action_id']) and q['criterion_id']==fail['criterion_id']][:WINDOW]
        attempts=[];witness=None
        for q in future:
            issues=list(failure_issues)+check_issues(q);a=snapshots.get(fail.get('snapshot_id'));b=snapshots.get(q.get('snapshot_id'))
            if q.get('criterion_version')!=fail.get('criterion_version'):issues.append('criterion_version_changed')
            if set(q.get('required_objects',[]))!=set(fail.get('required_objects',[])):issues.append('criterion_input_scope_changed')
            if a and b and a['environment']!=b['environment']:issues.append('environment_changed')
            changed={k for k in fail.get('required_objects',[]) if a and b and a['objects'].get(k)!=b['objects'].get(k)}
            changes=[]
            for e in edits:
                if not b or not changed or lane(e['action_id'])!=lane(fail['action_id']):continue
                if not index(fail['result_event_id'])<index(e['action_id'])<index(e['result_event_id'])<index(q['action_id']):continue
                before=snapshots[e['before_snapshot_id']];after=snapshots[e['after_snapshot_id']]
                overlap=set(e['changed_objects'])&changed
                if (overlap and before['environment']==after['environment']==b['environment'] and
                    all(after['objects'].get(k)==b['objects'].get(k) for k in overlap)):
                    changes.append({'action_id':e['action_id'],'result_event_id':e['result_event_id'],
                        'before_snapshot_id':e['before_snapshot_id'],'after_snapshot_id':e['after_snapshot_id'],'changed_inputs':sorted(overlap)})
            supported={k for e in changes for k in e['changed_inputs']}
            # At least one relevant, retained recorded change is necessary. This
            # is an association, not complete attribution of every state delta.
            comparable=not issues
            recovered=comparable and q['result']=='passed' and bool(supported)
            if q['result']=='unknown':issues.append('check_result_unknown')
            if q['result']=='passed' and not supported:issues.append('passing_check_without_supported_change')
            row={'action_id':q['action_id'],'result_event_id':q.get('result_event_id'),'result':q['result'],
                'comparable':comparable,
                'issues':sorted(set(issues)),'changed_inputs':sorted(changed),'changes':changes,
                'status':'recovered' if recovered else 'failed' if not issues and q['result']=='failed' else 'unknown'}
            attempts.append(row)
            if recovered:witness=row;break
        closed=len(attempts)==WINDOW
        negative=closed and all(q['status']=='failed' for q in attempts)
        value=True if witness else False if negative else None
        reasons=[] if value is not None else sorted(set(failure_issues+[issue for q in attempts for issue in q['issues']]+(['window_not_fully_observed'] if not closed else [])))
        reference_edges=[];cutoff=index(witness['action_id']) if witness else index(attempts[-1]['action_id']) if attempts else -1
        for eid in feedback.get(fail['result_event_id'],{}).get('edge_ids',[]):
            edge=edge_index[eid];node=nodes[edge['source']]
            if node['event_index']<cutoff:reference_edges.append(eid)
        source_ids=[fail['action_id'],fail['result_event_id']]
        for q in attempts:
            source_ids.extend([q['action_id'],q['result_event_id']])
            for e in q['changes']:source_ids.extend([e['action_id'],e['result_event_id']])
        records.append({'id':'recovery-window-'+digest([graph['id'],fail['action_id'],WINDOW]),
            'failure_action_id':fail['action_id'],'failure_result_event_id':fail['result_event_id'],
            'criterion_id':fail['criterion_id'],'criterion_version':fail.get('criterion_version'),
            'required_objects':fail.get('required_objects',[]),'attempts':attempts,'window_closed':closed or bool(witness),
            'value':value,'status':'recovered' if value is True else 'not_recovered_in_window' if value is False else 'unknown',
            'unknown_reasons':reasons,'recovery_action_id':witness['action_id'] if witness else None,
            'feedback_reference_edge_ids':reference_edges,'event_ids':list(dict.fromkeys(e for e in source_ids if e))})
    n=sum(r['value'] is True for r in records);d=sum(r['value'] is not None for r in records)
    output={'schema':VERSION,'run_id':state['run_id'],'source_hash':state['source_hash'],
        'state_projection_id':state['id'],'input_graph_id':graph['id'],'window':{'unit':'recorded_same_criterion_checks','count':WINDOW},
        'records':records,'metrics':{'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(records),'unknown':len(records)-d},
        'coverage':{'captured_checks':sum(bool(q.get('snapshot_id')) for q in checks),'recorded_checks':len(checks),
            'unknown_reasons':dict(Counter(reason for r in records for reason in r['unknown_reasons'])),
            'excluded_failures':excluded,'with_recorded_feedback_reference':sum(bool(r['feedback_reference_edge_ids']) for r in records)},'limits':LIMITS}
    return output


def evidence_graph(source,state_graph,output,*,version=VERSION,observer='recovery-evidence/1',
                   label='Recovery windows with source, state and unit evidence',opportunity_key='recovery_opportunity_id'):
    """One combined evidence graph, retaining semantic and captured state facts."""
    if source['run_id']!=state_graph['run_id'] or source['source_hash']!=state_graph['source_hash']:raise InputError('Recovery evidence sources differ')
    nodes={n['id']:deepcopy(n) for n in source['nodes']};edges={e['id']:deepcopy(e) for e in source['edges']}
    for n in state_graph['nodes']:
        if n['id'] in nodes and nodes[n['id']]!=n:raise InputError('Recovery evidence node collision')
        nodes[n['id']]=deepcopy(n)
    for e in state_graph['edges']:edges[e['id']]=deepcopy(e)
    for row in output['records']:
        for retry in row['attempts']:
            value={'source':'check:'+retry['action_id'],'target':'check:'+row['failure_action_id'],'type':'recorded_recheck_of',
                'properties':{'basis':'captured criterion identity; comparability is explicitly recorded','comparable':retry['comparable'],
                    'issues':retry['issues'],'window_version':version,opportunity_key:row['id'],'causal':False}}
            edge={'id':'edge-'+digest(value),**value};edges[edge['id']]=edge
        # References remain their original selected edges; no new assessment is inferred.
    content={k:deepcopy(v) for k,v in source.items() if k not in {'id','nodes','edges','counts'}}
    content.update(observer=observer,observer_label=label,
        annotation_hash=digest([source['id'],state_graph['id'],output]),
        nodes=sorted(nodes.values(),key=lambda n:n['id']),edges=sorted(edges.values(),key=lambda e:e['id']),
        counts={'nodes':len(nodes),'edges':len(edges),'unresolved_endpoints':sum(n['kind']=='unresolved_reference' for n in nodes.values())})
    return {'id':'graph-'+digest(content),**content}


def compare(values,focus,reference):
    groups={}
    for name,ids in [('focus',focus),('reference',reference)]:
        rows=[v for v in values if v['run_id'] in ids];ms=[v['metrics'] for v in rows]
        n=sum(m['numerator'] for m in ms);d=sum(m['denominator'] for m in ms);op=sum(m['opportunities'] for m in ms)
        known=[m['value'] for m in ms if m['value'] is not None]
        groups[name]={'rollouts':len(ids),'measured_rollouts':len(known),'metrics':{'value':n/d if d else None,
            'numerator':n,'denominator':d,'opportunities':op,'unknown':op-d,
            'mean_rollout_value':sum(known)/len(known) if known else None}}
    return {'schema':VERSION,'groups':groups,'records':values,'limits':LIMITS,
        'definition':'Primary rates pool decidable failed-check opportunities. Per-rollout means and unknown opportunities remain separate.'}
