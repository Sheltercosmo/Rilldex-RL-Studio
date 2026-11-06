"""Ablate preceding dialogue and information-gathering/checking definitions."""
import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_harness_generalization import representations, requests as harness_requests
from tracker.adapters import normalize
from tracker.jev import JevClient, validate_answers
from tracker.action_context import visible_before
from tracker.schema import digest, dumps

BOUNDARY=('Distinguish gathering facts for a later decision from testing an expectation. '
          'A lookup that supplies previously unknown information is explore, even when a task policy requires later checks. '
          'Use verify when this dispatch is used to test a specified claim, expected result or acceptance criterion. '
          'The same read tool can serve either purpose; use the expressed local purpose, not its name alone.')


def add_context(req,run,action):
    req['state']['recent_expressions']=[{'event_id':e['id'],'kind':e['kind'],'actor':e['actor'],
        'text':e['text'][:6000],'source_pointer':e['source_pointer'],'source_characters':len(e['text'])}
        for e in run['events'] if e['kind'] in {'message','reasoning'} and e['actor']==action['actor']
        and visible_before(e,action) and not e.get('copied_context') and e['text'].strip()][-3:]
    req['state']['expression_scope']='Earlier visible dialogue provides context, not a native parent link, promise of execution or proof of success.'


def requests():
    client=JevClient()
    for domain,description,identifier,read,check in [
        ('browser','Retrieve the current DOM text without changing the page.',{'page':'checkout'},
         'Read the checkout page to discover its controls before deciding what to do.',
         'Use the checkout DOM to test whether the submitted form displays the expected confirmation CONFIRMED.'),
        ('file','Retrieve the contents of a file without changing it.',{'file':'report.txt'},
         'Read report.txt to learn what it currently contains before choosing an edit.',
         'Read report.txt to check that the saved edit contains exactly the expected heading Results.'),
        ('sensor','Read a sensor voltage without modifying the sensor.',{'sensor':'A7'},
         'Read sensor A7 to discover its current voltage before deciding what to do.',
         'Read sensor A7 to test whether the calibration produced the expected 3.3 volts.')]:
        for purpose,expression in [('explore',read),('verify',check)]:
            doc={'messages':[{'role':'user','content':'Investigate this task and report the result.'},
                {'role':'assistant','content':expression,'tool_calls':[{'id':'call','type':'function',
                  'function':{'name':'dispatch','arguments':dumps(identifier)}}]}],
                'tools':[{'type':'function','function':{'name':'dispatch','description':description,'parameters':{'type':'object'}}}]}
            for fmt,document in representations(doc):
                run=normalize(document)[0];action=next(e for e in run['events'] if e['kind']=='action')
                base=client.request(run,action['id']);base['questions']={'mode':base['questions']['mode']}
                production=deepcopy(base)
                base['questions']['mode']['instructions']=base['questions']['mode']['instructions'].replace(' '+BOUNDARY,'')
                base['state'].pop('recent_expressions',None);base['state'].pop('expression_scope',None)
                for arm in ('baseline','expressions','expressions_and_boundary','production'):
                    req=deepcopy(base)
                    if arm=='production':req=deepcopy(production)
                    elif arm!='baseline':add_context(req,run,action)
                    if arm=='expressions_and_boundary':req['questions']['mode']['instructions']+=' '+BOUNDARY
                    yield {'case_id':domain+'-'+purpose,'format':fmt,'arm':arm,'reference':purpose,'request':req}
    for row in harness_requests():
        if row['case_id']!='airline-3-e7' or row['layer']!='macro':continue
        # For this case no local parent intention is supplied in any format.
        for arm in ('baseline','boundary','production','production_boundary'):
            req=deepcopy(row['request'])
            req['questions']['mode']['instructions']=req['questions']['mode']['instructions'].replace(' '+BOUNDARY,'')
            if arm in ('baseline','boundary'):
                req['state'].pop('recent_expressions',None);req['state'].pop('expression_scope',None)
            if arm in ('boundary','production_boundary'):req['questions']['mode']['instructions']+=' '+BOUNDARY
            for repetition in range(3 if arm.startswith('production') else 1):
                yield {'case_id':row['case_id'],'format':row['format'],'arm':arm,'repetition':repetition,'reference':'explore','request':req}


def evaluate(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);rows=list(requests());results=[];client=JevClient()
    (root/'requests.json').write_text(dumps(rows),encoding='utf8')
    for row in rows:
        key=digest(row['request']);suffix='-repeat'+str(row['repetition']) if row.get('repetition') else ''
        path=root/(key+suffix+'.json')
        if path.exists():response=json.loads(path.read_text(encoding='utf8'))['response']
        else:
            response=client.transport(row['request']);path.write_text(dumps({'request':row['request'],'response':response}),encoding='utf8')
        assert response['model']==client.model
        pred=validate_answers(response,row['request'])['mode']['value']
        result={k:v for k,v in row.items() if k!='request'}
        results.append({**result,'request_hash':key,'prediction':pred,'correct':pred==row['reference']})
        print(row['case_id'],row['format'],row['arm'],pred,flush=True)
    (root/'report.json').write_text(dumps(results),encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--prompt-key',action='store_true');a=p.parse_args()
    if a.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    evaluate(a.output)
