"""Live, cached controls for context-dependent readings across environments.

Public trace selections and authored controls are reported separately. The
complete-prefix arm diagnoses missing context; it is not a production policy.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker.capabilities import recorded_scope
from tracker.jev import JevClient, DEFAULT_MODEL, validate_answers
from tracker.schema import InputError, digest, dumps


def conversation(goal, operations, descriptions):
    messages = [{'role': 'user', 'content': goal}]
    for i, (name, arguments, result, expression) in enumerate(operations):
        messages.append({'role': 'assistant', 'content': expression, 'tool_calls': [
            {'id': f'c{i}', 'type': 'function', 'function': {'name': name, 'arguments': dumps(arguments)}}]})
        if result is not None:
            messages.append({'role': 'tool', 'tool_call_id': f'c{i}', 'content': dumps(result)})
    return {'messages': messages, 'tools': [{'type': 'function', 'function': {
        'name': name, 'description': description, 'parameters': {'type': 'object'}}}
        for name, description in descriptions.items()]}


def cases():
    for domain, goal, field, low, high, operation, arguments, description in [
        ('inventory', 'Reserve 4 units of SKU A7 only if its recorded available stock is at least 4. Otherwise wait.',
         'available', 3, 8, 'reserve', {'sku': 'A7', 'quantity': 4}, 'Reserve the requested quantity from the SKU.'),
        ('navigation', 'Move rover R7 only if its battery_percent is at least 20. Otherwise wait.',
         'battery_percent', 10, 90, 'drive', {'rover': 'R7', 'distance': 2}, 'Command the rover to move the given distance.'),
        ('publishing', 'Publish document D7 only if its recorded review_approved is true. Otherwise wait.',
         'review_approved', False, True, 'publish', {'document': 'D7'}, 'Publish the specified document publicly.'),
    ]:
        identity = {k: v for k, v in arguments.items() if isinstance(v, str)}
        for condition, value, expected in [('blocked', low, 'conflicting'), ('allowed', high, 'direct')]:
            for distance in ('near', 'distant'):
                ops = [('state', identity, {**identity, field: value}, 'Read the relevant state.')]
                if distance == 'distant':
                    ops += [('sensor', {'station': f'S{i}'}, {'temperature': 18+i}, 'Read the next station.') for i in range(5)]
                ops += [(operation, arguments, None, 'Perform the requested operation now.')]
                yield {'id': f'{domain}-{condition}-{distance}', 'kind': 'authored',
                    'document': conversation(goal, ops, {'state': 'Read current state without changing it.',
                        'sensor': 'Read a weather station temperature.', operation: description}),
                    'reference': {'mode': 'apply', 'goal_relation': expected}}
        # A later state supersedes the earlier constraint value. Retrieval must
        # not turn an old blocked state into a permanent property of the task.
        ops = [('state', identity, {**identity, field: low}, 'Read the relevant state.')]
        ops += [('sensor', {'station': f'S{i}'}, {'temperature': 18+i}, '') for i in range(5)]
        ops += [('state', identity, {**identity, field: high}, 'Refresh the relevant state.'),
                (operation, arguments, None, 'Perform the requested operation now.')]
        yield {'id': domain+'-state-updated', 'kind': 'authored',
               'document': conversation(goal, ops, {'state': 'Read current state without changing it.',
                   'sensor': 'Read a weather station temperature.', operation: description}),
               'reference': {'goal_relation': 'direct'}}
    for name, ops, expected in [
        ('retry', [('direct', {'target':'B7'}, {'error':'route closed'}, 'Try the direct route.'),
                   ('direct', {'target':'B7'}, None, 'Try exactly the same route again.')], 'repeat'),
        ('revise', [('direct', {'target':'B7'}, {'error':'route closed'}, 'Try the direct route.'),
                    ('ferry', {'target':'B7'}, None, 'The route is closed; use the ferry instead.')], 'method_change'),
        ('inspect', [('direct', {'target':'B7'}, {'error':'route closed'}, 'Try the direct route.'),
                     ('survey', {'target':'B7'}, None, 'Inspect alternate routes before choosing.')], 'gather_information'),
    ]:
        yield {'id': 'navigation-'+name, 'kind':'authored',
               'document':conversation('Deliver the package to B7.', ops,
                    {'direct':'Attempt delivery by the direct road.', 'ferry':'Attempt delivery by a ferry crossing.',
                     'survey':'Read available routes without dispatching delivery.'}),
               'reference':{'feedback_response':expected, 'expressed_plan_followed':'follows'}}
    for variant, stock, expected in [('long-blocked',3,'conflicting'),('long-allowed',8,'direct'),
                                     ('renamed-blocked',3,'conflicting')]:
        ops=[('read', {'sku':'Z-91'}, {'sku':'Z-91','available':stock}, 'Read the stock record.')]
        ops += [('sensor', {'station':f'W{i}'}, {'temperature':12+i}, '') for i in range(9)]
        ops += [('reserve', {'sku':'Z-91','quantity':4}, None, 'Reserve four units now.')]
        doc=conversation('Reserve four units of Z-91 only when its recorded available stock is at least four; otherwise wait.',ops,
            {'read':'Read the current stock without modifying it.', 'sensor':'Read a weather station temperature.',
             'reserve':'Reserve the supplied quantity from this SKU.'})
        if variant.startswith('long'):
            doc['messages'][2]['content']='unrelated readings '*500+f'SKU Z-91 available stock is {stock}.'+' diagnostics '*500
        else:
            aliases={'read':'op_61','sensor':'op_27','reserve':'op_83'}
            for msg in doc['messages']:
                for call in msg.get('tool_calls',[]):call['function']['name']=aliases[call['function']['name']]
            for tool in doc['tools']:tool['function']['name']=aliases[tool['function']['name']]
        yield {'id':'inventory-'+variant,'kind':'authored','document':doc,'reference':{'goal_relation':expected}}
    for file, event_id, expected in [('airline-0','e7','coordinate'), ('airline-3','e7','explore'),
            ('airline-3','e12','apply'), ('telecom-0','e7','explore'), ('telecom-0','e10','explore'),
            ('telecom-4','e16','explore'), ('telecom-4','e19','apply')]:
        yield {'id':file+'-'+event_id, 'kind':'public_trace', 'action_id':event_id,
               'document':json.loads((Path(__file__).resolve().parents[1]/'tests/fixtures/tau-bench'/
                                      (file+'.json')).read_text(encoding='utf-8')),
               'reference':{'mode':expected}}


def requests(model, arms):
    client = JevClient(model=model)
    for case in cases():
        run = normalize(case['document'])[0]
        action = next(e for e in run['events'] if e['id']==case['action_id']) if 'action_id' in case else \
                 [e for e in run['events'] if e['kind']=='action'][-1]
        for arm in arms:
            request = client.request(run, action['id'])
            request['questions'] = {k:v for k,v in request['questions'].items() if k in case['reference']}
            if arm == 'complete_prefix':
                rows = [deepcopy(e) for e in run['events'] if e['index'] < action['index'] and
                    recorded_scope(e)==recorded_scope(action) and not e.get('copied_context') and
                    e.get('agent_visible') is not False and e.get('agent_visibility')!='not_established' and
                    not e['kind'].startswith('external_')]
                # Small diagnostic captures only, not an unbounded product path.
                if len(dumps(rows)) > 90000:continue
                request['state']['diagnostic_source_prefix'] = rows
            yield {'case_id':case['id'], 'kind':case['kind'], 'arm':arm, 'reference':case['reference'],
                   'request_hash':digest(request), 'request':request}


def score(response, row):
    if response.get('model') != row['request']['model']:
        raise InputError('Evaluation response model differs from the requested version')
    answers = validate_answers(response, row['request'])
    scores = {}
    for key, expected in row['reference'].items():
        answer = answers[key]
        value = answer['value'] if answer['status']=='decided' else answer['status']
        scores[key] = {'expected':expected, 'prediction':value, 'correct':value==expected,
                       'probabilities':answer['probabilities']}
    return scores


def evaluate(output, *, live=False, model=DEFAULT_MODEL, arms=('current','complete_prefix')):
    root=Path(output);root.mkdir(parents=True, exist_ok=True)
    rows=list(requests(model, arms))
    (root/'requests.json').write_text(dumps(rows), encoding='utf-8')
    if live and not os.environ.get('JEV_API_KEY'):raise InputError('Set JEV_API_KEY for live evaluation')
    client=JevClient(model=model);results=[]
    for row in rows:
        record={k:v for k,v in row.items() if k!='request'}
        if live:
            path=root/(row['request_hash']+'.json')
            if path.exists():
                saved=json.loads(path.read_text(encoding='utf-8'))
                if saved['request']!=row['request']:raise InputError('Cached request differs')
                response=saved['response']
            else:
                response=client.transport(row['request'])
                score(response,row)
                path.write_text(dumps({'request':row['request'],'response':response}), encoding='utf-8')
            record['scores']=score(response,row)
            print(row['case_id'], row['arm'], {k:v['prediction'] for k,v in record['scores'].items()}, flush=True)
        results.append(record)
    groups={}
    for row in results:
        for dimension, value in row.get('scores',{}).items():
            key='/'.join([row['kind'],row['arm'],dimension])
            g=groups.setdefault(key,{'cases':0,'correct':0,'failures':[]})
            g['cases']+=1;g['correct']+=value['correct']
            if not value['correct']:g['failures'].append(row['case_id'])
    from tracker.jev import JEV_HARNESS
    report={'status':'evaluated' if live else 'requests_only', 'model':model,'harness':JEV_HARNESS,'groups':groups,'results':results,
            'interpretation':'Development controls and selected public trace actions; references are authored. No population accuracy estimate. Complete-prefix is a context ablation, not the production reader.'}
    (root/'report.json').write_text(dumps(report), encoding='utf-8')
    return {k:v for k,v in report.items() if k!='results'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('outputs/reading-context'))
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--arms',nargs='+',choices=['current','complete_prefix'],default=['current','complete_prefix'])
    args=parser.parse_args()
    try:print(dumps(evaluate(args.output,live=args.live,arms=args.arms)))
    except InputError as exc:parser.exit(2,str(exc)+'\n')
