"""Local extraction dependencies, before reference or action relationships.

These are proposed inspection inputs, not semantic links or verified roles.
They depend on selected source evidence, never on confidence or future units.
"""
from copy import deepcopy

from .schema import digest

VERSION = 'local-role-context/1'
# Mention field -> governing expression, contrast fields. The latter are
# evidence to distinguish roles, not automatic exclusions by string overlap.
DEPENDENCIES = {
    'inspect__information_target': ('inspect__query', ('inspect__source',)),
    'inspect__source': ('inspect__query', ('inspect__information_target',)),
    'hypothesize__explained_phenomenon': ('hypothesize__candidate_explanation', ()),
    'plan__intended_target': ('plan__intended_operation', ('plan__expressed_subgoal',)),
    'construct__target_artifact_or_state': ('construct__operation', ('construct__proposed_change',)),
    'verify__check_target': ('verify__check_operation', ('verify__criterion',)),
    'assess__feedback_referent': ('assess__assessment_claim', ()),
    'revise__prior_item_reference': ('revise__replacement', ('revise__stated_reason',)),
    'coordinate__addressee_mention': ('coordinate__requested_operation', ('coordinate__request_target',)),
    'coordinate__request_target': ('coordinate__requested_operation', ('coordinate__addressee_mention',)),
    'report__artifact_reference': ('report__reported_content', ('report__completion_claim',)),
}


def exact_local_candidate(run, node, candidate):
    if not candidate or candidate.get('event_id') != node['event_id']:
        return False
    if candidate.get('source_pointer') != node['source_pointer']:
        return False
    if candidate.get('kind') == 'source_span':
        a, b = candidate.get('start'), candidate.get('end')
        return (type(a) is int and type(b) is int and node['start'] <= a < b <= node['end']
                and node['text'][a-node['start']:b-node['start']] == candidate.get('text'))
    if candidate.get('kind') == 'structured_argument':
        try:
            value = next(e for e in run['events'] if e['id'] == node['event_id'])
            parts = candidate['normalized_event_pointer'].strip('/').split('/')
            if not parts or parts[0] != 'arguments':
                return False
            for part in parts:
                part = part.replace('~1', '/').replace('~0', '~')
                value = value[int(part)] if isinstance(value, list) else value[part]
            return value == candidate['value']
        except (KeyError, TypeError, ValueError, IndexError, StopIteration):
            return False
    return False


def context_for(run, node, key):
    head_key, contrasts = DEPENDENCIES[key]
    extraction = node['entity_extraction']
    fields = {r['activity']+'__'+f['role']: f for r in extraction['routes'] for f in r['fields']}
    field = fields[key]
    saved = extraction.get('observation') or {}
    provenance = saved.get('_provenance', {})

    def evidence(field_key):
        f = fields.get(field_key, {})
        candidate = f.get('selected_candidate')
        selected = f.get('status') in {'selected_span', 'selected_argument'}
        integrity = exact_local_candidate(run, node, candidate) if candidate else None
        return {'field': field_key, 'presence': f.get('presence_decision'),
                'status': f.get('status', 'field_not_routed'),
                'raw_choice': f.get('raw_choice'), 'selection': deepcopy(candidate),
                'review_note': f.get('review_note'), 'source_exact': integrity,
                'usable': bool(selected and integrity and not f.get('review_note'))}

    head = evidence(head_key)
    presence = field.get('presence_decision')
    if extraction['extraction_status'] != 'observed':
        status, next_step = 'local_extraction_needed', 'Complete current category field extraction.'
    elif presence == 'no_local_expression':
        status, next_step = 'no_local_role', 'No local role selected; retain this absence decision without inferring global absence.'
    elif presence == 'route_not_applicable':
        status, next_step = 'activity_review_needed', 'Review the base activity for this expression.'
    elif presence != 'local_expression':
        status, next_step = 'role_presence_review_needed', 'Resolve local role presence before proposing occurrences.'
    elif not head['usable']:
        status, next_step = 'governing_expression_needed', 'Extract or review '+head_key+' before binding this mention role.'
    else:
        status, next_step = 'ready_for_role_inspection', 'Inspect candidate mentions against this governing expression; then select boundaries.'
    return {'version': VERSION, 'field': key, 'status': status, 'next_step': next_step,
            'governing_expression': head, 'contrasts': [evidence(k) for k in contrasts],
            'upstream': {k: provenance.get(k) for k in ('harness', 'model', 'request_hash', 'packet_hash', 'selection_policy')},
            'upstream_result_hash': digest(saved) if saved else None,
            'boundary': 'This is an input dependency, not a verified role binding. Preserve the complete local expression and its modality. A governing span may contain multiple operations; it does not separate them or resolve identity.'}


def project(run, node):
    """Enrich the view without mutating saved observations or inferred choices."""
    rows = []
    for route in node['entity_extraction']['routes']:
        for field in route['fields']:
            key = route['activity']+'__'+field['role']
            if key in DEPENDENCIES:
                rows.append(context_for(run, node, key))
    node['local_role_context'] = {'version': VERSION, 'fields': rows,
        'boundary': 'Complete local roles before constructing cross-unit relationships. Readiness is not semantic accuracy.'}
    return node
