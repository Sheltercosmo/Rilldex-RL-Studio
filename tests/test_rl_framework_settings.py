"""Native config conformance and evidence-bound recommendation regressions."""
import ast
import argparse
import copy
import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
import unittest

from tracker import training_setup as setup, training_monitoring, training_recipes
from tracker.schema import InputError
from test_training_setup import request

SOURCES = Path(__file__).resolve().parents[1] / 'research/rl-method-adaptation-2026-10-12/sources'


def native_definition(path, name, *, constructor=False):
    """Execute only the reviewed pure resolver/constructor, no native imports.

    The loss constructor only sets fields and checks scalar parameters; changing
    its parent to object allows independent comparison without GPU dependencies.
    The original source and SHA256 are retained in source-manifest.json.
    """
    tree = ast.parse((SOURCES / path).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    if constructor:
        node.bases = [ast.Name(id='object', ctx=ast.Load())]
        node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == '__init__']
    scope = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), scope)
    return scope[name]


class FrameworkSettingsTests(unittest.TestCase):
    def test_openrlhf_export_uses_native_cli_field_names_and_defaults(self):
        tree=ast.parse((SOURCES/'openrlhf/openrlhf/cli/train_ppo_ray.py').read_text(encoding='utf-8'))
        parser=argparse.ArgumentParser()
        found=set()
        for node in ast.walk(tree):
            if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                    and node.func.attr=='add_argument' and node.args
                    and isinstance(node.args[0],ast.Constant)):continue
            name=str(node.args[0].value).removeprefix('--')
            if name not in setup.FIELDS['openrlhf']:continue
            found.add(name)
            module=ast.fix_missing_locations(ast.Module(body=[ast.Expr(value=node)],type_ignores=[]))
            exec(compile(module,'native-cli','exec'),{'parser':parser})
        self.assertEqual(found,set(setup.FIELDS['openrlhf']))
        native_args=parser.parse_args([])
        d=setup.inspect(setup.prepare('openrlhf',native_args,version=setup.PINS['openrlhf'],resolved=True))
        self.assertEqual(d['status'],'ready',d['issues'])
        self.assertEqual(d['profile']['credit'],'critic')
        self.assertEqual(d['profile']['scheduling'],'synchronous')
        self.assertNotIn('policy_segments',{m['id'] for m in d['monitors']})

    def test_native_slime_objective_resolver_conformance(self):
        native = native_definition('slime/slime/utils/ppo_utils.py', 'get_pg_loss_type')
        # 48 combinations: alias-selected objective, explicit objective and SC.
        for adv in ['grpo', 'gspo', 'cispo', 'ppo', 'reinforce_plus_plus', 'reinforce_plus_plus_baseline']:
            for loss in [None, 'ppo', 'cispo', 'reinforce']:
                for sc in [False, True]:
                    with self.subTest(adv=adv, loss=loss, sc=sc):
                        p = request('slime'); s = p['config']
                        s.update(advantage_estimator=adv, pg_loss_type=loss, use_score_centering=sc,
                                 use_rollout_logprobs=False, normalize_advantages=True)
                        try: expected = native(SimpleNamespace(**s))
                        except ValueError:
                            self.assertEqual(setup.inspect(p)['status'], 'needs_review'); continue
                        # Native validation rejects SC with the GSPO/CISPO
                        # estimator even where the pure resolver can choose a loss.
                        if sc and adv in {'gspo', 'cispo'}: continue
                        report = setup.inspect(p)
                        self.assertEqual(report['status'], 'ready', report['issues'])
                        self.assertEqual(report['recipe']['components'][0]['objective']['definition'], 'slime/' + expected)

    def test_native_openrlhf_ratio_and_reduction_conformance(self):
        native = native_definition('openrlhf/openrlhf/models/loss.py', 'PolicyLoss', constructor=True)
        for loss in ['ppo', 'gspo']:
            for token in [False, True]:
                for level, mode, gate in [('off','mask','ratio'), ('token','clip','ratio'),
                        ('token','mask','ratio'), ('seq','mask','binary_kl')]:
                    with self.subTest(loss=loss, token=token, level=level, mode=mode):
                        p=request('openrlhf'); s=p['config']
                        s['actor'].update(policy_loss_type=loss, loss_agg_mode='token-mean' if token else 'seq-mean-token-mean')
                        s['algo']['advantage'].update(is_correction_level=level, is_correction_mode=mode,
                            is_correction_gating=gate, is_correction_threshold=[0.,2.])
                        result=native(token_level_loss=token, policy_loss_type=loss, is_correction_level=level,
                            is_correction_mode=mode, is_correction_gating=gate, is_correction_threshold=[0.,2.])
                        d=setup.inspect(p); self.assertEqual(d['status'],'ready',d['issues'])
                        self.assertEqual(d['profile']['reduction'], 'token-mean' if result.token_level_loss else 'seq-mean-token-mean')
                        ids={m['id'] for m in d['monitors']}
                        self.assertEqual('selection' in ids, loss=='ppo' and level!='off' and mode=='mask')

    def test_credit_modes_do_not_follow_objective_acronym(self):
        for adv, credit in [('gae','critic'), ('reinforce','return'), ('flash_reinforce','return'),
                           ('reinforce_baseline','group_relative'), ('rloo','group_relative'),
                           ('group_norm','group_relative'), ('dr_grpo','group_relative')]:
            p=request('openrlhf');p['config']['algo']['advantage']['estimator']=adv
            p['config']['rollout']['n_samples_per_prompt']=2
            d=setup.inspect(p);self.assertEqual(d['profile']['credit'],credit)
            self.assertEqual(d['profile']['credit_unit'],'token')
        p=request('openrlhf');d=setup.inspect(p);ids={m['id'] for m in d['monitors']}
        self.assertIn('batch_baseline',ids);self.assertNotIn('group_contrast',ids)
        for adv in ('grpo','gspo','cispo','reinforce_plus_plus_baseline'):
            for normalized in (False,True):
                p=request('slime');p['config'].update(advantage_estimator=adv, pg_loss_type=None,
                    use_score_centering=False, rewards_normalization=normalized, use_rollout_logprobs=False,
                    normalize_advantages=True)
                d=setup.inspect(p);self.assertEqual(d['status'],'ready',d['issues'])
                self.assertEqual(d['profile']['credit'],'group_relative' if normalized else 'return')

    def test_native_incompatible_combinations_do_not_publish(self):
        cases=[]
        for level,mode,gate,bounds in [('seq','clip','ratio',[0.,2.]), ('token','clip','binary_kl',[0.,2.]),
                                     ('seq','mask','binary_kl',[.5,2.]), ('token','mask','ratio',[2.,1.])]:
            p=request('openrlhf');p['config']['algo']['advantage'].update(is_correction_level=level,
                is_correction_mode=mode,is_correction_gating=gate,is_correction_threshold=bounds);cases.append(p)
        p=request('openrlhf');p['config']['train']['async_enable']=False;cases.append(p)
        p=request('openrlhf');p['config']['algo']['advantage']['estimator']='rloo';cases.append(p)
        for delta in ({'use_score_centering':False,'pg_loss_type':'ppo'}, {'train_backend':'fsdp'},
                      {'use_opsm':True}, {'use_opd':True}, {'tis_clip_low':3.0},
                      {'custom_pg_loss_reducer_function_path':'custom.reduce'},
                      {'custom_advantage_function_path':'custom.credit'},
                      {'custom_tis_function_path':'custom.weights'}):
            p=request('slime');p['config'].update(delta);cases.append(p)
        for p in cases:
            with self.subTest(config=p['config']):
                d=setup.inspect(p);self.assertIsNone(d['recipe']);self.assertEqual(d['monitoring_plan']['status'],'needs_review')

    def test_flat_nested_and_native_namespace_exports_agree_and_omit_secrets(self):
        p=request('openrlhf');expected=setup.inspect(p)
        flat=setup.selected_settings('openrlhf',p['config'])
        flat['credentials.api_key']='must-not-export'
        native=Namespace(**flat)
        nested=SimpleNamespace(**{k:SimpleNamespace(**v) for k,v in p['config'].items()})
        nested.algo.advantage=SimpleNamespace(**p['config']['algo']['advantage'])
        for cfg in (flat,native,nested):
            clean=setup.prepare('openrlhf',cfg,version=p['version'],resolved=True)
            self.assertNotIn('must-not-export',json.dumps(clean))
            self.assertEqual(setup.inspect(clean),expected)
        auto=copy.deepcopy(p);auto['config']=flat;auto['framework']='auto'
        self.assertEqual(setup.inspect(auto),expected)
        bad=copy.deepcopy(p);bad['config']['actor.policy_loss_type']='gspo'
        with self.assertRaises(InputError):setup.inspect(bad)

    def test_configuration_guards_unknown_versions_and_custom_hooks(self):
        for framework in ('slime','openrlhf'):
            p=request(framework);p['version']='unverified-release'
            self.assertIsNone(setup.inspect(p)['recipe'])
            p=request(framework);p['resolved']=False
            self.assertIsNone(setup.inspect(p)['recipe'])
        p=request('slime');p['config'].pop('custom_advantage_function_path')
        self.assertIsNone(setup.inspect(p)['recipe'])
        p=request('openrlhf');p['config']['train']['async_enable']='false'
        self.assertIsNone(setup.inspect(p)['recipe'])
        for bad in [[float('nan'),2.],[False,2.],['0',2.]]:
            p=request('openrlhf');p['config']['algo']['advantage']['is_correction_threshold']=bad
            with self.assertRaises(InputError):setup.inspect(p)

    def test_sampling_server_presence_does_not_export_url_or_credentials(self):
        p=request('slime');p['config']['rollout_logprob_server_url']='https://private.invalid/?key=must-not-export'
        clean=setup.prepare('slime',p['config'],version=p['version'],resolved=True)
        self.assertIs(clean['config']['rollout_logprob_server_url'],True)
        report=setup.inspect(clean)
        self.assertNotIn('must-not-export',json.dumps(report))
        self.assertIsNone(report['recipe'])

    def test_recommendations_are_context_bound_and_do_not_rewrite_recipe(self):
        p=request('openrlhf');report=setup.inspect(p)
        recipe=report['recipe'];original=copy.deepcopy(recipe)
        recipe['producer']='test';context={'manifest':recipe}
        before=copy.deepcopy(context);plan=training_monitoring.for_context(context)
        self.assertEqual(before,context)
        self.assertEqual([g['id'] for g in plan['groups']],['outcomes','selection','credit','updates','freshness'])
        self.assertEqual(len(plan['time_axes']),3)
        self.assertIsNone(training_monitoring.for_context({'manifest':None}))
        context['manifest']['setup']['version']='unknown'
        self.assertEqual(training_monitoring.for_context(context)['status'],'needs_review')
        packet={'schema':training_recipes.VERSION,'producer':'p','experiment':'e','recipes':[original]}
        training_recipes.validate(packet)

    def test_unclipped_return_methods_keep_credit_and_update_questions(self):
        p=request('slime');p['config'].update(use_score_centering=False,
            advantage_estimator='reinforce_plus_plus',normalize_advantages=True)
        d=setup.inspect(p);self.assertEqual(d['status'],'ready',d['issues'])
        ids={m['id'] for m in d['monitors']}
        self.assertTrue({'return_credit','unclipped_update'} <= ids)
        self.assertFalse({'group_contrast','objective_exposure'} & ids)

    def test_pinned_source_hashes(self):
        import hashlib
        manifest=json.loads((SOURCES.parent/'source-manifest.json').read_text(encoding='utf-8'))
        for row in manifest:
            self.assertEqual(hashlib.sha256((SOURCES/row['framework']/row['path']).read_bytes()).hexdigest(),row['sha256'])


if __name__ == '__main__': unittest.main()
