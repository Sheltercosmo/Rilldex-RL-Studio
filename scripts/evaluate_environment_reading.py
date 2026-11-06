"""Compare Jev readings with definitions, renamed tools, and removed definitions.

Default: export exact requests without calling a model. --live evaluates and
resumes exact cached requests. References are authored controls, never supplied
to the model, and are not a held-out real-world accuracy benchmark.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker.jev import JevClient, DEFAULT_MODEL, validate_answers
from tracker.portable import Episode
from tracker.schema import InputError, digest, dumps


def cases():
    # Domain operations deliberately share the same opaque API name. Meaning
    # must come from the contract, task, arguments and recorded expression.
    rows = [
        ('opaque-read', 'Handle booking B-7.', 'Invoke the available operation.',
         'Retrieve the current booking details without changing the booking.', {'ref': 'B-7'}, 'explore'),
        ('opaque-update', 'Handle booking B-7.', 'Invoke the available operation.',
         'Apply the already selected booking update to the reservation.', {'ref': 'B-7'}, 'apply'),
        ('opaque-check', 'Handle booking B-7.', 'Invoke the available operation.',
         'Check whether the booking satisfies its recorded acceptance criteria and return the check result.', {'ref': 'B-7'}, 'verify'),
        ('inventory', 'Read stock for A-7 before choosing a quantity.', 'I will retrieve the stock record.',
         'Read available inventory for a SKU; no state is changed.', {'sku': 'A-7'}, 'explore'),
        ('reservation', 'Reserve two seats on the selected service S-9.', 'Reserve the two selected seats now.',
         'Create a temporary seat reservation for the given service and count.', {'service': 'S-9', 'count': 2}, 'apply'),
        ('browser', 'Check whether the submitted form preserved the requested email.', 'Check that the displayed email equals a@example.org.',
         'Compare a DOM field value with an expected value and return whether they match; does not modify the field.',
         {'field': 'email', 'expected': 'a@example.org'}, 'verify'),
        ('delegation', 'Ask the reviewer to inspect the contract before approval.', 'Send the contract to the reviewer for inspection.',
         'Send a work request to another actor; does not execute that work.', {'recipient': 'reviewer', 'task': 'Inspect contract'}, 'coordinate'),
        ('delivery', 'Send the completed report to the researcher.', 'Deliver the existing report now.',
         'Deliver an existing report to its recipient; does not generate or evaluate it.', {'report': 'R-7'}, 'report'),
    ]
    result = []
    for domain, goal, expression, description, arguments, expected in rows:
        document = {'messages': [{'role': 'user', 'content': goal},
                    {'role': 'assistant', 'content': expression, 'tool_calls': [
                        {'id': 'call-1', 'type': 'function', 'function': {'name': 'dispatch', 'arguments': dumps(arguments)}}]}],
                    'tools': [{'type': 'function', 'function': {'name': 'dispatch', 'description': description,
                               'parameters': {'type': 'object'}}}]}
        result.append({'id': domain, 'document': document, 'reference': expected})
    for domain, action, schema, obs, obs_schema in [
        ('navigation', 5, {'type': 'integer', 'oneOf': [{'const': 5, 'title': 'toggle/activate the facing object'}]},
         {'door_state': 2}, {'properties': {'door_state': {'oneOf': [{'const': 2, 'title': 'locked'}]}}}),
        ('continuous-control', [0.2, -0.1], {'type': 'array', 'prefixItems': [
            {'title': 'shoulder torque', 'description': 'Nm'}, {'title': 'elbow torque', 'description': 'Nm'}]},
         [0.1, 0.3], {'type': 'array', 'prefixItems': [{'title': 'shoulder angle'}, {'title': 'elbow angle'}]}),
    ]:
        doc = (Episode(episode_id=domain, goal='Apply the selected control input.', action_schema=schema,
                       observation_schema=obs_schema).reset(obs)
               .step(action, obs, model_response='Apply the selected control input now.').snapshot())
        result.append({'id': domain, 'document': doc, 'reference': 'apply'})
    # Context-poor controls: no tool meaning, goal or parent expression.
    result.append({'id': 'undocumented-operation', 'document': {'messages': [{'role': 'assistant', 'content': '',
        'tool_calls': [{'id': 'x', 'type': 'function', 'function': {'name': 'q7', 'arguments': '{}'}}]}]},
        'reference': 'unresolved'})
    return result


def without_definitions(value):
    if isinstance(value, dict):
        return {k: without_definitions(v) for k,v in value.items()
                if k not in {'tool_contract', 'observation_contract', 'environment_encoding', 'tool_catalog'}}
    if isinstance(value, list):
        return [without_definitions(v) for v in value]
    return value


def requests(model):
    client = JevClient(model=model)
    for case in cases():
        for variant in ('described', 'renamed', 'without_definitions'):
            doc = deepcopy(case['document'])
            if variant == 'renamed' and 'messages' in doc:
                for msg in doc['messages']:
                    for call in msg.get('tool_calls', []):call['function']['name'] = 'api_873'
                for tool in doc.get('tools', []):tool['function']['name'] = 'api_873'
            elif variant == 'renamed':
                continue  # The environment action encoding has no API-name alias.
            run = normalize(doc)[0]
            action = next(e for e in run['events'] if e['kind'] == 'action')
            request = client.request(run, action['id'])
            request['questions'] = {'mode': request['questions']['mode']}
            if variant == 'without_definitions':request = without_definitions(request)
            # These three otherwise identical actions become indistinguishable
            # after definitions are removed. Score the answer that the visible
            # evidence supports, not the hidden operation definition.
            expected = 'unresolved' if variant == 'without_definitions' and case['id'].startswith('opaque-') else case['reference']
            yield {'case_id': case['id'], 'variant': variant, 'source_hash': digest(run),
                   'reference': case['reference'], 'expected_visible_answer': expected,
                   'request_hash': digest(request), 'request': request}


def evaluate(output, *, live=False, model=DEFAULT_MODEL):
    root = Path(output); root.mkdir(parents=True, exist_ok=True)
    rows = list(requests(model))
    (root / 'requests.json').write_text(dumps({'reference_kind': 'authored development controls', 'cases': rows}), encoding='utf-8')
    if live and not os.environ.get('JEV_API_KEY'):
        raise InputError('Requests saved. Set JEV_API_KEY to run the live model evaluation.')
    client = JevClient(model=model)
    results = []
    for row in rows:
        record = {k:v for k,v in row.items() if k != 'request'}
        if live:
            path = root / (row['request_hash'] + '.json')
            if path.exists():
                saved = json.loads(path.read_text(encoding='utf-8'))
                if saved['request'] != row['request']:raise InputError('Cached evaluation request differs')
                response = saved['response']
            else:
                response = client.transport(row['request'])
                validate_answers(response, row['request'])
                path.write_text(dumps({'request': row['request'], 'response': response}), encoding='utf-8')
            if response.get('model') != model:raise InputError('Evaluation response model differs from requested version')
            answer = validate_answers(response, row['request'])['mode']
            prediction = answer['value'] if answer['status']=='decided' else answer['status']
            record.update(prediction=prediction, correct=prediction == row['expected_visible_answer'])
        results.append(record)
    groups = {}
    for variant in sorted({r['variant'] for r in results}):
        group = [r for r in results if r['variant'] == variant]
        correct = sum(r['correct'] for r in group) if live else None
        groups[variant] = {'cases': len(group), 'correct': correct, 'accuracy': correct / len(group) if live else None}
    report = {'status': 'evaluated' if live else 'requests_only', 'model': model, 'groups': groups, 'results': results,
              'interpretation': 'Authored development controls. Renamed tools test name dependence; removed definitions test information dependence. Not an estimate of real-world prevalence or held-out accuracy.'}
    (root / 'report.json').write_text(dumps(report), encoding='utf-8')
    return {k:v for k,v in report.items() if k != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('outputs/environment-reading'))
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:print(dumps(evaluate(args.output, live=args.live, model=args.model)))
    except InputError as exc:parser.exit(2, str(exc) + '\n')
