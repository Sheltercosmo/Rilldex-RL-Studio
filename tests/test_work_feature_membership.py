from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import graph_store, work_mentions, work_content_bindings as scoped
from tracker import work_feature_membership as membership
from tracker.adapters import normalize
from tracker.metered_jev import BoundedTransport
from tracker.portable import chat_document
from tracker.schema import InputError, digest


def fixture():
    text = 'Using the staging database, I will inspect the schema and validate the records. Then I will publish the report.'
    run = normalize(chat_document([dict(role='assistant', content=text)]))[0]
    graph = graph_store.build(run)
    event = run['events'][0]
    graph['nodes'].append(dict(id='u1', kind='unit', activity='orient', event_index=0,
        trajectory_id=event['trajectory_id'], properties=dict(kind='semantic', actor='agent',
            status='selected', source=dict(event_id=event['id'], start=0, end=len(text), text=text))))
    graph['counts']['nodes'] = len(graph['nodes'])
    graph.pop('id'); graph['id'] = 'graph-'+digest(graph)
    packet = work_mentions.packet(graph, ['u1'])
    body = dict(contents=[dict(id=key, kind='operation', mode='proposed', expression=dict(text=phrase))
        for key, phrase in [('inspect','inspect the schema'), ('validate','validate the records'),
                            ('publish','publish the report')]],
        features=[dict(id='database', type='method', form='literal',
                       expression=dict(text='Using the staging database'), scopes=[['inspect']])])
    bound = scoped.bind(packet, scoped.request(packet, 'u1'), body, 'authored structural fixture')
    return packet, body, bound


def response(req, *, shape='separable', attached=('inspect','validate'), unresolved=()):
    choices = dict(scope_shape=shape)
    for i,c in enumerate(req['state']['contents']):
        choices['c'+str(i)] = ('unresolved' if c['id'] in unresolved else
                             'attached' if c['id'] in attached else 'not_attached')
    return dict(model=req['model'], answers={key:dict(type='choice', choice='unresolved', confidence=0,
        probabilities={value: .4 if value == choices[key] else .6/(len(q['criteria'])-1)
                       for value in q['criteria']}) for key,q in req['questions'].items()})


class FeatureMembershipTests(unittest.TestCase):
    def test_shared_scope_not_supplied_is_representable_without_changing_base(self):
        p, _, b = fixture(); before = deepcopy((p,b)); req = membership.request(p,b,'database')
        result = membership.resolve(p,b,'database',response(req))
        self.assertEqual(result['content_ids'],['inspect','validate'])
        self.assertEqual(result['publication'],'review_only')
        self.assertEqual(result['selection_policy'],'argmax/1')
        self.assertEqual(result['response']['answers']['c0']['confidence'],0)
        self.assertEqual((p,b),before)
        self.assertEqual(set(req['questions']),{'scope_shape','c0','c1','c2'})
        self.assertNotIn('scopes',req['state']['feature'])
        self.assertEqual(req['state']['unit']['source'],p['units'][0]['source'])

    def test_scope_options_and_content_order_do_not_change_request_or_use_more_calls(self):
        p,body,b = fixture(); req = membership.request(p,b,'database')
        body['features'][0]['scopes']=[['publish'],['inspect','validate'],['validate']]
        body['contents'].reverse()
        other=scoped.bind(p,scoped.request(p,'u1'),body,'different candidate producer')
        self.assertEqual(req,membership.request(p,other,'database'))
        sent=[]
        with tempfile.TemporaryDirectory() as directory:
            transport=BoundedTransport(directory,1,send=lambda r:sent.append(r) or response(r))
            first=membership.resolve(p,b,'database',transport(req))
            second=membership.resolve(p,other,'database',transport(membership.request(p,other,'database')))
        self.assertEqual(len(sent),1)
        self.assertEqual(first['content_ids'],second['content_ids'])
        self.assertNotEqual(first['bound_hash'],second['bound_hash'])

    def test_missing_joint_or_ambiguous_scope_never_emits_partial_union(self):
        p,_,b=fixture();req=membership.request(p,b,'database')
        for shape,status in [('joint','joint_scope'),('missing_content','incomplete_content_inventory'),
                             ('unresolved','unresolved_scope')]:
            with self.subTest(shape=shape):
                result=membership.resolve(p,b,'database',response(req,shape=shape))
                self.assertEqual(result['status'],status)
                self.assertIsNone(result['content_ids'])
                self.assertEqual(result['positive_content_ids'],['inspect','validate'])
        result=membership.resolve(p,b,'database',response(req,unresolved=('publish',)))
        self.assertEqual(result['status'],'unresolved_membership')
        self.assertIsNone(result['content_ids'])
        self.assertEqual(result['unresolved_content_ids'],['publish'])

    def test_all_negative_is_not_a_valid_empty_attachment(self):
        p,_,b=fixture();req=membership.request(p,b,'database')
        result=membership.resolve(p,b,'database',response(req,attached=()))
        self.assertEqual(result['status'],'no_attachment_selected')
        self.assertIsNone(result['content_ids'])

    def test_tampered_source_contents_feature_and_model_fail(self):
        p,_,b=fixture();req=membership.request(p,b,'database');raw=response(req)
        for field in ['source','content','feature','model']:
            pp,bb,rr=deepcopy((p,b,raw))
            if field=='source':pp['units'][0]['source']['text']='changed'
            if field=='content':bb['contents'][0]['mode']='asserted'
            if field=='feature':bb['features'][0]['type']='negation'
            if field=='model':rr['model']='other'
            with self.subTest(field=field),self.assertRaises(InputError):
                membership.resolve(pp,bb,'database',rr)
        with self.assertRaises(InputError):membership.request(p,b,'absent')

    def test_every_pair_needs_a_valid_distribution(self):
        p,_,b=fixture();req=membership.request(p,b,'database')
        for change in ['missing','foreign','nan']:
            raw=response(req)
            if change=='missing':raw['answers'].pop('c1')
            if change=='foreign':raw['answers']['c1']['probabilities']['foreign']=0.1
            if change=='nan':raw['answers']['c1']['probabilities']['attached']=float('nan')
            with self.subTest(change=change),self.assertRaises(InputError):membership.resolve(p,b,'database',raw)

    def test_comparison_preserves_disagreement_and_missing_option_without_winner(self):
        p,_,b=fixture();req=scoped.focused_scope_request(p,b,'database')
        old=dict(model=req['model'],answers=dict(scope=dict(type='choice',probabilities=
            {k:float(k=='s0') for k in req['questions']['scope']['criteria']})))
        prior=scoped.focused_scope_result(p,b,'database',old)
        new_req=membership.request(p,b,'database')
        new=membership.resolve(p,b,'database',response(new_req))
        result=membership.compare_to_choice(p,'database',b,prior,b,new)
        self.assertEqual(result['status'],'disagreement')
        self.assertEqual(result['changed_content_ids'],['validate'])
        self.assertFalse(result['membership_scope_was_offered'])
        self.assertEqual(result['resolution'],'not_adjudicated')
        unresolved=membership.resolve(p,b,'database',response(new_req,shape='joint'))
        result=membership.compare_to_choice(p,'database',b,prior,b,unresolved)
        self.assertEqual(result['status'],'incomplete')
        self.assertIsNone(result['changed_content_ids'])
        new['members'][0]['choice']='not_attached'
        with self.assertRaises(InputError):membership.compare_to_choice(p,'database',b,prior,b,new)

    def test_comparison_rejects_valid_rebound_with_different_content_meaning(self):
        p,body,b=fixture();req=scoped.focused_scope_request(p,b,'database')
        raw=dict(model=req['model'],answers=dict(scope=dict(type='choice',probabilities=
            {k:float(k=='s0') for k in req['questions']['scope']['criteria']})))
        prior=scoped.focused_scope_result(p,b,'database',raw)
        body['contents'][0]['mode']='asserted'
        changed=scoped.bind(p,scoped.request(p,'u1'),body,'different proposed meaning')
        new=membership.resolve(p,changed,'database',response(membership.request(p,changed,'database')))
        with self.assertRaisesRegex(InputError,'identical source, content and feature meanings'):
            membership.compare_to_choice(p,'database',b,prior,changed,new)


