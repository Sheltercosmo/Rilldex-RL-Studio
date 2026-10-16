"""Compare saved whole-work memberships with typed, prefix-bound pair evidence.

This finds disagreements between observations. It chooses neither observation
as ground truth and never changes a graph, measurement or model receipt.
"""
from collections import Counter
from copy import deepcopy
from . import work_subjects
from .schema import digest

VERSION = 'work-scope-consistency/1'
TYPES = {
    'same_work_target': ('same_work_target', True),
    'same_action_target': ('same_work_target', True),
    'overlapping_work_scope': ('partial_work_overlap', False),
    'different_work_same_subject': ('different_work_same_subject', False),
    'similar_operation_distinct_target': ('different_instance', False),
}
PROFILES = {
    ('pair-derived-work', 'pair-derived-work/1'),
    ('immediate-work', '1'),
    ('jev-immediate-work', 'contribution-work-selection/1'),
    ('jev-immediate-work', 'contribution-work-selection/1|map-content-target/1'),
}


def finish(report, state):
    report['state'] = state
    return dict(id='scope-audit-'+digest(report), **report)


def project(graph):
    document = ((graph.get('semantic_context') or {}).get('work_subjects') or {}).get('document')
    report = dict(schema=VERSION, graph_id=graph['id'], source_hash=graph['source_hash'],
        run_id=graph['run_id'], records=[], conflicts=[], excluded=[],
        scope='Consistency of explicit whole-immediate-work memberships and saved typed pair judgments only. These observations may both be wrong. Untested pairs and independent semantic accuracy remain unknown. No inference, receipt rewriting or silent repair is performed.')
    if not document:
        return finish(report, 'work_membership_unavailable')
    profile = document.get('profile', work_subjects.DEFAULT_PROFILE)
    report['profile'] = deepcopy(profile)
    derived = document.get('schema') == work_subjects.DERIVED_VERSION
    if derived:
        from .scope_membership import validate
        grouping = validate(graph, document)
        report['grouping'] = deepcopy(grouping)
        report['grouping']['reviewed_bindings'] = sum(r['provenance']['kind']=='review' for r in document['bindings'])
    if (profile['id'],profile['version']) not in PROFILES:
        return finish(report, 'scope_not_comparable')
    events, units, _, _ = work_subjects.evidence_index(graph)
    rows = {r['unit_id']:r for r in document['bindings']}
    subjects = {s['id']:s for s in document['subjects']}
    for edge in sorted(graph['edges'],key=lambda e:e['id']):
        if edge['type'] not in TYPES: continue
        if derived and (edge['properties'].get('protocol') != 'contribution-scope-pairs/2' or
                        edge['properties'].get('scope_layer') != 'contribution-scope-graph/1'): continue
        expected_choice, expected_same = TYPES[edge['type']]
        current, prior = units.get(edge['source']), units.get(edge['target'])
        props = edge['properties']; reason = None
        if not current or not prior: reason = 'ineligible_or_missing_units'
        elif props.get('pair_choice',props.get('choice')) != expected_choice or not props.get('pair_request',props.get('request')):
            reason = 'typed_pair_receipt_unestablished'
        else:
            a,b=current['source'],prior['source']; ea,eb=events[a['event_id']],events[b['event_id']]
            cutoff=props.get('cutoff',{})
            if work_subjects.lane(current,events)!=work_subjects.lane(prior,events): reason='different_actor_or_context'
            elif not (eb['index']<ea['index'] or eb['index']==ea['index'] and b['end']<=a['start']):reason='prior_order_unestablished'
            elif (ea['kind']==eb['kind']=='action' and (
                    ea.get('parent_id') and ea.get('parent_id')==eb.get('parent_id') or
                    ea.get('source_message_index') is not None and ea.get('source_message_index')==eb.get('source_message_index'))):
                reason='parallel_dispatch_order_unestablished'
            elif cutoff.get('event_id')!=a['event_id'] or cutoff.get('end')!=a['end']:reason='pair_cutoff_mismatch'
            else:
                refs=props.get('evidence',[])
                if not isinstance(refs,list) or a not in refs or b not in refs:reason='endpoint_source_evidence_missing'
                else:
                    for ref in refs:
                        if not isinstance(ref, dict):
                            reason='invalid_source_evidence';break
                        event=events.get(ref.get('event_id')); start,end=ref.get('start'),ref.get('end')
                        if (not event or type(start) is not int or type(end) is not int or
                                not 0<=start<end<=len(event['text']) or event['text'][start:end]!=ref.get('text') or
                                ref.get('source_pointer')!=event.get('source_pointer')):
                            reason='invalid_source_evidence';break
                        if (event['index'],end)>(ea['index'],a['end']):reason='future_source_evidence';break
        if reason:
            report['excluded'].append(dict(edge_id=edge['id'],reason=reason));continue
        left,right=rows.get(edge['source']),rows.get(edge['target'])
        known=left and right and left['status']==right['status']=='bound'
        same=left['subject_id']==right['subject_id'] if known else None
        record=dict(edge_id=edge['id'],relation=edge['type'],pair_choice=expected_choice,
            pair_request=props.get('pair_request',props.get('request')),expected_same=expected_same,membership_same=same,
            status='unresolved_membership' if same is None else 'consistent' if same==expected_same else 'conflict',
            source_unit_id=edge['source'],target_unit_id=edge['target'],cutoff=deepcopy(props['cutoff']),
            evidence=deepcopy(props['evidence']),
            bindings=[dict(unit_id=uid,source=deepcopy(units[uid]['source']),binding=deepcopy(rows.get(uid)),
                           subject=deepcopy(subjects.get((rows.get(uid) or {}).get('subject_id'))))
                      for uid in (edge['target'],edge['source'])])
        record['id']='scope-case-'+digest([graph['id'],record]);report['records'].append(record)
        if record['status']=='conflict':report['conflicts'].append(record)
    report['counts']=dict(Counter(r['status'] for r in report['records']))
    report['counts'].update(checked_pairs=len(report['records']),excluded_pairs=len(report['excluded']),
                            bound_contributions=sum(r['status']=='bound' for r in rows.values()))
    report['affected_subject_ids']=sorted({b['binding']['subject_id'] for r in report['conflicts'] for b in r['bindings']})
    return finish(report, 'conflicts_found' if report['conflicts'] else 'no_conflicts_in_checked_pairs' if report['records'] else 'no_comparable_pair_evidence')
