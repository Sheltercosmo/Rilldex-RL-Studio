"""Experimental operation/claim-conditioned local mention inspection.

Does not replace the current occurrence worker. Frozen trials can use this
client after inspecting its explicit dependencies; missing heads block the
dependent field, not the whole run, and never count as negative mentions.
"""
from copy import deepcopy

from .entity_occurrences import OccurrenceClient, packet
from .local_role_context import context_for
from .schema import InputError

HARNESS = 'anchored-local-occurrences/0.1'


def prepare(run, nodes, unit_id):
    result = packet(run, nodes, unit_id)
    node = next(n for n in nodes if n['id'] == unit_id)
    contexts = {key: context_for(run, node, key) for key in result['state']['fields']}
    ready = {k: c for k, c in contexts.items() if c['status'] == 'ready_for_role_inspection'}
    skipped = {k: c for k, c in contexts.items() if k not in ready}
    state = result['state']
    state['harness'] = HARNESS
    state['fields'] = {k: f for k, f in state['fields'].items() if k in ready}
    for key, field in state['fields'].items():
        field['local_role_context'] = deepcopy(ready[key])
    used = {cid for f in state['fields'].values() for cid in f['candidate_ids']}
    state['candidates'] = [c for c in state['candidates'] if c['id'] in used]
    state['question_bindings'] = {k: b for k, b in state['question_bindings'].items() if b['field'] in ready}
    result['questions'] = {k: q for k, q in result['questions'].items() if k in state['question_bindings']}
    for key, question in result['questions'].items():
        field = state['question_bindings'][key]['field']
        question['instructions'] += (
            f' Bind this role specifically to the selected governing expression in fields[{field}].local_role_context. '
            'Read that expression within the complete local source. The earlier extraction is a proposal, not proof. '
            'Contrast fields help distinguish purpose, content, criterion and actor from the requested role; '
            'their spans are not automatic exclusions and may themselves be wrong. '
            'An object in a premise or purpose clause is not automatically a target of the main operation. '
            'If the proposed governing expression cannot support this role judgment, select unresolved. '
            'Preserve intention, request, assertion and dispatch separately; do not infer execution.')
    # Skipped dependencies remain outside model evidence and are exposed to the
    # caller for repair. They are not model-generated absence decisions.
    return result, skipped


class AnchoredOccurrenceClient(OccurrenceClient):
    harness = HARNESS

    def request(self, run, unit_id):
        if self.nodes is None:
            raise InputError('Anchored occurrences require current local fields')
        result, skipped = prepare(run, self.nodes, unit_id)
        if not result['questions']:
            raise InputError('Extract the governing local expression before inspecting dependent mentions')
        return {**result, 'model': self.model}
