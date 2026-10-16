"""First recorded recheck outcomes, independent of retained input changes.

Uses the versioned recovery projection's comparability checks, but never its
change-conditioned success label or its search for a later passing witness.
"""
from collections import Counter
from copy import deepcopy
from .schema import InputError, digest

VERSION = 'retry-outcomes/1'
GROUPS = ('recorded_relevant_change', 'unchanged_captured_inputs',
          'changed_inputs_without_recorded_edit', 'unresolved_inputs')
LIMITS = [
    'One opportunity per visible failed check; only the first later recorded check of that criterion in the same actor and trajectory is used. No later pass rescues its outcome.',
    'Success means a comparable recorded passing check, not task success. Criterion version, scope, environment and captured stability must be comparable.',
    'Input categories describe captured state at dispatch. Unchanged captured inputs do not establish no semantic revision, no intervening work, or a deterministic environment.',
    'A recorded relevant change establishes at least one retained input edit, not complete attribution of every delta or a causal benefit of revision.',
    'Missing retries, unknown results and incomparable inputs remain unknown. Subgroup rates retain unresolved input membership as unknown and exclude known other groups.',
    'Overlapping failure opportunities in the same rollout are not independent samples. Rates are descriptive and conditional on capture and outcome coverage.',
    'Only existing feedback references before first recheck dispatch are retained. Absent references do not establish absence of feedback use.'
]


def ratio(records):
    n = sum(r['value'] is True for r in records)
    d = sum(r['value'] is not None for r in records)
    return dict(value=n / d if d else None, numerator=n, denominator=d,
                opportunities=len(records), unknown=len(records) - d)


def project(recovery, graph):
    if (recovery['run_id'], recovery['source_hash'], recovery['input_graph_id']) != (graph['run_id'], graph['source_hash'], graph['id']):
        raise InputError('Next-check input sources differ')
    nodes = {n['id']: n for n in graph['nodes']}
    edges = {e['id']: e for e in graph['edges']}
    records = []
    for old in recovery['records']:
        attempt = deepcopy(old['attempts'][0]) if old['attempts'] else None
        value = None
        group = 'unresolved_inputs'
        reasons = ['next_check_not_recorded']
        refs = []
        events = [old['failure_action_id'], old['failure_result_event_id']]
        if attempt:
            # These two reasons belong to the legacy change-conditioned label;
            # neither makes the captured inputs incomparable.
            issues = [i for i in attempt['issues'] if i not in
                      {'passing_check_without_supported_change', 'check_result_unknown'}]
            attempt['issues'] = issues
            if attempt['comparable']:
                group = ('recorded_relevant_change' if attempt['changes'] else
                         'changed_inputs_without_recorded_edit' if attempt['changed_inputs'] else
                         'unchanged_captured_inputs')
                if attempt['result'] in {'passed', 'failed'}:
                    value = attempt['result'] == 'passed'
            reasons = issues + (['check_result_unknown'] if attempt['result'] == 'unknown' else [])
            if not attempt['comparable'] and not reasons:
                reasons = ['comparison_unestablished']
            attempt['status'] = 'passed' if value is True else 'failed' if value is False else 'unknown'
            cutoff = nodes['event:' + attempt['action_id']]['event_index']
            refs = [eid for eid in old['feedback_reference_edge_ids']
                    if nodes[edges[eid]['source']]['event_index'] < cutoff]
            events += [attempt['action_id'], attempt.get('result_event_id')]
            for change in attempt['changes']:
                events += [change['action_id'], change['result_event_id']]
        records.append(dict(
            id='next-check-' + digest([graph['id'], old['failure_action_id'], VERSION]),
            failure_action_id=old['failure_action_id'], failure_result_event_id=old['failure_result_event_id'],
            criterion_id=old['criterion_id'], criterion_version=old['criterion_version'],
            required_objects=old['required_objects'], attempts=[attempt] if attempt else [],
            input_response=group, value=value,
            status='passed' if value is True else 'failed' if value is False else 'unknown',
            unknown_reasons=sorted(set(reasons)) if value is None else [],
            feedback_reference_edge_ids=refs, event_ids=list(dict.fromkeys(e for e in events if e))))
    strata = []
    for group in GROUPS:
        selected = [r for r in records if r['input_response'] == group]
        strata.append(dict(input_response=group, **ratio(selected),
                           failed=sum(r['value'] is False for r in selected)))
    return dict(schema=VERSION, run_id=graph['run_id'], source_hash=graph['source_hash'],
                input_graph_id=graph['id'], recovery_projection_id=recovery['id'],
                state_projection_id=recovery['state_projection_id'],
                window=dict(unit='first_recorded_same_criterion_check', count=1), records=records,
                metrics=ratio(records), coverage=dict(
                    strata=strata, recorded_checks=recovery['coverage']['recorded_checks'],
                    excluded_failures=recovery['coverage']['excluded_failures'],
                    unknown_reasons=dict(Counter(x for r in records for x in r['unknown_reasons']))), limits=LIMITS)


def measure(output, group='all'):
    if group not in ('all', 'recorded_relevant_change', 'unchanged_captured_inputs'):
        raise InputError('Unknown next-check input group')
    cases = []
    excluded = 0
    membership_unknown = 0
    for row in output['records']:
        if group != 'all' and row['input_response'] not in (group, 'unresolved_inputs'):
            excluded += 1
            continue
        unresolved = group != 'all' and row['input_response'] == 'unresolved_inputs'
        membership_unknown += int(unresolved)
        cases.append(dict(id=row['id'], label=row['criterion_id'] + ' · failure ' + row['failure_action_id'],
                          taken=None if unresolved else row['value'],
                          status='input_group_unestablished' if unresolved else row['status'],
                          node_ids=['event:' + eid for eid in row['event_ids']],
                          edge_ids=row['feedback_reference_edge_ids'], record=row, next_check=True))
    metrics = ratio([dict(value=c['taken']) for c in cases])
    if group == 'all' and metrics != output['metrics']:
        raise InputError('Next-check opportunities do not reconcile with projection')
    return dict(**metrics, cases=cases, coverage=dict(output['coverage'], input_group=group,
        all_failures=len(output['records']), excluded_known_other_inputs=excluded,
        unknown_input_membership=membership_unknown),
        reason=None if metrics['denominator'] else 'No decidable next-check outcomes in this group; missing evidence remains unknown.')
