"""Source-declared meanings for arbitrary JSON actions and observations.

Schemas describe the encoding, not what an agent intended or accomplished.
Keep them separate from agent-visible messages and never fetch schema refs.
"""
from copy import deepcopy

from .schema import InputError, dumps

VERSION = 'environment-contracts/1'
READING_RULE = ('Interpret unfamiliar or misleading tool names and encoded values using their recorded definitions. '
                'A schema describes possible operations and value meanings, not an executed effect, an agent intention, '
                'or task success. Compare recorded observations without assuming the full environment state is visible.')


def capture_schema(value, name):
    if not isinstance(value, dict):
        raise InputError(name + ' must be a JSON Schema object')
    try:
        dumps(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InputError(name + ' must contain finite JSON data') from exc
    return deepcopy(value)


def contracts(document):
    result = {}
    for field, key in [('action_schema', 'tool_contract'), ('observation_schema', 'observation_contract')]:
        if field in document:
            result[key] = {
                'source_pointer': '/' + field,
                'definition': capture_schema(document[field], field),
                'source_format': VERSION,
                'basis': 'producer_declared_encoding',
                'scope': 'Describes recorded values. Not agent-visible instructions, observed effects, or evidence of success. External schema references are not resolved.',
            }
    return result


def excerpt_contracts(item, *, limit, truncated):
    """Use the same source contracts in macro and activity interpretation."""
    result = {}
    for field in ('tool_contract', 'observation_contract'):
        contract = item.get(field)
        if not contract:
            continue
        text = dumps(contract['definition'])
        if len(text) > limit:
            truncated.append(field + ':' + contract['source_pointer'])
        result[field] = {k: deepcopy(v) for k, v in contract.items() if k != 'definition'} | {
            'definition_text': text[:limit], 'source_characters': len(text),
        }
    return result


def encoding_context(run):
    """Make capture-time definitions available even before the first dispatch.

    Read only the declared schemas, never episode outcomes or private info.
    This is interpreter reference material, not an additional agent message.
    """
    if run.get('adapter') != 'environment-episode':
        return {}
    declared = contracts(run.get('raw', {}))
    if not declared:
        return {}
    clipped = []
    values = excerpt_contracts(declared, limit=8000, truncated=clipped)
    return {'environment_encoding': {'schema': VERSION, 'definitions': values,
            'truncated_definition_ids': clipped, 'interpretation_rule': READING_RULE}}


def reading_context(run, current):
    """Reference definitions supplied with this history, including before calls.

    A session catalog is not reconstructed from later actions. Tools from other
    histories must never supply meanings for a reused name in this context.
    """
    result = encoding_context(run)
    if run.get('adapter') not in {'chat-messages','responses-items'}:
        return result
    source, base = run.get('raw', {}), ''
    if run.get('adapter_version') == 'chat-messages/2':
        from .capabilities import recorded_scope
        match = next(((i,s) for i,s in enumerate(source.get('sessions', []))
                      if recorded_scope(s) == recorded_scope(current)), None)
        if match is None:return result
        index, source = match
        base = f'/sessions/{index}'
    tools = source.get('tools', [])
    if not tools:return result
    definitions, clipped = [], []
    budget = 24000
    for i,tool in enumerate(tools):
        if budget <= 0:break
        text = dumps(tool); limit = min(8000, budget)
        pointer = f'{base}/tools/{i}'
        if len(text) > limit:clipped.append(pointer)
        definitions.append({'source_pointer':pointer, 'definition_text':text[:limit],
                            'source_characters':len(text)})
        budget -= min(len(text), limit)
    result['tool_catalog'] = {'schema':'recorded-tools/1', 'definitions':definitions,
        'omitted_definition_count':len(tools)-len(definitions), 'truncated_definition_ids':clipped,
        'scope':'Definitions supplied for this recorded conversation, not inferred from later calls. '
                'They describe available operations, not proof of use, effects or success.'}
    return result
