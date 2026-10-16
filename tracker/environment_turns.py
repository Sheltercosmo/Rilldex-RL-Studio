"""Versioned response/action bindings for portable environment episodes.

The binding is supplied by capture code. It is not a semantic claim that a
particular sentence caused an action, nor proof that the action succeeded.
"""
from .schema import InputError, event

VERSION = 'environment-episode/2'


def identifier(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise InputError(label + ' must be a nonempty string of at most 500 characters')
    return value


def validate(doc):
    identifier(doc.get('episode_id'), 'episode_id')
    seen, responses = set(), set()
    for step in doc.get('steps', []):
        tid = identifier(step.get('turn_id'), 'turn_id')
        if tid in seen: raise InputError('Duplicate turn_id within an episode')
        seen.add(tid)
        if step.get('turn_identity_basis') not in {'producer_id', 'capture_sequence'}:
            raise InputError('Declare turn_identity_basis as producer_id or capture_sequence')
        if 'model_response' in step and not isinstance(step['model_response'], str):
            raise InputError('model_response must be the recorded text; omit it when unavailable')
        if 'response_id' in step:
            rid = identifier(step['response_id'], 'response_id')
            if 'model_response' not in step: raise InputError('response_id needs a recorded model_response')
            if rid in responses: raise InputError('One response reused for several actions requires a batch-aware source contract')
            responses.add(rid)


def append_response(events, step, pointer, *, episode_id, index):
    common = {'episode_id':episode_id, 'turn_id':step['turn_id'],
              'turn_identity_basis':step['turn_identity_basis'], 'step_id':index}
    if 'response_id' in step: common['response_id'] = step['response_id']
    text = step.get('model_response')
    parent = None
    if isinstance(text, str) and text.strip():
        parent = event(events, kind='message', actor='agent', text=text,
                       pointer=pointer+'/model_response', source_role='recorded_model_response', **common)
    action_fields = {**common, 'model_response_recorded':'model_response' in step}
    if 'model_response' in step: action_fields['model_response_pointer'] = pointer+'/model_response'
    if parent:
        action_fields.update(parent_id=parent['id'], parent_link_basis='producer_recorded_response_action_binding')
    return action_fields, common
