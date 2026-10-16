"""Explicit native reward-column identity; no guessing from callback names."""
from .schema import InputError
from .training_lineage import text


def validate_components(value, count, first_definition):
    if not isinstance(value, list) or len(value) != count or not 2 <= count <= 32:
        raise InputError('Supply two to 32 ordered reward_components matching native reward_funcs')
    result = []
    for component in value:
        if not isinstance(component, dict) or set(component) != {'component', 'definition'}:
            raise InputError('Each native reward column needs a component name and versioned definition')
        for key, item in component.items():
            text(item, key)
        result.append(dict(component))
    if len({r['component'] for r in result}) != count:
        raise InputError('Native reward component names must be unique')
    if result[0]['definition'] != first_definition:
        raise InputError('First native reward definition must match the wrapped capture')
    return result
