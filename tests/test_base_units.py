import copy
import json
from pathlib import Path
import tempfile
import unittest
from tracker.activity import units
from tracker.adapters import normalize
from tracker.base_units import BaseClient, ACTIVITIES, project
from tracker.schema import InputError, dumps
from research.occurrence_controls import fixed_response


def fixture():
    run=normalize({'schema_version':'ATIF-v1.7','session_id':'base-unit-test','agent':{'name':'test','version':'1'},'steps':[
        {'step_id':1,'source':'agent','message':'Since the code does not use the decorator, we need to add it to the class to reproduce the issue.'},
        {'step_id':2,'source':'agent','message':'FUTURE success result.'}]})[0]
    return run,next(u['id'] for u in units(run) if u['eligible'])


def response(req):
    stage=req['state']['stage']
    if stage=='unit_boundary':return fixed_response(req,lambda k,q:'coherent_unit')
    if stage=='base_activity':return fixed_response(req,lambda k,q:'orient')
    target=next(c['id'] for c in req['state']['candidates'] if c['text']=='the code')
    r=fixed_response(req,lambda k,q:target if k=='focus' else 'not_expressed')
    for a in r['answers'].values():a.update(choice='unresolved',confidence=0)
    return r


class BaseTests(unittest.TestCase):
    def test_stages_depend_on_unit_then_category_without_prior_tags(self):
        run,uid=fixture();calls=[]
        def transport(req):calls.append(copy.deepcopy(req));return response(req)
        client=BaseClient(transport=transport);saved=client.evaluate(run,uid);view=project(saved)
        self.assertEqual([r['state']['stage'] for r in calls],['unit_boundary','base_activity','local_content'])
        self.assertEqual(set(calls[0]['questions']),{'unit'});self.assertEqual(set(calls[1]['questions']),{'activity'})
        self.assertNotIn('assess',ACTIVITIES);self.assertNotIn('revise',ACTIVITIES)
        self.assertNotIn('FUTURE',str(calls));self.assertNotIn('activity_definitions',str(calls))
        self.assertEqual(view['activity']['value'],'orient')
        focus=next(f for f in view['fields'] if f['name']=='focus');self.assertEqual(focus['selection']['text'],'the code')
        self.assertEqual(focus['decision']['confidence'],0)
        self.assertTrue(client.cache_matches(json.loads(dumps(saved)),run,uid))

    def test_bad_boundary_stops_category_and_extraction(self):
        run,uid=fixture()
        for choice in ['needs_broader_unit','needs_split','not_behavior','unresolved']:
            calls=[]
            def transport(req):calls.append(req);return fixed_response(req,lambda k,q:choice)
            client=BaseClient(transport=transport);saved=client.evaluate(run,uid);view=project(saved)
            self.assertEqual(len(calls),1);self.assertIsNone(view['activity']);self.assertEqual(view['fields'],[])
            self.assertEqual(view['unit_decision']['value'],choice);self.assertTrue(client.cache_matches(saved,run,uid))

    def test_each_partial_stage_resumes_without_repeating_successful_calls(self):
        run,uid=fixture()
        for failing in [2,3]:
            calls=[];checkpoints=[]
            def transport(req):
                calls.append(req['state']['stage'])
                if len(calls)==failing:raise InputError('temporary failure')
                return response(req)
            client=BaseClient(transport=transport)
            with self.assertRaises(InputError):client.evaluate(run,uid,checkpoint=lambda s:checkpoints.append(json.loads(dumps(s))) or True)
            saved=client.evaluate(run,uid,resume=checkpoints[-1]);self.assertEqual(len(calls),4)
            self.assertEqual(calls.count('unit_boundary'),1);self.assertTrue(client.cache_matches(saved,run,uid))

    def test_import_validation_rejects_missing_answers_altered_choices_and_stage_reordering(self):
        run,uid=fixture();client=BaseClient(transport=response);saved=client.evaluate(run,uid)
        broken=copy.deepcopy(saved);broken['_stages'][1]['answers']['activity']['value']='plan'
        self.assertFalse(client.cache_matches(broken,run,uid))
        broken=copy.deepcopy(saved);broken['_stages'][2]['answers'].pop('focus')
        self.assertFalse(client.cache_matches(broken,run,uid))
        broken=copy.deepcopy(saved);broken['_stages'].reverse()
        self.assertFalse(client.cache_matches(broken,run,uid))
        broken=copy.deepcopy(saved);broken['_stages'][1]['request']['state']['unit_decision']['value']='needs_split'
        self.assertFalse(client.cache_matches(broken,run,uid))

    def test_unknown_category_does_not_trigger_fields(self):
        run,uid=fixture();calls=[]
        def transport(req):
            calls.append(req);return fixed_response(req,lambda k,q:'coherent_unit' if k=='unit' else 'unresolved')
        saved=BaseClient(transport=transport).evaluate(run,uid)
        self.assertEqual(len(calls),2);self.assertEqual(project(saved)['fields'],[])

    def test_full_standard_cache_does_not_mix_with_earlier_definitions(self):
        run,uid=fixture();old=BaseClient(transport=response);new=BaseClient(standard='behavioral-unit-standard/2',transport=response)
        before=old.evaluate(run,uid);after=new.evaluate(run,uid)
        self.assertTrue(old.cache_matches(before,run,uid));self.assertTrue(new.cache_matches(after,run,uid))
        self.assertFalse(new.cache_matches(before,run,uid));self.assertFalse(old.cache_matches(after,run,uid))
        self.assertEqual(before['_request']['state']['standard'],'behavioral-unit-standard/1')
        self.assertEqual(after['_request']['state']['standard'],'behavioral-unit-standard/2')
        choices=after['_stages'][1]['request']['questions']['activity']['criteria']
        self.assertTrue({'knowledge','decide','decline','social'} <= set(choices))
        self.assertTrue({'assess','revise'}.isdisjoint(choices))