class RecordedMembershipTests(unittest.TestCase):
    """Offline protocol replay, including wrong readings; not accuracy acceptance."""

    def test_original_wire_receipts_replay_without_changing_scope_meaning(self):
        path=Path(__file__).parent/'fixtures/feature-membership/recorded-controls.json'
        cases=json.loads(path.read_text(encoding='utf-8'))['cases']
        results={}
        for case in cases:
            p,b,fid=case['packet'],case['bound'],case['feature_id']
            outputs={}
            for arm,saved in case['arms'].items():
                with self.subTest(case=case['case'],arm=arm):
                    req=(membership.request(p,b,fid) if arm=='membership' else scoped.focused_scope_request(p,b,fid))
                    self.assertEqual(req,saved['request'])
                    self.assertEqual(saved['receipt']['request_hash'],digest(req))
                    self.assertEqual(saved['receipt']['response_hash'],digest(saved['response']))
                    self.assertEqual(saved['receipt']['status'],'response_received')
                    result=(membership.resolve(p,b,fid,saved['response']) if arm=='membership' else
                            scoped.focused_scope_result(p,b,fid,saved['response']))
                    self.assertEqual(result,saved['result'])
                    outputs[arm]=result
            results[case['case']]=outputs
            comparison=membership.compare_to_choice(p,fid,b,outputs['choice'],b,outputs['membership'])
            self.assertEqual(comparison['resolution'],'not_adjudicated')
        # Scope membership fixes the method overextension in this control.
        self.assertEqual(results['shared-method']['membership']['content_ids'],['inspect','validate'])
        self.assertEqual(results['shared-method']['choice']['content_ids'],['inspect','publish','validate'])
        # Its broad scope judgment still fails on a distributive prohibition.
        shared=results['shared-negation']['membership']
        self.assertEqual(shared['scope_shape'],'joint')
        self.assertEqual(shared['positive_content_ids'],['delete','list','overwrite'])
        self.assertIsNone(shared['content_ids'])
        # A genuinely joint prohibition must not become two separate prohibitions.
        joint=results['joint-negation']['membership']
        self.assertEqual(joint['scope_shape'],'joint')
        self.assertIsNone(joint['content_ids'])
        self.assertEqual(joint['publication'],'review_only')


if __name__=='__main__':unittest.main()
