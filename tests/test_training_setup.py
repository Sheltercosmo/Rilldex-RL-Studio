import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tracker.training_setup import inspect, record, prepare, PINS
from tracker.schema import InputError
from tracker.capture import Outbox
from tracker import training_recipes, training_lineage, training_health
from tracker.store import Store
from tracker.trl_lineage import GRPOTrainingLineageMixin


def request(framework='trl', **settings):
    cfg = {'loss_type':'dapo', 'importance_sampling_level':'token', 'scale_rewards':'group',
           'multi_objective_aggregation':'sum_then_normalize', 'num_generations':8}
    if framework == 'verl':
        cfg = {'algorithm':{'adv_estimator':'gae'}, 'actor_rollout_ref':{'actor':{
            'policy_loss':{'loss_mode':'vanilla'}, 'loss_agg_mode':'token-mean'}}}
    elif framework == 'areal':
        cfg = {'actor':{'use_sapo_loss':False, 'use_cispo_loss':False, 'use_decoupled_loss':False,
              'importance_sampling_level':'sequence','reward_norm':{'mean_level':'group'}},
              'gconfig':{'n_samples':8}, 'critic':None}
    elif framework == 'nemo_rl':
        cfg = {'ppo':{'adv_estimator':{'name':'gae'}}, 'loss_fn':{
            'disable_ppo_ratio':False, 'force_on_policy_ratio':False, 'use_cispo':False,
            'sequence_level_importance_ratios':False, 'token_level_loss':True}}
    elif framework in {'openrlhf', 'slime'}:
        from tracker.rl_framework_settings import examples
        cfg = copy.deepcopy(next(row[3] for row in examples() if row[2] == framework))
    elif framework == 'verl_agent':
        from tracker.gigpo_setup import examples
        cfg = copy.deepcopy(examples()[0][3])
    cfg.update(settings)
    return {'framework':framework, 'version':PINS[framework], 'resolved':True, 'config':cfg}


