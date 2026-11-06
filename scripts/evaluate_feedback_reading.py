"""Long-result development controls and selected public follow-up actions.

Retain requests and raw replies. References never enter model requests; these
controls diagnose reading failures, not deployment-wide semantic accuracy.
"""
import argparse
from collections import defaultdict
import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_harness_generalization import representations
from scripts.evaluate_reading_context import conversation, score
from tracker.adapters import normalize
from tracker.jev import JevClient, JEV_HARNESS
from tracker.schema import InputError, digest, dumps

RESPONSE_QUESTION = {
    'type': 'choice',
    'instructions': 'Compare current_action with the most recent prior action and its visible feedback in this same agent trajectory. Classify the observable response, not differences in tool names or arguments alone. An unchanged operation is repeat, without implying failure or unchanged environment state. A new information-gathering step is gather_information. Performing the next scheduled step or checking another criterion under the existing approach is continue. Use parameter_change or method_change for a supported adjustment to address the feedback: distinguish settings within the same procedure from replacing its mechanism using the recorded operation definitions and expressions. Changing the inspected file, processed record or test scope during ordinary progression is not by itself a revision. Do not infer an unexpressed causal reason or successful recovery.',
    'criteria': {
        'repeat': 'Repeat the same operation with unchanged arguments; polling or reconfirmation can also repeat.',
        'parameter_change': 'Adjust settings or inputs within the same procedure to address earlier feedback.',
        'method_change': 'Replace the approach or mechanism to address earlier feedback.',
        'gather_information': 'Gather additional evidence about the feedback or to decide a next step.',
        'continue': 'Proceed with the existing approach, including its next execution step or check, without an established adjustment.',
        'not_applicable': 'No prior action with visible feedback is available.',
        'unresolved': 'The response relationship or the nature of an adjustment cannot be established.',
    },
}
RESPONSE_QUESTION_V2 = {**RESPONSE_QUESTION,
    'instructions': 'Compare current_action with the most recent prior action and its visible feedback in this same agent trajectory. Classify the observable response using operation definitions and local purpose, not tool names or argument differences alone. An unchanged operation is repeat, without implying failure or unchanged environment state. Reading another source to decide what to do is gather_information even during an ongoing investigation. Distinguish replacing a procedure from adjusting only its settings: a parameter can encode an entirely different algorithm or mechanism. A planned next execution step or verification check is continue when no adjustment to address feedback is established. Do not infer an unexpressed causal reason or successful recovery.',
    'criteria': {**RESPONSE_QUESTION['criteria'],
        'parameter_change': 'Adjust only settings or inputs within the same procedure to address feedback. The procedure itself stays the same; a parameter selecting a different algorithm or mechanism is not this category.',
        'method_change': 'Replace the procedure, algorithm, route or operational mechanism to address feedback, including when this change is encoded by a parameter of the same tool.',
        'gather_information': 'Read, inspect or probe to learn facts for deciding what to do next, including continuing investigation into another source. This is not a check against an already specified expected result.',
        'continue': 'Perform the next execution step or verification check within the existing approach, without an established adjustment. Excludes exploratory information gathering.',
    }}


