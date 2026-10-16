"""An optional macro projection over audited work identity, retaining every unit."""
from copy import deepcopy

from .repeated_sequences import find
from .recurrence_context import build as interval_context
from .schema import digest
from .returning_sequences import find as find_returns

VERSION = 'work-sequence-patterns/1'
RETURN_VERSION = 'work-sequence-patterns/2'


def returning_work(run, document, stream, groups, tokens):
    """Keep pattern identity, source intervals and exact-pair judgments separate."""
    scan = find_returns(tokens)
    patterns, returns = [], []
    positions = stream['positions']
    methods = document.get('method_comparison', {}).get('observations', [])

    def block(start, length):
        return {'start_position': start + 1, 'end_position': start + length,
                'action_unit_ids': [p['unit_id'] for p in positions[start:start + length]]}

    for pattern in scan['patterns']:
        identity = 'work-return-pattern-' + digest([stream['id'], pattern])[:20]
        targets = [groups[g]['target'] for g in pattern['pattern']]
        projected = {'id': identity, 'stream_id': stream['id'], 'length': pattern['length'],
                     'pattern_targets': targets, 'group_ids': pattern['pattern'],
                     'at_length_limit': pattern['at_length_limit'],
                     'occurrences': [block(s, pattern['length']) for s in pattern['starts']],
                     'return_ids': []}
        for pair in pattern['returns']:
            previous = block(pair['previous_start'], pair['length'])
            current = block(pair['current_start'], pair['length'])
            gap = positions[pair['gap_start']:pair['gap_end']]
            comparisons = []
            for group_id, before, after in zip(pattern['pattern'], previous['action_unit_ids'], current['action_unit_ids']):
                # A method label belongs to exactly these endpoints. Another
                # comparison in the same target group cannot fill this gap.
                method_index = next((i for i, m in enumerate(methods) if
                    (m['group_id'], m['previous_unit_id'], m['current_unit_id']) ==
                    (group_id, before, after)), None)
                comparisons.append({'group_id': group_id, 'previous_unit_id': before,
                    'current_unit_id': after, 'method_observation_index': method_index,
                    'method_observation_hash': digest(methods[method_index]) if method_index is not None else None,
                    'context': interval_context(run, document, before, after)})
            context = interval_context(run, document, previous['action_unit_ids'][0], current['action_unit_ids'][-1])
            # The range endpoints can have different targets. Only aligned
            # operation pairs above support invocation/procedure comparison.
            context.pop('dispatch_comparison')
            value = {'id': 'work-return-' + digest([identity, pair])[:20],
                     'pattern_id': identity, 'stream_id': stream['id'],
                     'actor': stream['actor'], 'trajectory_id': stream['trajectory_id'],
                     'pattern_targets': targets, 'previous': previous, 'current': current,
                     'gap': {'start_position': pair['gap_start'] + 1, 'end_position': pair['gap_end'],
                             'operation_positions': len(gap),
                             'action_unit_ids': [p['unit_id'] for p in gap if p['unit_id'] is not None],
                             'unrepresented_action_event_ids': [p['event_id'] for p in gap if p['unit_id'] is None],
                             'unresolved_identity_positions': [i + 1 for i in pair['missing_gap_positions']]},
                     'comparisons': comparisons, 'context': context}
            projected['return_ids'].append(value['id'])
            returns.append(value)
        patterns.append(projected)
    return scan, patterns, returns


def build(run, document, *, include_returns=False):
    history = document.get('work_history', {})
    result = {'version': VERSION, 'available': bool(history.get('available')),
              'base_map_hash': digest(document), 'source_hash': digest(run), 'streams': [], 'runs': [],
              'basis': 'Selected immediate-work identity, independent of activity labels or exact command equality.',
              'limits': 'This retrospective projection finds consecutive repetition of selected target sequences. Different methods, intervening prose, feedback and changed conditions remain in the focused interval. It does not establish failed retries, active goals, exploration, exploitation, deviation or progress. Missing or disputed identity is a barrier; no detected pattern does not prove absence of recurring work.'}
    if include_returns:
        result.update(version=RETURN_VERSION, returning_patterns=[], returns=[])
        result['limits'] += ' Separated returns retain the entire intervening interval and compare aligned operations only. Return patterns and pairs can overlap; their counts are not distinct-work or waste rates. Uninspected scan scope stays explicit.'
    if not result['available']:
        result['reason'] = 'Selected immediate-work identities are unavailable.'
        return result
    disputed = {r['group_id'] for r in document.get('method_comparison', {}).get('observations', [])
                if r.get('comparison') == 'different_work'}
    for stream in history['streams']:
        groups = {g['id']: g for g in stream['groups']}
        group_for = {o['unit_id']: g['id'] for g in stream['groups'] for o in g['occurrences']}
        # Positive within-group identity supports equality even when a root's
        # relationship to older, other work remained unresolved. Singletons
        # cannot supply repeated membership; they still occupy source positions.
        tokens = []
        for position in stream['positions']:
            group_id = group_for.get(position['unit_id'])
            group = groups.get(group_id)
            tokens.append(group_id if group and not group.get('disputed_identity') and group_id not in disputed else None)
        scanned = find(tokens)
        output = {'stream_id': stream['id'], 'actor': stream['actor'], 'trajectory_id': stream['trajectory_id'],
                  'scan': scanned, 'run_ids': []}
        for row in scanned['runs']:
            positions = stream['positions'][row['start']:row['end']]
            members = [p['unit_id'] for p in positions]
            value = {**row, 'stream_id': stream['id'], 'actor': stream['actor'],
                     'trajectory_id': stream['trajectory_id'],
                     'id': 'work-pattern-' + digest([stream['id'], row])[:20],
                     'start_position': row['start'] + 1, 'end_position': row['end'],
                     'pattern_targets': [groups[g]['target'] for g in row['pattern']],
                     'action_unit_ids': members,
                     'copies': [members[i:i + row['period']] for i in range(0, len(members), row['period'])],
                     'context': interval_context(run, document, members[0], members[-1])}
            output['run_ids'].append(value['id'])
            result['runs'].append(value)
        if include_returns:
            scan, patterns, returns = returning_work(run, document, stream, groups, tokens)
            output.update(return_scan=scan, return_ids=[r['id'] for r in returns])
            result['returning_patterns'].extend(patterns)
            result['returns'].extend(returns)
        result['streams'].append(output)
    result['counts'] = {'periodic_regions': len(result['runs']),
                        'multi_target_regions': sum(r['period'] > 1 for r in result['runs']),
                        'repeated_operation_positions': sum(len(s['scan']['repeated_positions']) for s in result['streams'])}
    if include_returns:
        result['counts'].update(returning_patterns=len(result['returning_patterns']),
                                separated_returns=len(result['returns']),
                                return_streams_uninspected=sum(s['return_scan']['status'] != 'complete' for s in result['streams']))
    return result


def project(result, run, *, include_returns=False):
    """Leave saved observations, catalog bindings and old exports unchanged."""
    if not result.get('available'):
        return result
    projected = deepcopy(result)
    projected['document']['sequence_patterns'] = build(run, result['document'], include_returns=include_returns)
    if projected.get('observer'):
        from .semantic_catalog import export_payload
        projected['export_digest'] = digest(export_payload(projected))
    return projected