class SetupTests(unittest.TestCase):
    def test_trl_objectives_do_not_conflate_clipping_capping_smoothing(self):
        expected = {'dapo':'hard_gate','grpo':'hard_gate','bnpo':'hard_gate','dr_grpo':'hard_gate',
                    'cispo':'capped','sapo':'smooth','vespo':'smooth','luspo':'hard_gate'}
        for loss, weighting in expected.items():
            with self.subTest(loss=loss):
                result = inspect(request(loss_type=loss, importance_sampling_level='sequence' if loss=='luspo' else 'token'))
                self.assertEqual(result['status'],'ready')
                self.assertEqual(result['profile']['weighting'],weighting)
                self.assertFalse(result['recipe']['components_complete'])
                self.assertEqual(result['recipe']['setup']['settings'], result['settings'])
                training_recipes.validate({'schema':'training-recipes/1','producer':'p','experiment':'e','recipes':[result['recipe']]})
        self.assertNotEqual(inspect(request(loss_type='dapo'))['profile']['reduction'], inspect(request(loss_type='grpo'))['profile']['reduction'])

    def test_verl_estimator_independent_of_loss_and_reduction(self):
        p=request('verl'); critic=inspect(p)
        self.assertEqual(critic['profile']['credit'],'critic')
        self.assertIn('critic_credit',[m['id'] for m in critic['monitors']])
        self.assertNotIn('group_contrast',[m['id'] for m in critic['monitors']])
        p['config']['algorithm']['adv_estimator']='rloo'
        p['config']['actor_rollout_ref']['actor']['policy_loss']['loss_mode']='gspo'
        group=inspect(p)
        self.assertEqual(group['profile']['credit'],'group_relative')
        self.assertEqual(group['profile']['ratio_unit'],'sequence')
        self.assertNotEqual(group['settings_digest'],critic['settings_digest'])

    def test_areal_orthogonal_modifiers_and_critic(self):
        p=request('areal'); a=p['config']['actor'];a['use_decoupled_loss']=True;a['rejection_sampling']={'metric':'ratio'};a['m2_threshold']=2
        d=inspect(p); ids=[m['id'] for m in d['monitors']]
        self.assertEqual(d['profile']['credit'],'group_relative')
        for identifier in ['sequence_ratio','policy_mismatch','selection','moment_constraint']: self.assertIn(identifier,ids)
        p['config']['critic']={'model':{'path':'must-not-leak'}};a['gae_timestep_unit']='turn'
        d=inspect(p);self.assertEqual(d['profile']['credit'],'critic');self.assertEqual(d['profile']['credit_unit'],'turn')
        self.assertNotIn('must-not-leak',json.dumps(d))

    def test_reject_incompatible_combinations(self):
        self.assertIsNone(inspect(request(loss_type='luspo'))['recipe'])
        p=request('areal');a=p['config']['actor'];a['use_sapo_loss']=True;a['use_decoupled_loss']=True
        self.assertIn('incompatible',[x['code'] for x in inspect(p)['issues']])
        a['use_decoupled_loss']=False;a['use_cispo_loss']=True
        self.assertIsNone(inspect(p)['recipe'])
        a['use_sapo_loss']=False;a['importance_sampling_level']='token';a['eps_clip_higher']=4
        self.assertEqual(inspect(p)['status'],'ready')
        a['eps_clip_higher']=0
        self.assertIsNone(inspect(p)['recipe'])
        a['use_cispo_loss']=False;a['use_sapo_loss']=True;a['sapo_tau_pos']=1;a['sapo_tau_neg']=1.05
        before=inspect(p);self.assertEqual(before['status'],'ready')
        a['sapo_tau_neg']=1.1
        self.assertNotEqual(before['settings_digest'],inspect(p)['settings_digest'])

    def test_unknown_missing_unresolved_and_version_do_not_become_grpo(self):
        cases=[]
        p=request(loss_type='future-loss');cases.append(p)
        p=request();p['config'].pop('loss_type');cases.append(p)
        p=request();p['version']='future';cases.append(p)
        p=request();p['resolved']=False;cases.append(p)
        p=request(num_generations='${group_size}');cases.append(p)
        for p in cases:
            self.assertEqual(inspect(p)['status'],'needs_review');self.assertIsNone(inspect(p)['recipe'])
        p=request('areal');p['config'].pop('critic');self.assertEqual(inspect(p)['profile']['credit'],'unknown')

    def test_auto_detection_and_allowlist(self):
        for framework in PINS:
            p=request(framework);p['framework']='auto';p['config']['api_key']='secret-test'
            d=inspect(p);self.assertEqual(d['framework'],framework);self.assertNotIn('secret-test',json.dumps(d))
        p=request();p['config']['actor_rollout_ref']={};p['framework']='auto'
        with self.assertRaises(InputError):inspect(p)
        for value in [float('inf'),{},['wrong'],True]:
            if value is True:continue
            with self.assertRaises(InputError):inspect(request(epsilon=value))

    def test_safe_export_preserves_interpretation_without_secrets(self):
        for framework in PINS:
            p=request(framework);p['config']['api_key']='secret-test'
            clean=prepare(framework,p['config'],version=p['version'],resolved=True)
            self.assertNotIn('secret-test',json.dumps(clean))
            self.assertEqual(inspect(p),inspect(clean))
        self.assertIsNone(inspect(request(use_vllm='false'))['recipe'])
        with self.assertRaises(InputError):inspect({'framework':[], 'config':{}})

    def test_setting_change_is_immutable_and_same_setting_replays(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox=Outbox(Path(tmp)/'out.sqlite',producer='p')
            first=record(outbox,'exp',request());repeat=record(outbox,'exp',request())
            changed=record(outbox,'exp',request(scale_rewards='none'))
            self.assertEqual(first,repeat);self.assertNotEqual(first,changed)
            store=Store(Path(tmp)/'db.sqlite')
            with outbox.connect() as c:packets=[json.loads(r[0]) for r in c.execute('SELECT payload FROM queue')]
            for p in packets:training_recipes.receive(store,p['training_recipes'])
            self.assertEqual(len(training_recipes.snapshot(store)['recipes']),2)

    def test_runtime_values_override_stale_argument_copies_and_deduplicate(self):
        rows=[];t=object.__new__(GRPOTrainingLineageMixin)
        t.args=SimpleNamespace(**request()['config']);t.loss_type='cispo';t._jev_setup_ids=set()
        t.training_capture=SimpleNamespace(experiment='exp',outbox=SimpleNamespace(producer='p',log_recipes=lambda exp,rs:rows.extend(rs)))
        first=t._jev_setup();self.assertEqual(t._jev_setup(),first);self.assertEqual(len(rows),1)
        t.loss_type='sapo';self.assertNotEqual(t._jev_setup(),first);self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['components'][0]['objective']['weighting'],'capped')
        self.assertEqual(rows[1]['components'][0]['objective']['weighting'],'smooth')
        t.args.epsilon=0.8;t.epsilon_low=0.1;t._jev_setup()
        self.assertEqual(rows[-1]['setup']['settings']['epsilon'],0.1)

    def test_native_setup_reaches_health_without_manual_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Outbox(Path(tmp)/'out.sqlite',producer='p');ref=record(out,'exp',request(loss_type='cispo'))
            store=Store(Path(tmp)/'db.sqlite')
            with out.connect() as c:packet=json.loads(c.execute('SELECT payload FROM queue').fetchone()[0])
            training_recipes.receive(store,packet['training_recipes'])
            training_lineage.receive(store,{'schema':'training-records/2','producer':'p','experiment':'exp','records':[
                {'id':'s','revision':0,'kind':'sample','sample':{'producer':'p','id':'s'},'evidence':{'basis':'authored control'},
                 'data':{'split':'train','recipe':ref,'step':0,'step_basis':'generation'}}]})
            c=training_health.snapshot(store)['cohorts'][0]
            self.assertEqual(c['recipe_context']['status'],'recorded')
            self.assertEqual(c['recipe_context']['manifest']['label'],'CISPO')
            self.assertEqual(next(x for x in c['capabilities'] if x['id']=='objective_exposure')['state'],'unsupported')


if __name__=='__main__':unittest.main()
