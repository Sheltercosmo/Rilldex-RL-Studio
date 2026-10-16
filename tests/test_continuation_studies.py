import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import continuation_studies as cs, training_lineage
from tracker.capture import Outbox
from tracker.schema import InputError, digest
from tracker.store import Store, ReviewConflict


def example(n=16):
    """Authored contract control, not a model experiment or measured success lift."""
    producer='control'; experiment='authored-continuation-control'
    ref=lambda name:{'producer':producer,'id':name}
    shared={'task_id':'test-task','policy_version':'test-policy-1','environment':'text-control','environment_version':'1'}
    tokens=list(range(2,1205))
    arms={a:{'prefix_tokens':end,'prefix_digest':digest(tokens[:end]),'state_id':None,
             'samples':[ref(a+str(i)) for i in range(n)]} for a,end in [('before',20),('after',1020)]}
    study={'id':'window-1','label':'Authored continuation control','basis':'Authored test records; no model executed',
           'master':ref('master'),**shared,'tokenizer_id':'test-vocab','settings_digest':'test-sampling',
           'budget_definition':'fixed 400 new tokens per draw','environment_kind':'text',
           'verifier':{'producer':producer,'component':'success','definition':'authored-binary/1'},
           'selection':'retrospective','independent_draws':True,'step':7,'step_basis':'authored generation step','arms':arms}
    def declaration(name,inputs,outputs,**extra):
        return {'id':'sample/'+name,'revision':0,'kind':'sample','sample':ref(name),
                'evidence':{'basis':'Authored control'},'data':{'split':'evaluation',**shared,**extra,
                'token_context':{'schema':'training-token-context/1','tokenizer_id':'test-vocab','boundary':'authored export',
                'generation':{'input_ids':inputs,'output_ids':outputs},
                'training':{'input_ids':inputs+outputs,'loss_mask':[0]*len(inputs)+[1]*len(outputs)}}}}
    records=[declaration('master',tokens[:2],tokens[2:])]
    for arm,gate in arms.items():
        for i,r in enumerate(gate['samples']):
            name=r['id']; records.append(declaration(name,tokens[:gate['prefix_tokens']],[5,6,7],
                continuation={'study':ref(study['id']),'arm':arm,'draw_id':name,'settings_digest':study['settings_digest'],
                              'budget_definition':study['budget_definition'],'state_id':None}))
            records.append({'id':'score/'+name,'revision':0,'kind':'score','sample':r,'evidence':{'basis':'Authored control'},
                'data':{'component':'success','definition':'authored-binary/1','status':'scored','value':int(i==0 if arm=='before' else i!=0)}})
    return ({'schema':cs.VERSION,'producer':producer,'experiment':experiment,'studies':[study]},
            {'schema':'training-records/2','producer':producer,'experiment':experiment,'records':records})


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'store.sqlite');self.design,self.facts=example()

    def load(self):
        cs.receive(self.store,self.design);training_lineage.receive(self.store,self.facts)

    def study(self):return cs.snapshot(self.store)['studies'][0]

    def test_before_after_counts_and_independent_interval(self):
        self.load();s=self.study()
        self.assertEqual(s['span_tokens'],1000);self.assertEqual(s['difference'],.875)
        self.assertEqual([s['arms'][a]['successes'] for a in cs.ARMS],[1,15])
        self.assertEqual(s['arms']['before']['rate'],1/16)
        self.assertAlmostEqual(s['arms']['before']['interval'][0],0.01111934476464255)
        self.assertAlmostEqual(s['arms']['before']['interval'][1],0.28328737570298945)
        self.assertTrue(.55<s['interval'][0]<.58);self.assertTrue(.94<s['interval'][1]<.96)
        self.assertEqual(s['arms']['after']['generated_tokens'],48)

    def test_late_results_never_imply_failures_or_partial_lift(self):
        cs.receive(self.store,self.design)
        self.assertIsNone(self.study()['difference'])
        records=self.facts['records'];last=records.pop()
        training_lineage.receive(self.store,self.facts);s=self.study()
        self.assertEqual(s['arms']['after']['observed'],15);self.assertIsNone(s['difference'])
        self.assertIsNone(s['arms']['before']['interval'])
        training_lineage.receive(self.store,{**self.facts,'records':[last]})
        self.assertEqual(self.study()['difference'],.875)

    def test_corrected_outcomes_change_snapshot_without_rewriting_design(self):
        self.load();old=self.study();r=copy.deepcopy(self.facts['records'][-1]);r['revision']=3;r['data']['value']=0
        training_lineage.receive(self.store,{**self.facts,'records':[r]})
        new=self.study();self.assertNotEqual(old['snapshot_id'],new['snapshot_id'])
        self.assertEqual(new['difference'],.8125);self.assertEqual(old['difference'],.875)
        self.assertEqual(new['design'],old['design'])

    def test_conflicting_scores_are_not_chosen_by_arrival_order(self):
        self.load();r=copy.deepcopy(self.facts['records'][-1]);r['id']='other-score'
        training_lineage.receive(self.store,{**self.facts,'records':[r]})
        self.assertIsNone(self.study()['difference'])
        self.assertEqual(self.study()['arms']['after']['issues'],{'conflicting_score':1})

    def test_nonbinary_unavailable_and_error_scores_are_excluded(self):
        for change in [{'status':'scored','value':.5},{'status':'unavailable','value':None},{'status':'error','value':None}]:
            with self.subTest(change=change):
                self.facts['records'][-1]['data'].update(change)
                with tempfile.TemporaryDirectory() as p:
                    store=Store(Path(p)/'s.sqlite');cs.receive(store,self.design);training_lineage.receive(store,self.facts)
                    self.assertIsNone(cs.snapshot(store)['studies'][0]['difference'])

    def test_master_prefix_mismatch_cannot_establish_lift(self):
        self.design['studies'][0]['arms']['before']['prefix_digest']='wrong';self.load()
        self.assertIsNone(self.study()['difference'])
        self.assertIn('Before gate does not match',self.study()['issues'][0])

    def test_sampler_metadata_and_token_identity_must_agree(self):
        for change in ['policy_version','tokenizer','prefix','budget','settings','membership']:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as p:
                design,facts=example(2);d=facts['records'][1]['data']
                if change=='policy_version':d['policy_version']='another-policy'
                elif change=='tokenizer':d['token_context']['tokenizer_id']='other-vocab'
                elif change=='prefix':d['token_context']['generation']['input_ids'][0]=999
                elif change=='budget':d['continuation']['budget_definition']='different'
                elif change=='settings':d['continuation']['settings_digest']='different'
                else:d.pop('continuation')
                store=Store(Path(p)/'s.sqlite');cs.receive(store,design);training_lineage.receive(store,facts)
                self.assertIsNone(cs.snapshot(store)['studies'][0]['difference'])

    def test_duplicate_draw_ids_in_distinct_sample_ids_are_detected(self):
        self.facts['records'][3]['data']['continuation']['draw_id']='before0';self.load()
        self.assertIsNone(self.study()['difference']);self.assertTrue(any('Repeated draw' in p for p in self.study()['issues']))

    def test_dependent_draws_allow_descriptive_difference_without_interval(self):
        self.design['studies'][0]['independent_draws']=False;self.load()
        self.assertEqual(self.study()['difference'],.875);self.assertIsNone(self.study()['interval'])

    def test_all_successes_are_zero_difference_with_nonzero_uncertainty(self):
        for r in self.facts['records']:
            if r['kind']=='score':r['data']['value']=1
        self.load();s=self.study()
        self.assertEqual(s['difference'],0)
        self.assertLess(s['interval'][0],0);self.assertGreater(s['interval'][1],0)

    def test_generation_facts_from_another_experiment_cannot_join(self):
        cs.receive(self.store,self.design)
        training_lineage.receive(self.store,{**self.facts,'experiment':'another-job'})
        s=self.study();self.assertIsNone(s['difference'])
        self.assertEqual(s['arms']['before']['observed'],0)

    def generation_only(self):
        for r in self.facts['records']:
            if r['kind']=='sample':
                t=r['data'].pop('token_context')
                r['data']['generation_context']={'schema':'generation-token-context/1',
                    'tokenizer_id':t['tokenizer_id'],'boundary':'native sampler output',**t['generation']}

    def test_generation_only_probes_need_no_training_inputs_or_masks(self):
        self.generation_only();self.load();s=self.study()
        self.assertEqual(s['difference'],.875)
        self.assertEqual(s['arms']['before']['cases'][0]['training_stages'],[])
        population=training_lineage.snapshot(self.store)
        self.assertFalse(any(r['populations']['backward'] for r in population['samples']))
        self.assertTrue(all('generation_context_summary' in r for r in population['samples']))
        self.assertFalse(any('generation_context' in r for r in population['samples']))

    def test_disagreeing_generation_and_training_export_evidence_is_rejected(self):
        r=self.facts['records'][0];t=r['data']['token_context']
        r['data']['generation_context']={'schema':'generation-token-context/1',
            'tokenizer_id':t['tokenizer_id'],'boundary':'sampler','input_ids':[999],
            'output_ids':t['generation']['output_ids']}
        with self.assertRaises(InputError):training_lineage.receive(self.store,self.facts)

    def test_generation_only_record_does_not_hide_known_mixed_policy_evidence(self):
        r=self.facts['records'][1];t=r['data']['token_context']
        r['data']['generation_context']={'schema':'generation-token-context/1',
            'tokenizer_id':t['tokenizer_id'],'boundary':'sampler',**copy.deepcopy(t['generation'])}
        t['generation']['policy_versions']=[1,2,2]
        self.load();self.assertIsNone(self.study()['difference'])

    def test_generation_only_rejects_bad_shapes_and_nonfinite_logprobs(self):
        from tracker.training_token_context import validate_generation
        base={'schema':'generation-token-context/1','tokenizer_id':'t','boundary':'sampler','input_ids':[1],'output_ids':[2,3]}
        for extra in [{'output_ids':[True]},{'input_ids':[-1]},{'policy_versions':[1]},
                      {'logprobs':[float('nan'),0]},{'loss_mask':[1,1]}]:
            with self.subTest(extra=extra),self.assertRaises(InputError):validate_generation(base|extra)

    def test_before_gate_inside_prompt_is_invalid_even_if_digest_matches(self):
        s=self.design['studies'][0];s['arms']['before'].update(prefix_tokens=1,prefix_digest=digest([2]))
        self.load();self.assertFalse(self.study()['prefix_verified']);self.assertIsNone(self.study()['difference'])

    def test_idempotent_transport_and_atomic_conflict(self):
        self.assertEqual(cs.receive(self.store,self.design)['inserted'],1)
        self.assertEqual(cs.receive(self.store,self.design)['inserted'],0)
        packet=copy.deepcopy(self.design);packet['studies'][0]['label']='Changed'
        another=copy.deepcopy(packet['studies'][0]);another['id']='new'
        packet['studies'].insert(0,another)
        with self.assertRaises(ReviewConflict):cs.receive(self.store,packet)
        self.assertEqual(cs.snapshot(self.store)['total'],1)

    def test_duplicate_members_and_master_reuse_rejected(self):
        for ref in [self.design['studies'][0]['master'],self.design['studies'][0]['arms']['before']['samples'][0]]:
            packet=copy.deepcopy(self.design);packet['studies'][0]['arms']['after']['samples'][0]=ref
            with self.assertRaises(InputError):cs.validate(packet)

    def test_sandbox_requires_explicit_restore_state(self):
        self.design['studies'][0]['environment_kind']='sandbox'
        with self.assertRaises(InputError):cs.validate(self.design)
        for arm in cs.ARMS:self.design['studies'][0]['arms'][arm]['state_id']='snapshot-'+arm
        self.load();self.assertIsNone(self.study()['difference'])

    def test_stage_receipts_are_not_new_continuations(self):
        self.load();ref=self.design['studies'][0]['arms']['after']['samples'][0]
        receipt={'id':'use/1','revision':0,'kind':'use','sample':ref,'evidence':{'basis':'Authored control'},
                 'data':{'batch_id':'batch','learner_step':8,'stage':'backward_completed'}}
        training_lineage.receive(self.store,{**self.facts,'records':[receipt]})
        s=self.study();self.assertEqual(s['arms']['after']['observed'],16)
        self.assertEqual(s['arms']['after']['cases'][0]['training_stages'],['backward_completed'])

    def test_confirmation_reuse_or_missing_design_withholds_comparison(self):
        self.design['studies'][0].update(selection='prospective',confirmation_of={'producer':'control','id':'absent'})
        self.load();self.assertEqual(self.study()['confirmation_status'],'design_missing')
        self.assertIsNone(self.study()['difference'])

    def confirmation(self, *, reuse_draw=False, change_gate=False):
        self.load();design,facts=example(16);s=design['studies'][0]
        s.update(id='confirm-1',selection='prospective',confirmation_of={'producer':'control','id':'window-1'})
        for arm in cs.ARMS:
            for ref in s['arms'][arm]['samples']:ref['id']='fresh-'+ref['id']
        if change_gate:s['arms']['after']['prefix_tokens']+=1
        for r in facts['records'][1:]:
            r['id']='fresh-'+r['id']
            if r['kind']=='sample':
                r['sample']['id']='fresh-'+r['sample']['id']
                member=r['data']['continuation'];member['study']['id']='confirm-1'
                if not reuse_draw:member['draw_id']='fresh-'+member['draw_id']
        # Score references share the design dictionaries; declarations do not.
        cs.receive(self.store,design);training_lineage.receive(self.store,{**facts,'records':facts['records'][1:]})
        return self.study()

    def test_confirmation_requires_fresh_samples_and_draws(self):
        s=self.confirmation();self.assertEqual(s['confirmation_status'],'fresh_identities_same_design')
        self.assertEqual(s['difference'],.875)

    def test_renaming_samples_does_not_make_reused_draws_fresh(self):
        s=self.confirmation(reuse_draw=True)
        self.assertEqual(s['confirmation_status'],'design_changed_or_samples_reused');self.assertIsNone(s['difference'])

    def test_mixed_policy_generations_withhold_comparison(self):
        self.facts['records'][1]['data']['token_context']['generation']['policy_versions']=[1,2,2]
        self.load();self.assertIsNone(self.study()['difference'])

    def test_unplanned_samples_are_visible_but_never_expand_denominator(self):
        self.load();r=copy.deepcopy(self.facts['records'][1]);r['id']='extra';r['sample']['id']='extra'
        training_lineage.receive(self.store,{**self.facts,'records':[r]})
        s=self.study();self.assertEqual(s['unplanned_samples'],[{'producer':'control','id':'extra'}])
        self.assertEqual(s['arms']['before']['expected'],16);self.assertEqual(s['difference'],.875)

    def test_filtering_pagination_and_revision(self):
        with self.store.connect() as c:before=training_lineage.revision(c)
        self.load()
        with self.store.connect() as c:self.assertNotEqual(before,training_lineage.revision(c))
        self.assertEqual(cs.snapshot(self.store,experiment='absent')['total'],0)
        self.assertEqual(cs.snapshot(self.store,environment='absent')['total'],0)
        self.assertEqual(cs.snapshot(self.store,offset=1)['studies'],[])
        with self.assertRaises(InputError):cs.snapshot(self.store,limit=0)

    def test_design_only_scope_is_selectable_without_source_rollouts(self):
        from tracker.monitoring import snapshot
        cs.receive(self.store,self.design);v=snapshot(self.store)
        self.assertEqual(v['experiments'],[{'id':self.design['experiment'],'count':0}])
        self.assertEqual(v['environments'],['text-control'])

    def test_outbox_lost_ack_and_wrong_ack(self):
        out=Outbox(Path(self.tmp.name)/'out.sqlite',producer='control')
        receipt=out.log_continuation_studies(self.design['experiment'],self.design['studies'])
        self.assertEqual(receipt['revision'],0)
        def lost(request,**kwargs):
            self.assertTrue(request.full_url.endswith('/api/continuation-studies'))
            cs.receive(self.store,json.loads(request.data));raise OSError('lost acknowledgement')
        with patch('tracker.capture.urlopen',side_effect=lost):self.assertEqual(out.drain()['pending'],1)
        with patch('tracker.capture.urlopen',return_value=io.BytesIO(b'{"id":"wrong","revision":0}')):
            self.assertEqual(out.drain()['pending'],1)
        def send(request,**kwargs):return io.BytesIO(json.dumps(cs.receive(self.store,json.loads(request.data))).encode())
        with patch('tracker.capture.urlopen',side_effect=send):self.assertEqual(out.drain()['sent_now'],1)
        self.assertEqual(cs.snapshot(self.store)['total'],1)


if __name__=='__main__':unittest.main()
