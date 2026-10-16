import copy
import json
import unittest
from tracker.activity import units
from tracker.adapters import normalize
from tracker.schema import InputError, digest, dumps
from tracker.unit_content import ContentClient, project
from research.occurrence_controls import fixed_response


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.run=normalize({'schema_version':'ATIF-v1.7','session_id':'orient-test','agent':{'name':'test','version':'1'},'steps':[
            {'step_id':1,'source':'agent','message':'Since the code does not use the decorator, we need to add it to the class to reproduce the issue.'},
            {'step_id':2,'source':'agent','message':'FUTURE: all tests passed.'}]})[0]
        self.unit=next(u for u in units(self.run) if u['eligible'])
        self.ref={'unit_id':self.unit['id'],'source_hash':digest(self.unit['text']),'category':'orient','basis':'authored_test_not_human_reference'}

    def test_direct_fields_have_whole_unit_and_no_relation_or_activity_questions(self):
        req=ContentClient(reference=self.ref).request(self.run,self.unit['id'])
        self.assertEqual(set(req['questions']),{'target','situation','needed_work'})
        self.assertEqual(req['state']['subject']['text'],self.unit['text'])
        self.assertNotIn('FUTURE',str(req))
        for c in req['state']['candidates']:
            self.assertEqual(self.unit['text'][c['start']-self.unit['start']:c['end']-self.unit['start']],c['text'])

    def test_reference_binding_prevents_using_a_category_for_another_unit(self):
        for key,value in [('source_hash','wrong'),('unit_id','wrong'),('category','plan')]:
            with self.assertRaises(InputError):ContentClient(reference={**self.ref,key:value}).request(self.run,self.unit['id'])

    def test_raw_argmax_exact_saved_replay_and_explicit_missing_field(self):
        def transport(req):
            selected=next(c['id'] for c in req['state']['candidates'] if c['text']=='the code')
            response=fixed_response(req,lambda k,q:selected if k=='target' else 'not_expressed')
            for a in response['answers'].values():a.update(confidence=0,choice='unresolved')
            return response
        client=ContentClient(reference=self.ref,transport=transport);saved=client.evaluate(self.run,self.unit['id'])
        fields=project(saved)['fields'];self.assertEqual(fields[0]['selection']['text'],'the code')
        self.assertEqual(fields[0]['decision']['confidence'],0);self.assertIsNone(fields[1]['selection'])
        self.assertTrue(client.cache_matches(json.loads(dumps(saved)),self.run,self.unit['id']))
        changed=copy.deepcopy(saved);changed['target']['value']='unresolved'
        self.assertFalse(client.cache_matches(changed,self.run,self.unit['id']))
