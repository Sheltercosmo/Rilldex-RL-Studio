import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker import value_observations as values
from tracker import training_setup, training_recipes, training_lineage, training_health
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict
from test_training_health import record
from test_training_setup import request


def signal(**change):
    return dict(schema=values.VERSION, component='rl-policy', definition='authored-return/1',
        unit='token', role='value_fit', target_kind='lambda_return', value_model='critic',
        value_version='critic-update-7', input_digest='authored-input', positions=[0, 1, 2],
        mask=[1, 1, 0], values=[0., 2., 999.], returns=[0., 1., -999.], **{}) | change


def receipts(*signals):
    return [{'data': {} if s is None else {'value_observation': s}} for s in signals]


def context(framework='verl'):
    p = request(framework)
    if framework == 'openrlhf': p['config']['algo']['advantage']['estimator'] = 'gae'
    if framework == 'slime':
        p['config'].update(advantage_estimator='ppo', pg_loss_type='ppo', use_score_centering=False,
                           use_rollout_logprobs=False, use_tis=False)
    if framework == 'areal':
        p['config']['critic'] = {}
        p['config']['actor']['gae_timestep_unit'] = 'turn'
    report = training_setup.inspect(p)
    assert report['status'] == 'ready', report['issues']
    return {'manifest':report['recipe']}


class ValueTests(unittest.TestCase):
    def test_masked_moments_are_position_weighted(self):
        r = values.summarize(receipts(signal(), signal(positions=[0], mask=[1], values=[3.], returns=[3.])), context())
        self.assertEqual(r['eligible_positions'], 3)
        self.assertEqual(r['recorded_positions'], 4)
        self.assertAlmostEqual(r['mean_squared_error'], 1/3)
        self.assertAlmostEqual(r['mean_error'], 1/3)
        self.assertAlmostEqual(r['explained_variance'], 6/7)
        self.assertAlmostEqual(r['within_sample_variation_fraction'], 3/7)

    def test_constant_bias_is_visible_even_with_perfect_explained_variance(self):
        r = values.summarize(receipts(signal(values=[10., 11., 0.], returns=[0., 1., 0.])), context())
        self.assertEqual(r['explained_variance'], 1)
        self.assertEqual(r['mean_squared_error'], 100)
        self.assertEqual(r['mean_error'], 10)

    def test_negative_variance_is_not_clamped(self):
        r = values.summarize(receipts(signal(values=[1., 0., 0.])), context())
        self.assertEqual(r['explained_variance'], -3)

    def test_empty_singleton_and_constant_target_are_not_success(self):
        for s in [signal(mask=[0, 0, 0]), signal(mask=[1, 0, 0]), signal(returns=[1., 1., 0.])]:
            r = values.summarize(receipts(s), context())
            self.assertIsNone(r['explained_variance'])
        r = values.summarize(receipts(signal(mask=[0, 0, 0]), None), context())
        self.assertEqual(r['masked_out_uses'], 1)
        self.assertEqual(r['missing_uses'], 1)
        self.assertIsNone(r['mean_squared_error'])

    def test_flat_values_with_different_sample_means_have_zero_within_share(self):
        r = values.summarize(receipts(signal(values=[0., 0., 0.]), signal(values=[2., 2., 2.])), context())
        self.assertEqual(r['within_sample_variation_fraction'], 0)
        self.assertEqual(r['eligible_uses'], 2)
        r = values.summarize(receipts(signal(values=[2., 2., 2.])), context())
        self.assertIsNone(r['within_sample_variation_fraction'])
        self.assertEqual(r['variation_status'], 'constant_values')

    def test_different_roles_units_models_and_definitions_form_separate_series(self):
        for key, change in [('role', 'advantage_baseline'), ('unit', 'turn'),
                            ('value_model', 'other-critic'), ('definition', 'new/1'), ('target_kind', 'custom')]:
            with self.subTest(key=key):
                r = values.summarize(receipts(signal(), signal(**{key:change})), context())
                self.assertFalse(r['compatible_definitions'])
                self.assertIsNone(r['mean_squared_error'])
                self.assertEqual(len(r['series']), 2)
                self.assertTrue(all(s['eligible_positions'] == 2 for s in r['series']))

    def test_versions_and_input_digests_can_change_without_redefining_a_series(self):
        r = values.summarize(receipts(signal(), signal(value_version='next', input_digest='next')), context())
        self.assertEqual(len(r['series']), 1)
        self.assertEqual(r['eligible_positions'], 4)

    def test_five_frameworks_share_observation_contract_without_loss_assumptions(self):
        for framework in ['verl', 'areal', 'nemo_rl', 'openrlhf', 'slime']:
            with self.subTest(framework=framework):
                ctx=context(framework)
                r=values.summarize(receipts(signal()),ctx)
                self.assertEqual(r['mean_squared_error'], .5)
                c=next(c for c in training_recipes.capabilities(ctx,uses=receipts(signal())) if c['id']=='critic_credit')
                self.assertEqual(c['state'],'captured')

    def test_missing_recipe_or_noncritic_never_borrows_generation_settings(self):
        for ctx in [{'manifest':None},context('trl')]:
            r=values.summarize(receipts(signal()),ctx)
            self.assertEqual(r['unbound_uses'],1)
            self.assertEqual(r['series'],[])
            self.assertIsNone(r['mean_squared_error'])

    def test_validation_rejects_misalignment_and_unsupported_semantics(self):
        for change in [{'positions':[1,1,2]}, {'positions':[2,1,3]}, {'positions':[True,1,2]},
                       {'positions':[]}, {'mask':[1,0]}, {'mask':[1,True,0]}, {'values':[1.,2.]},
                       {'values':[float('nan'),0.,0.]}, {'returns':[False,0.,0.]},
                       {'role':'critic_accuracy'}, {'target_kind':'unknown'}, {'unit':'vocabulary'},
                       {'value_version':''}, {'unrecognized':0}]:
            with self.subTest(change=change),self.assertRaises(InputError):
                values.validate(signal(**change))

    def test_numeric_range_is_json_safe(self):
        r=values.summarize(receipts(signal(values=[1e308,-1e308,0.],returns=[-1e308,1e308,0.])),context())
        self.assertIsNone(r['mean_squared_error'])
        self.assertIsNone(r['explained_variance'])
        json.dumps(r,allow_nan=False)

    def test_builder_copies_native_arrays_without_mutation(self):
        s=signal();kwargs={k:v for k,v in s.items() if k!='schema'}
        built=values.observation(**kwargs);built['values'][0]=100.
        self.assertEqual(s['values'][0],0.)


class ValueRoundtripTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'values.sqlite')
        self.recipe=context()['manifest']
        self.ref={'producer':'worker','id':self.recipe['id'],'revision':0}

    def add(self,*rows):
        return training_lineage.receive(self.store,{'schema':'training-records/1','producer':'worker','experiment':'exp','records':list(rows)})

    def declare(self):
        training_recipes.receive(self.store,{'schema':'training-recipes/1','producer':'worker','experiment':'exp','recipes':[self.recipe]})

    def test_late_recipe_idempotence_and_conflicting_replay(self):
        self.add(record('sample',recipe=self.ref))
        r=record('use',recipe=self.ref,value_observation=signal())
        self.add(r)
        self.assertEqual(training_health.snapshot(self.store)['cohorts'][0]['uses'][0]['value_observation']['unbound_uses'],1)
        self.declare();first=training_health.snapshot(self.store);self.add(r)
        self.assertEqual(first,training_health.snapshot(self.store))
        self.assertEqual(first['cohorts'][0]['dashboard']['default']['label'],'Value predictions and returns')
        changed=copy.deepcopy(r);changed['data']['value_observation']['values'][0]=2
        with self.assertRaises(ReviewConflict):self.add(changed)

    def test_actor_mask_differs_from_value_mask_without_overwriting_either(self):
        self.declare();self.add(record('sample',recipe=self.ref), record('use',recipe=self.ref,
            loss_tokens=0,model_tokens=10,value_observation=signal()))
        u=training_health.snapshot(self.store)['cohorts'][0]['uses'][0]
        self.assertEqual(u['value_observation']['eligible_positions'],2)
        self.assertEqual(u['positive_mask']['numerator'],0)
        self.assertEqual(u['points'][0]['records'][0]['data']['value_observation'],signal())

    def test_stage_step_role_and_repeated_use_stay_separate(self):
        self.declare();self.add(record('sample',recipe=self.ref))
        for ident,step,stage,role in [('a',1,'backward_completed','value_fit'),('b',2,'backward_completed','value_fit'),
            ('c',2,'backward_completed','advantage_baseline'),('d',2,'optimizer_step_completed','value_fit')]:
            self.add(record('use',identifier=ident,learner_step=step,stage=stage,recipe=self.ref,value_observation=signal(role=role)))
        c=training_health.snapshot(self.store)['cohorts'][0]
        self.assertEqual(len(c['uses']),2)
        b=next(u for u in c['uses'] if u['stage']=='backward_completed')
        self.assertEqual([p['step'] for p in b['points']],[1,2])
        self.assertEqual(len(b['value_observation']['series']),2)
        self.assertEqual(sorted(s['eligible_uses'] for s in b['value_observation']['series']),[1,2])

    def test_recipe_required_without_fabricated_value_capture(self):
        with self.assertRaises(InputError):self.add(record('use',value_observation=signal()))
        self.declare();self.add(record('sample',recipe=self.ref),record('use',recipe=self.ref))
        u=training_health.snapshot(self.store)['cohorts'][0]['uses'][0]
        self.assertEqual(u['value_observation']['observed_uses'],0)
        self.assertEqual(next(c for c in u['capabilities'] if c['id']=='critic_credit')['state'],'missing')


if __name__=='__main__':unittest.main()
