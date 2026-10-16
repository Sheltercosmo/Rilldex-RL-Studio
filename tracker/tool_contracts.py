"""Offline parameter-schema observations, separate from operation/task outcomes.

Only native agent calls with source-bound declarations are eligible. No text
classification, schema repair, remote reference retrieval or provider calls.
"""
from collections import Counter
from copy import deepcopy
from importlib.metadata import version as package_version
import json
import math

from .schema import InputError, digest, dumps

VERSION = 'tool-parameter-contracts/1'
DEFINITIONS = {
    'tool_contract_violation_count': ('Parameter-schema violations', 'Native agent calls violating their recorded machine-readable parameter schema. Tool-description rules, tool outcomes and task correctness are outside this check. Missing or unsupported schemas remain unknown.'),
    'tool_contract_violation_fraction': ('Parameter-schema violation fraction', 'Violating calls / calls with a decidable recorded-parameter-schema check. Unavailable checks are excluded and counted separately; not whole-agent error rate.'),
    'tool_contract_check_coverage': ('Parameter-schema check coverage', 'Decidable recorded-parameter-schema checks / eligible native agent calls, excluding copied context and other actors. No native calls means unavailable, not perfect coverage.'),
}
MAX_SCHEMA_BYTES = 65536
MAX_ARGUMENT_BYTES = 262144
MAX_NODES = 4096
MAX_DEPTH = 32
ANNOTATIONS = {'title', 'description', 'default', 'examples', '$comment', 'readOnly', 'writeOnly', 'deprecated'}
MAPS = {'properties', '$defs', 'definitions', 'dependentSchemas'}
LISTS = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
SINGLE = {'items', 'additionalProperties', 'contains', 'not', 'if', 'then', 'else', 'propertyNames', 'unevaluatedProperties', 'unevaluatedItems', 'additionalItems'}


class Unsupported(ValueError):
    pass


def protocol():
    try:
        from jsonschema import Draft7Validator, Draft202012Validator  # noqa: F401
        from referencing import Registry  # noqa: F401
    except ImportError:
        raise InputError('Parameter checks require the optional dependency: pip install ".[contracts]"') from None
    p = {'schema': VERSION, 'engine': 'jsonschema', 'engine_version': package_version('jsonschema'),
         'referencing_version': package_version('referencing'), 'unversioned_dialect': '2020-12',
         'bfcl_projection': 'dict-to-object,float-to-number; integer remains Python int',
         'max_schema_bytes': MAX_SCHEMA_BYTES, 'max_argument_bytes': MAX_ARGUMENT_BYTES,
         'max_nodes': MAX_NODES, 'max_depth': MAX_DEPTH,
         'limits': 'Machine-readable constraints only. No natural-language constraints, format assertions, regexes, remote references or recursive schemas. No defaults inserted or arguments coerced.'}
    return {**p, 'id': 'tool-contracts-' + digest(p)[:20]}


