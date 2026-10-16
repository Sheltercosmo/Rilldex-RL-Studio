"""Factor recorded recurrences by procedure and linked correction location.

This is an evidence projection, not an exploration or successful-recovery
classifier. Every count resolves to an exact previously observed pair.
"""
from collections import Counter
from copy import deepcopy

from . import work_episodes
from .schema import digest

DEPENDENCY = work_episodes.VERSION
VERSION = 'adaptation-patterns/1+' + DEPENDENCY
PROCEDURES = {
    'same_procedure': 'Same dispatched procedure',
    'reconfigured_procedure': 'Changed settings or inputs',
    'alternative_procedure': 'Different procedure',
    'unresolved': 'Procedure not established',
}
LOCATIONS = {
    'before_recurrence': 'Separate preparation attempt',
    'at_recurrence': 'Correction in the retry',
    'both': 'Preparation and retry correction',
    'not_established': 'Correction link not established',
}
DEFINITION = (
    'Each recorded same-work recurrence occupies one procedure × correction-location cell. '
    'Procedure comes from the exact-pair staged observation, not command equality. '
    'Separate preparation requires a recorded correction/action/preparation path to the shared work; '
    'this does not establish a necessary prerequisite, changed environment, or successful repair. '
    'Missing correction links mean not established, not no correction. '
    'An alternative procedure is not automatically exploration or a changed objective. '
    'Unknown procedure comparisons remain in the matrix and outside the procedure-change denominator.'
)


def project(graph):
    base = work_episodes.project(graph)
    observations = (graph.get('semantic_context') or {}).get('work_observations', {})
    raw_methods = observations.get('method_observations', [])
    method_schema = observations.get('method_schema')
    records = []
    for episode in base['episodes']:
        method = episode.get('method')
        raw = [m for m in raw_methods if m.get('previous_unit_id') == episode['previous_unit_id']
               and m.get('current_unit_id') == episode['current_unit_id']]
        procedure = 'unresolved'
        reason = 'No usable exact-pair procedure observation.'
        # Do not promote an old combined judgment, incomplete selection, or a
        # conflicted work-instance review into a compared opportunity. The base
        # projection already checks the evidence prefix for this exact pair.
        if method and len(raw) == 1:
            m = raw[0]
            reviewed = m.get('basis') == 'procedure-review/1' and m.get('status') == 'reviewed'
            original_schema = (observations.get('method_schema') if method_schema != 'procedure-review/1' else
                               (graph.get('semantic_context') or {}).get('procedure_reviews', {}).get('original_schema'))
            if ((reviewed or original_schema == 'work-method-comparison/3' and m.get('status') == 'selected')
                    and m.get('work_instance') == 'same_work_instance'
                    and not m.get('upstream_identity_disputed')
                    and m.get('comparison') in PROCEDURES):
                procedure = m['comparison']
                reason = ('Named source-bound procedure review.' if reviewed else
                          'Selected exact-pair procedure comparison.' if procedure != 'unresolved'
                          else 'The procedure observer selected unresolved.')
        before = [a for a in episode['adjustments'] if a['timing'] == 'before_recurrence'
                  and a.get('scope') == 'preparation_for_shared_work']
        at = [a for a in episode['adjustments'] if a['timing'] == 'at_recurrence'
              and a.get('scope') == 'retry_dispatch']
        location = ('both' if before and at else 'before_recurrence' if before
                    else 'at_recurrence' if at else 'not_established')
        row = {'episode_id': episode['id'], 'target': episode['target'],
               'previous_unit_id': episode['previous_unit_id'], 'current_unit_id': episode['current_unit_id'],
               'procedure': procedure, 'procedure_reason': reason, 'correction_location': location,
               'preparation_edge_ids': sorted({a['edge_id'] for a in before}),
               'retry_correction_edge_ids': sorted({a['edge_id'] for a in at}),
               'method_request': method.get('request') if method else None,
               'work_request': method.get('work_request') if method else None,
               'episode': deepcopy(episode)}
        row['id'] = 'adaptation-case-' + digest([VERSION, graph['id'], row])
        records.append(row)
    known = [r for r in records if r['procedure'] != 'unresolved']
    changed = [r for r in known if r['procedure'] in {'reconfigured_procedure', 'alternative_procedure'}]
    counts = Counter((r['procedure'], r['correction_location']) for r in records)
    cells = [{'procedure': p, 'correction_location': loc, 'count': counts[p, loc],
              'case_ids': [r['id'] for r in records if (r['procedure'], r['correction_location']) == (p, loc)]}
             for p in PROCEDURES for loc in LOCATIONS]
    observed = bool(records or base['counts']['identity_reviewed'])
    value = {'schema': VERSION, 'dependency': DEPENDENCY, 'run_id': graph['run_id'],
             'graph_id': graph['id'], 'source_hash': graph['source_hash'], 'observer': graph['observer'],
             'metadata': graph.get('metadata', {}), 'observed': observed, 'records': records, 'cells': cells,
             'coverage': {**base['counts'], 'recurrences': len(records), 'procedure_compared': len(known),
                          'procedure_unknown': len(records) - len(known)},
             'procedure_change': {'numerator': len(changed), 'denominator': len(known),
                                  'opportunities': len(records), 'unknown': len(records) - len(known),
                                  'value': len(changed) / len(known) if known else None},
             'procedures': PROCEDURES, 'locations': LOCATIONS, 'definition': DEFINITION,
             'limits': [DEFINITION, 'Upstream semantic accuracy has not been independently established.']}
    return {'id': 'adaptation-patterns-' + digest(value), **value}


def compare(records, focus, reference):
    groups = {}
    for name, ids in [('focus', focus), ('reference', reference)]:
        selected = [r for r in records if r['run_id'] in ids]
        cases = [c for r in selected for c in r['records']]
        known = [c for c in cases if c['procedure'] != 'unresolved']
        cells = []
        # Counts pool episodes; per-rollout shares give each nonempty observed
        # rollout equal weight, so a long rollout cannot silently dominate.
        eligible = [r for r in selected if r['records']]
        for p in PROCEDURES:
            for loc in LOCATIONS:
                matching = [c for c in cases if (c['procedure'], c['correction_location']) == (p, loc)]
                shares = [sum(c['procedure'] == p and c['correction_location'] == loc for c in r['records'])
                          / len(r['records']) for r in eligible]
                cells.append({'procedure': p, 'correction_location': loc, 'count': len(matching),
                              'mean_rollout_share': sum(shares) / len(shares) if shares else None,
                              'case_ids': [c['id'] for c in matching]})
        n = sum(c['procedure'] in {'reconfigured_procedure', 'alternative_procedure'} for c in known)
        groups[name] = {'rollouts': len(ids), 'graphs': len(selected),
                        'observed_rollouts': sum(r['observed'] for r in selected),
                        'rollouts_with_recurrence': len(eligible), 'recurrences': len(cases), 'cells': cells,
                        'procedure_change': {'numerator': n, 'denominator': len(known),
                                             'opportunities': len(cases), 'unknown': len(cases) - len(known),
                                             'value': n / len(known) if known else None}}
    return {'schema': VERSION, 'dependency': DEPENDENCY, 'records': records, 'groups': groups,
            'procedures': PROCEDURES, 'locations': LOCATIONS, 'definition': DEFINITION}
