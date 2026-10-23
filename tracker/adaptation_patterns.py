"""Factor recorded recurrences by procedure and linked correction location.

This is an evidence projection, not an exploration or successful-recovery
classifier. Every count resolves to an exact previously observed pair.
"""
from collections import Counter
from copy import deepcopy

from . import work_episodes, repeated_work, approach_feedback
from .schema import digest

DEPENDENCY = work_episodes.VERSION
VERSION = 'adaptation-patterns/4+' + repeated_work.RECIPE.replace('|','+')+'+'+approach_feedback.VERSION
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


def _reason_resolver(graph):
    """Resolve the selected reason, never guess one from nearby text."""
    nodes={n['id']:n for n in graph['nodes']}
    grounded={(e['source'],e['target']) for e in graph['edges'] if e['type']=='grounded_in'}
    labels={'no_expressed_basis':'No explicit reason selected in the supplied text.',
            'distributed_basis':'The selected reason spans several contributions.',
            'unresolved_basis':'The observer could not resolve the stated reason.',
            'not_inspected':'The stated reason was not inspected.'}
    def resolve(method,episode):
        choice=(method or {}).get('stated_basis')
        empty=dict(status='unavailable',label='No source-bound reason available.',node_id=None,text=None)
        if not method or method.get('status') not in {'selected','reviewed'}:return empty
        if choice in labels:return {**empty,'status':choice,'label':labels[choice]}
        if not isinstance(choice,str) or choice not in method.get('rationale_candidate_ids',[]):return empty
        unit=nodes.get(choice);prior=nodes.get(episode['previous_unit_id']);current=nodes.get(episode['current_unit_id'])
        if not unit or unit['kind']!='unit' or not prior or not current:return empty
        p=unit['properties'];ref=p.get('source',{});event=nodes.get('event:'+str(ref.get('event_id')))
        if not event or (choice,event['id']) not in grounded or p.get('kind')!='semantic':return empty
        e=event['properties'];a,b=ref.get('start'),ref.get('end');text=e.get('text','')
        if (type(a) is not int or type(b) is not int or not 0<=a<b<=len(text) or text[a:b]!=ref.get('text')
                or e.get('copied_context') or e.get('agent_visibility')=='not_established' or e.get('order_known') is False):return empty
        references=method.get('inspector_context',{}).get('source_ranges',[])
        if not any(r.get('event_id')==ref['event_id'] and type(r.get('start')) is int and type(r.get('end')) is int
                   and r['start']<=a<b<=r['end'] for r in references):return empty
        for endpoint in (prior,current):
            ep=endpoint['properties'];er=ep.get('source',{});en=nodes.get('event:'+str(er.get('event_id')))
            if not en:return empty
            ee=en['properties']
            if (unit['trajectory_id']!=endpoint['trajectory_id'] or event['trajectory_id']!=endpoint['trajectory_id']
                    or e.get('context_id')!=ee.get('context_id') or p.get('actor')!=ep.get('actor')
                    or e.get('actor')!=ep.get('actor')):return empty
        if ((prior['event_index'],prior['properties']['source']['end'])>(unit['event_index'],a)
                or (unit['event_index'],b)>(current['event_index'],current['properties']['source']['start'])):return empty
        return dict(status='selected',label="Agent's stated reason",node_id=choice,event_id=ref['event_id'],
                    text=ref['text'],source=deepcopy(ref),request=method.get('request'),attribution='agent_expression')
    return resolve


def _response_context(comparison,nodes):
    result={}
    for side in ('previous','current'):
        saved=(comparison or {}).get('feedback',{}).get(side)
        if not saved:
            result[side]=dict(status='unavailable',records=[],reasons=['No bound feedback comparison available'])
            continue
        records=[]
        for nid in saved['node_ids']:
            node=nodes[nid];p=node['properties']
            records.append(dict(node_id=nid,event_id=p['id'],text=p.get('text',''),source_pointer=p.get('source_pointer')))
        result[side]=dict(status='available' if not saved['reasons'] else 'unavailable',records=records,
                          reasons=saved['reasons'],edge_ids=saved['edge_ids'])
    result['scope']='Earlier feedback precedes the current dispatch. Current feedback is a later source observation, excluded from the procedure decision; it is not a task-success verdict.'
    return result


def project(graph):
    base = work_episodes.project(graph)
    comparisons={(r['previous_node_id'],r['current_node_id']):r for r in repeated_work.project(graph,_episodes=base)['rows']}
    nodes={n['id']:n for n in graph['nodes']};reason_for=_reason_resolver(graph);feedback_for=approach_feedback.resolver(graph)
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
            if ((reviewed or original_schema in {'work-method-comparison/3','work-method-comparison/4'} and m.get('status') == 'selected')
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
               'stated_reason':reason_for(raw[0] if method and len(raw)==1 else None,episode),
               'response_context':_response_context(comparisons.get((episode['previous_unit_id'],episode['current_unit_id'])),nodes),
               'episode': deepcopy(episode)}
        row['error_followup']=feedback_for(episode,row['response_context'])
        row['id'] = 'adaptation-case-' + digest([VERSION, graph['id'], row])
        records.append(row)
    known = [r for r in records if r['procedure'] != 'unresolved']
    changed = [r for r in known if r['procedure'] in {'reconfigured_procedure', 'alternative_procedure'}]
    counts = Counter((r['procedure'], r['correction_location']) for r in records)
    followup_counts=Counter(r['error_followup']['category'] for r in records)
    cells = [{'procedure': p, 'correction_location': loc, 'count': counts[p, loc],
              'case_ids': [r['id'] for r in records if (r['procedure'], r['correction_location']) == (p, loc)]}
             for p in PROCEDURES for loc in LOCATIONS]
    observed = bool(records or base['counts']['identity_reviewed'])
    value = {'schema': VERSION, 'dependency': DEPENDENCY, 'run_id': graph['run_id'],
             'graph_id': graph['id'], 'source_hash': graph['source_hash'], 'observer': graph['observer'],
             'metadata': graph.get('metadata', {}), 'observed': observed, 'records': records, 'cells': cells,
             'coverage': {**base['counts'], 'recurrences': len(records), 'procedure_compared': len(known),
                          'procedure_unknown': len(records) - len(known),
                          'error_followup':{key:followup_counts[key] for key in approach_feedback.LABELS}},
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