def cases():
    scenarios = [
        ('software', 'Make the parser handle nested brackets.',
         'parse_regex', {'input': '[a,[b,c]]'}, 'Use the current regular-expression parser.',
         'Nested brackets remain unmatched by the regular-expression parser.',
         'parse_stack', {'input': '[a,[b,c]]'}, 'Parse the same input using a stack-based parser.',
         'Use the stack-based parser on this input.'),
        ('navigation', 'Deliver parcel P7 to pier B.',
         'road', {'parcel': 'P7', 'destination': 'pier B'}, 'Attempt delivery by road.',
         'Road delivery to pier B failed: the bridge is closed.',
         'ferry', {'parcel': 'P7', 'destination': 'pier B'}, 'Attempt delivery by ferry.',
         'Send P7 across on the ferry.'),
        ('service', 'Restore service on line L7.',
         'remote_reset', {'line': 'L7'}, 'Reset the customer line remotely.',
         'Remote reset failed. A broken cable requires an on-site repair.',
         'field_repair', {'line': 'L7'}, 'Dispatch a technician to repair the line on site.',
         'Dispatch the field repair for L7.'),
    ]
    for domain, goal, old, old_args, old_definition, failure, new, new_args, new_definition, expression in scenarios:
        log = '\n'.join(f'{i:05d} sample={i % 19} elapsed_ms={i * 7} status=recorded' for i in range(230))
        for placement in ('older', 'immediate'):
            operations = [('telemetry', {'limit': 230}, log, 'Read the diagnostic samples.')] if placement == 'older' else []
            result = failure if placement == 'older' else log + '\n' + failure
            operations += [(old, old_args, result, 'Attempt the requested work.'),
                           (new, new_args, None, expression)]
            doc = conversation(goal, operations, {'telemetry': 'Read diagnostic samples without changing state.',
                old: old_definition, new: new_definition})
            for fmt, document in representations(doc):
                yield {'id': domain + '-' + placement, 'kind': 'authored', 'format': fmt,
                    'document': document, 'reference': {'mode': 'apply', 'feedback_response': 'method_change'}}
    contrasts = [
        ('timeout-adjustment', 'Retrieve report R7.', 'request', {'report':'R7','timeout_s':2},
         'Timeout after 2 seconds.', 'request', {'report':'R7','timeout_s':20},
         'The request timed out; increase its timeout to 20 seconds.',
         {'request':'Retrieve the report, waiting at most timeout_s seconds.'}, 'parameter_change'),
        ('polling', 'Wait until job J7 finishes.', 'status', {'job':'J7'}, 'Job J7 is pending.',
         'status', {'job':'J7'}, 'Poll its status again.', {'status':'Read the job status without changing it.'}, 'repeat'),
        ('scheduled-next-record', 'Process records A then B with the standard procedure.', 'process', {'record':'A'},
         'Record A completed.', 'process', {'record':'B'}, 'Proceed to B as planned.',
         {'process':'Apply the standard procedure to the requested record.'}, 'continue'),
        ('next-inspection', 'Locate where the service reads its configuration.', 'read', {'file':'main.py'},
         'main.py imports settings from config.py.', 'read', {'file':'config.py'}, 'Look in config.py next.',
         {'read':'Read the named file without modifying it.'}, 'gather_information'),
        ('next-check', 'Run unit tests, then the integration suite.', 'test', {'suite':'unit'}, 'All unit tests passed.',
         'test', {'suite':'integration'}, 'Now run the integration suite as planned.',
         {'test':'Check the requested suite against its defined assertions.'}, 'continue'),
        ('encoded-method-change', 'Traverse graph G7 without visiting a node twice.', 'walk', {'graph':'G7','strategy':0},
         'Traversal exhausted memory on a cycle.', 'walk', {'graph':'G7','strategy':1},
         'Use a visited set to avoid cycling.',
         {'walk':'Traverse the graph. strategy 0 uses an unguarded recursive traversal; strategy 1 uses an iterative queue and visited set.'}, 'method_change'),
    ]
    for name, goal, old, old_args, feedback, new, new_args, expression, definitions, expected in contrasts:
        doc = conversation(goal, [(old,old_args,feedback,'Perform the next requested step.'),
            (new,new_args,None,expression)], definitions)
        for fmt, document in representations(doc):
            yield {'id': name, 'kind': 'response_boundary', 'format': fmt,
                'document': document, 'reference': {'feedback_response': expected}}
    path = Path(__file__).resolve().parents[1] / 'tests/fixtures/nebius-openhands/jbradberry-universe.json'
    document = json.loads(path.read_text(encoding='utf8'))
    for event, mode, response in [('e31', 'explore', 'gather_information'), ('e163', 'verify', 'continue')]:
        yield {'id': 'public-universe-' + event, 'kind': 'selected_public', 'format': 'native-openhands',
            'document': document, 'action_id': event, 'reference': {'mode': mode, 'feedback_response': response}}


