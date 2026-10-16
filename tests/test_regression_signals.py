import copy
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from tracker import regression_signals, training_setup, training_recipes, training_lineage, training_health, training_monitoring
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict
from test_training_health import record


def request(**config):
    return {'framework':'trl','trainer':'a2po','version':'1.13.0','resolved':True,
            'config':{'num_value_samples':3,'beta1':.5,'beta2':.2,'filter_all_incorrect':True,**config}}


def signal(**extra):
    return {'schema':'sample-regression/1','component':'rl-policy','definition':'authored-regression/1',
            'prediction':.2,'target':-.5,'baseline':.8,'reward':.3,**extra}


class RegressionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=Store(Path(temp.name)/'audit.sqlite')
        self.report=training_setup.inspect(request())
        training_recipes.receive(self.store,{'schema':'training-recipes/1','producer':'worker',
            'experiment':'exp','recipes':[self.report['recipe']]})
        self.ref={'producer':'worker','id':self.report['recipe']['id'],'revision':0}

    def add(self,*rows):
        training_lineage.receive(self.store,{'schema':'training-records/1','producer':'worker','experiment':'exp','records':list(rows)})

    def test_roundtrip_stage_counts_native_target_and_exact_case_fields(self):
        self.add(record('sample',recipe=self.ref),record('score'),
            record('use',recipe=self.ref,regression=signal(),model_tokens=4,loss_tokens=4),
            record('use',identifier='update',recipe=self.ref,regression=signal(),stage='optimizer_step_completed'))
        cohort=training_health.snapshot(self.store)['cohorts'][0]
        self.assertEqual(cohort['dashboard']['default']['mode'],'use')
        self.assertEqual(len(cohort['uses']),2)
        for use in cohort['uses']:
            r=use['regression']
            self.assertEqual(r['eligible_uses'],1)
            self.assertAlmostEqual(r['mean_squared_error'],.49)
            self.assertAlmostEqual(r['mean_error'],.7)
            self.assertEqual(r['mean_baseline'],.8)
            self.assertEqual(use['points'][0]['records'][0]['data']['regression'],signal())
        self.assertNotIn('group_contrast',{m['id'] for g in cohort['monitoring_plan']['groups'] for m in g['monitors']})

    def test_unbound_and_incompatible_observations_never_pool(self):
        context={'manifest':self.report['recipe']}
        rows=[{'data':{'regression':signal()}},{'data':{'regression':signal(definition='different/1')}}]
        result=regression_signals.summarize(rows,context)
        self.assertFalse(result['compatible_definitions']);self.assertEqual(result['eligible_uses'],0)
        self.assertIsNone(result['mean_squared_error'])
        result=regression_signals.summarize(rows,{'manifest':None})
        self.assertEqual(result['unbound_uses'],2);self.assertIsNone(result['mean_target'])
        wrong=copy.deepcopy(context);wrong['manifest']['components'][0]['objective']['weighting']='hard_gate'
        self.assertEqual(regression_signals.summarize(rows,wrong)['eligible_uses'],0)

    def test_missing_observation_and_baseline_are_not_zero(self):
        no_baseline=signal();del no_baseline['baseline'];del no_baseline['reward']
        result=regression_signals.summarize([{'data':{}},{'data':{'regression':no_baseline}}],{'manifest':self.report['recipe']})
        self.assertEqual(result['missing_uses'],1);self.assertEqual(result['baseline_uses'],0)
        self.assertIsNone(result['mean_baseline'])
        self.assertEqual(result['eligible_uses'],1)

    def test_numeric_overflow_is_unavailable_not_json_infinity(self):
        result=regression_signals.summarize([{'data':{'regression':signal(prediction=1e308,target=-1e308)}}],{'manifest':self.report['recipe']})
        self.assertEqual(result['eligible_uses'],1)
        self.assertIsNone(result['mean_squared_error']);self.assertIsNone(result['mean_error'])

    def test_validation_requires_finite_paired_fields_and_actual_recipe(self):
        for change in [{'prediction':True},{'target':float('inf')},{'baseline':None},{'extra':'no'}]:
            with self.subTest(change=change), self.assertRaises(InputError): regression_signals.validate(signal(**change))
        unpaired=signal();del unpaired['reward']
        with self.assertRaises(InputError):regression_signals.validate(unpaired)
        with self.assertRaises(InputError):self.add(record('use',regression=signal()))

    def test_replay_and_late_recipe_keep_original_inputs(self):
        self.add(record('sample',recipe=self.ref))
        use=record('use',recipe=self.ref,regression=signal())
        self.add(use);first=training_health.snapshot(self.store);self.add(use)
        self.assertEqual(first,training_health.snapshot(self.store))
        changed=copy.deepcopy(use);changed['data']['regression']['target']=0
        with self.assertRaises(ReviewConflict):self.add(changed)

    def test_settings_do_not_masquerade_as_grpo_or_clipping(self):
        self.assertEqual(self.report['profile']['weighting'],'regression')
        self.assertEqual(self.report['profile']['credit'],'cached_baseline')
        ids={m['id'] for m in self.report['monitors']}
        self.assertEqual(ids,{'reward','use','cached_baseline','regression'})
        self.assertEqual(training_monitoring.for_context({'manifest':self.report['recipe']})['status'],'ready')
        unknown=request();unknown['version']='unverified'
        self.assertIsNone(training_setup.inspect(unknown)['recipe'])
        with self.assertRaises(InputError):training_setup.inspect({**request(),'trainer':'made-up'})
        downgraded=copy.deepcopy(self.report['recipe']);downgraded['setup']['schema']='training-setup/1'
        with self.assertRaises(InputError):training_recipes.validate({'schema':'training-recipes/1',
            'producer':'worker','experiment':'exp','recipes':[downgraded]})

    def test_dataclass_export_is_allowlisted(self):
        @dataclass
        class Config:
            num_value_samples:int=3
            beta1:float=.5
            beta2:float=.2
            filter_all_incorrect:bool=True
            private_token:str='never export'
        exported=training_setup.prepare('trl',Config(),version='1.13.0',resolved=True,trainer='a2po')
        self.assertNotIn('private_token',exported['config'])
        self.assertEqual(training_setup.inspect(exported)['status'],'ready')

    def test_capture_receipt_opens_its_actual_rollout_revision(self):
        import json
        from types import SimpleNamespace
        from tracker.capture import Outbox
        from tracker.portable import generation_document
        from tracker.trl_a2po_capture import A2POCaptureMixin
        out=Outbox(self.store.path.parent/'outbox.sqlite',producer='worker')
        self.addCleanup(out.close)
        out.log('a',generation_document('task','response',metadata={'experiment':'exp'}),state='complete')
        native_record=A2POCaptureMixin._capture_record(SimpleNamespace(training_outbox=out),
            'sample','a/sample','a',{'split':'train','recipe':self.ref},'Authored source-binding regression control')
        self.add(native_record,record('use',recipe=self.ref,regression=signal()))
        self.assertEqual(training_health.snapshot(self.store)['cohorts'][0]['missing_source'],1)
        with out.connect() as c: packet=json.loads(c.execute('SELECT payload FROM queue').fetchone()[0])
        self.store.ingest(packet)
        cohort=training_health.snapshot(self.store)['cohorts'][0]
        self.assertEqual(cohort['missing_source'],0)
        self.assertIsNotNone(cohort['uses'][0]['points'][0]['records'][0]['sample']['run_id'])


if __name__=='__main__': unittest.main()