def pointer(parts):
    return ''.join('/' + str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def bounded(value, limit):
    nodes = 0
    def visit(v, depth):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise Unsupported('Recorded structure exceeds the inspection bound')
        if isinstance(v, dict):
            if any(not isinstance(k, str) for k in v):
                raise Unsupported('Non-string JSON object key')
            for child in v.values(): visit(child, depth + 1)
        elif isinstance(v, list):
            for child in v: visit(child, depth + 1)
        elif isinstance(v, float) and not math.isfinite(v):
            raise Unsupported('Non-finite recorded JSON number')
        elif not isinstance(v, (str, int, float, bool, type(None))):
            raise Unsupported('Unsupported recorded JSON value')
    visit(value, 0)
    if len(dumps(value).encode('utf-8')) > limit:
        raise Unsupported('Recorded payload exceeds the inspection byte bound')


def prepare_schema(original, bfcl=False):
    from jsonschema import Draft7Validator, Draft202012Validator, validators
    bounded(original, MAX_SCHEMA_BYTES)
    schema = deepcopy(original)
    dialect = schema.get('$schema') if isinstance(schema, dict) else None
    known = {None: Draft202012Validator,
             'https://json-schema.org/draft/2020-12/schema': Draft202012Validator,
             'http://json-schema.org/draft-07/schema#': Draft7Validator,
             'https://json-schema.org/draft-07/schema': Draft7Validator}
    if dialect not in known: raise Unsupported('Unrecognized declared JSON Schema dialect')
    validator = known[dialect]
    if bfcl:
        validator = validators.extend(validator, type_checker=validator.TYPE_CHECKER.redefine('integer', lambda _, v: type(v) is int))
    visited = 0
    def visit(node, path=(), ancestors=()):
        nonlocal visited
        visited += 1
        if visited > MAX_NODES or len(ancestors) > MAX_DEPTH:
            raise Unsupported('Schema expansion exceeds the inspection bound')
        if type(node) is bool: return
        if not isinstance(node, dict): raise Unsupported('Malformed parameter schema')
        if id(node) in ancestors: raise Unsupported('Recursive schema is not inspected')
        ancestors = (*ancestors, id(node))
        unknown = set(node) - set(validator.VALIDATORS) - ANNOTATIONS - {'$schema', '$defs', 'definitions'}
        if unknown: raise Unsupported('Unsupported schema keyword at ' + pointer(path) + ': ' + ', '.join(sorted(unknown)))
        if any(k in node for k in ('pattern', 'patternProperties', 'format', '$dynamicRef', '$recursiveRef', 'dependencies')):
            raise Unsupported('Regex, format, legacy dependencies or recursive schema constraints are not inspected')
        if '$schema' in node and path: raise Unsupported('Nested schema dialect changes are not inspected')
        if bfcl and isinstance(node.get('type'), str):
            node['type'] = {'dict': 'object', 'float': 'number'}.get(node['type'], node['type'])
        for key, child in node.items():
            if key in MAPS:
                if not isinstance(child, dict): raise Unsupported('Malformed schema map')
                for name, item in child.items(): visit(item, (*path, key, name), ancestors)
            elif key in LISTS or (key == 'items' and isinstance(child, list)):
                if not isinstance(child, list): raise Unsupported('Malformed schema array')
                for i, item in enumerate(child): visit(item, (*path, key, i), ancestors)
            elif key in SINGLE: visit(child, (*path, key), ancestors)
            elif key == '$ref':
                if not isinstance(child, str) or not (child == '#' or child.startswith('#/')) or '%' in child:
                    raise Unsupported('Only local JSON Pointer schema references are inspected')
                target = schema
                try:
                    for part in child[2:].split('/') if child != '#' else []:
                        token = part.replace('~1', '/').replace('~0', '~')
                        target = target[int(token)] if isinstance(target, list) else target[token]
                except (KeyError, ValueError, TypeError, IndexError):
                    raise Unsupported('Unresolved local schema reference') from None
                visit(target, (*path, '$ref'), ancestors)
    visit(schema)
    try: validator.check_schema(schema)
    except Exception as exc:
        from jsonschema.exceptions import SchemaError
        if not isinstance(exc, SchemaError): raise
        raise Unsupported('Recorded declaration is not a valid parameter schema') from None
    return validator, schema, ('bfcl-json-parameters/1' if bfcl else 'json-schema/' + ('draft-07' if validator is Draft7Validator else '2020-12'))


def arguments(raw):
    if isinstance(raw, str):
        if len(raw.encode('utf-8')) > MAX_ARGUMENT_BYTES: raise Unsupported('Recorded arguments exceed the inspection byte bound')
        def unique(pairs):
            value = {}
            for k, v in pairs:
                if k in value: raise Unsupported('Duplicate argument keys have ambiguous parser semantics')
                value[k] = v
            return value
        def reject_constant(_): raise ValueError('nonfinite')
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    else: value = raw
    bounded(value, MAX_ARGUMENT_BYTES)
    return value


def issue_description(error):
    if error.validator == 'required' and isinstance(error.instance, dict):
        return 'Missing required parameters: ' + ', '.join(k for k in error.validator_value if k not in error.instance)
    if error.validator == 'type':
        kind = ('null' if error.instance is None else 'boolean' if isinstance(error.instance, bool) else
                'object' if isinstance(error.instance, dict) else 'array' if isinstance(error.instance, list) else
                'string' if isinstance(error.instance, str) else 'number')
        return 'Expected ' + str(error.validator_value) + '; received ' + kind
    return 'Recorded arguments violate ' + str(error.validator)


def check(action):
    from referencing import Registry
    row = {'event_id': action['id'], 'source_pointer': action['source_pointer'],
           'source_message_index': action.get('source_message_index'), 'tool': action.get('tool'),
           'status': 'unavailable', 'issues': [], 'reason': None}
    contract = action.get('tool_contract')
    if not isinstance(contract, dict) or not isinstance(contract.get('source_pointer'), str):
        return {**row, 'reason': 'No source-bound tool declaration'}
    definition = contract.get('definition', {})
    bfcl = contract.get('source_format') == 'bfcl-function/1'
    function = definition if bfcl else definition.get('function', {})
    suffix = '/parameters' if bfcl else '/function/parameters'
    row.update(contract_pointer=contract['source_pointer'] + suffix, contract_hash=digest(contract))
    if function.get('name') != action.get('tool') or 'parameters' not in function:
        return {**row, 'reason': 'Missing or mismatched parameter declaration'}
    try:
        validator, schema, projection = prepare_schema(function['parameters'], bfcl)
        row['projection'] = projection
        row['projected_schema_hash'] = digest(schema)
        if 'raw_arguments' not in action: raise Unsupported('Exact recorded arguments are unavailable')
        try: value = arguments(action['raw_arguments'])
        except (json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, Unsupported): raise
            return {**row, 'status': 'invalid', 'issues': [{'keyword': 'json', 'argument_pointer': '', 'schema_pointer': '', 'description': 'Recorded arguments are not strict JSON'}]}
        errors = []
        for err in validator(schema, registry=Registry()).iter_errors(value):
            errors.append({'keyword': str(err.validator), 'argument_pointer': pointer(err.absolute_path),
                           'schema_pointer': pointer(err.absolute_schema_path),
                           'description': issue_description(err)})
            if len(errors) == 16: break
        return {**row, 'status': 'invalid' if errors else 'conformant', 'issues': errors,
                'issue_limit': 16, 'all_issues_enumerated': len(errors) < 16}
    except (Unsupported, RecursionError) as exc:
        return {**row, 'reason': str(exc) if isinstance(exc, Unsupported) else 'Recursive or excessively deep source structure'}


def inspect(run):
    p = protocol()
    actions = [e for e in run['events'] if e['actor'] == 'agent' and e['kind'] == 'action' and not e.get('copied_context')]
    # A normalized action can be a shell dispatch with no native function envelope.
    native = [e for e in actions if e.get('extraction') == 'recorded-function-call']
    rows = [check(e) for e in native]
    count = Counter(r['status'] for r in rows)
    invalid = [r['event_id'] for r in rows if r['status'] == 'invalid']
    decided = [r['event_id'] for r in rows if r['status'] != 'unavailable']
    metrics = {
        'tool_contract_violation_count': {'value': len(invalid) if decided else None, 'evidence': invalid, 'reason': None if decided else 'No decidable parameter-schema checks'},
        'tool_contract_violation_fraction': {'numerator': len(invalid), 'denominator': len(decided), 'evidence': invalid},
        'tool_contract_check_coverage': {'numerator': len(decided), 'denominator': len(native), 'evidence': decided},
    }
    return {'schema': VERSION, 'run_id': run['id'], 'source_hash': digest(run), 'protocol': p, 'calls': rows,
            'counts': {'native_calls': len(native), 'other_agent_actions': len(actions) - len(native),
                       'conformant': count['conformant'], 'invalid': count['invalid'], 'unavailable': count['unavailable']},
            'metrics': metrics}


def register(store, run):
    from .rollout_metrics import source_record, measurement, save
    result = inspect(run)
    record = source_record(run)
    record.update(observer=result['protocol']['id'], observer_label='Recorded parameter schemas',
                  observation_kind='tool_contracts', annotation_hash=digest(result), tool_contract_inspection=result)
    for name, params in result['metrics'].items(): record['metrics'][name] = measurement(**params)
    with store.connect() as connection: mid = save(connection, record)
    return {'measurement_id': mid, 'observer': record['observer'], 'inspection': result}


def read_saved(store, run_id, observer):
    if not isinstance(observer, str) or not observer:
        raise InputError('Select the parameter-schema observer to inspect')
    run = store.get(run_id, raw=True)['run']
    source_hash = digest(run)
    with store.connect() as connection:
        records = connection.execute('SELECT id,document FROM rollout_measurements WHERE run_id=? AND observer=? ORDER BY created_at DESC,id DESC', (run_id, observer)).fetchall()
    for saved in records:
        record = json.loads(saved['document']); result = record.get('tool_contract_inspection')
        if (record.get('source_hash') == source_hash and isinstance(result, dict)
                and result.get('schema') == VERSION and result.get('source_hash') == source_hash
                and result.get('protocol', {}).get('id') == observer):
            return {'measurement_id': saved['id'], **result}
    raise InputError('No parameter-schema inspection matches this source and observer')