def requests(arms=('current',)):
    client = JevClient()
    for case in cases():
        run = normalize(case['document'])[0]
        action = next(e for e in run['events'] if e['id'] == case['action_id']) if 'action_id' in case else \
            [e for e in run['events'] if e['kind'] == 'action'][-1]
        for arm in arms:
            request = client.request(run, action['id'])
            if arm not in {'production','response_definition','response_definition_v2'}:
                request['questions'] = {k:v for k,v in request['questions'].items() if k in case['reference']}
            if arm == 'response_definition' and 'feedback_response' in request['questions']:
                request['questions']['feedback_response'] = RESPONSE_QUESTION
            if arm == 'response_definition_v2' and 'feedback_response' in request['questions']:
                request['questions']['feedback_response'] = RESPONSE_QUESTION_V2
            if arm == 'full_recent':
                # Diagnostic ablation: complete only the same selected action/result
                # records. No future evidence or additional history is introduced.
                events = {e['id']:e for e in run['events']}
                complete = set()
                for record in request['state']['prior_actions']:
                    for item in [record['action'], *record['feedback']]:
                        e = events[item['event_id']]
                        item['text'] = e['text']; complete.add(e['id'])
                        if 'arguments' in e:
                            item['arguments_text'] = dumps(e['arguments']); complete.add(e['id'] + ':arguments')
                        for key in ('text_projection','source_text_ranges','omitted_text_ranges'):
                            item.pop(key, None)
                missing = request['state']['missingness']
                missing['truncated_event_ids'] = [x for x in missing['truncated_event_ids'] if x not in complete]
                for key in missing['required_truncated_by_question']:
                    missing['required_truncated_by_question'][key] = [x for x in missing['required_truncated_by_question'][key] if x not in complete]
            yield {k:v for k,v in case.items() if k not in {'document','action_id'}} | {
                'arm': arm, 'source_hash': digest(run), 'action_id': action['id'],
                'request_hash': digest(request), 'request': request}


def evaluate(output, *, live=False, arms=('current',)):
    root = Path(output); root.mkdir(parents=True, exist_ok=True)
    rows = list(requests(arms)); client = JevClient(); results = []
    (root / 'requests.json').write_text(dumps(rows), encoding='utf8')
    if live and not os.environ.get('JEV_API_KEY'):
        raise InputError('Set JEV_API_KEY for live evaluation.')
    for row in rows:
        result = {k:v for k,v in row.items() if k != 'request'}
        if live:
            path = root / (row['request_hash'] + '.json')
            if path.exists():
                saved = json.loads(path.read_text(encoding='utf8'))
                if saved['request'] != row['request']:raise InputError('Cached request differs')
                response = saved['response']
            else:
                response = client.transport(row['request'])
                score(response, row)
                path.write_text(dumps({'request': row['request'], 'response': response}), encoding='utf8')
            result['scores'] = score(response, row)
            print(row['id'], row['format'], row['arm'], {k:v['prediction'] for k,v in result['scores'].items()}, flush=True)
        results.append(result)
    groups = defaultdict(lambda: {'decisions': 0, 'correct': 0, 'failures': []})
    for row in results:
        for dimension, value in row.get('scores', {}).items():
            group = groups['/'.join([row['kind'], row['arm'], dimension])]
            group['decisions'] += 1; group['correct'] += value['correct']
            if not value['correct']:group['failures'].append(row['id'] + '/' + row['format'])
    report = {'model': client.model, 'harness': JEV_HARNESS, 'groups': dict(groups), 'results': results,
        'interpretation': 'Authored controls and two selected actions from one public trace, reported separately. Formats repeat the same underlying scenarios. No population-accuracy estimate. Full recent context is a diagnostic arm.'}
    (root / 'report.json').write_text(dumps(report), encoding='utf8')
    return {k:v for k,v in report.items() if k != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--prompt-key', action='store_true')
    parser.add_argument('--arms', nargs='+', choices=['current','full_recent','production','response_definition','response_definition_v2'], default=['current'])
    args = parser.parse_args()
    if args.prompt_key:os.environ['JEV_API_KEY'] = getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output, live=args.live, arms=args.arms)))
