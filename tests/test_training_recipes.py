import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker.capture import Outbox
from tracker.schema import InputError, digest
from tracker.store import Store, ReviewConflict
from tracker import training_recipes as recipes, training_lineage as lineage, training_health as health


def component(name='reward', supervision='reward', credit='group_relative', unit='sample', weighting='hard_gate'):
    return {'id':name,'label':name,'supervision':supervision,'credit':{'kind':credit,'unit':unit},
            'objective':{'definition':'authored objective/1','unit':'token','weighting':weighting,'reduction':'token mean'}}


def manifest(identifier='recipe', revision=0, components=None, complete=True):
    return {'id':identifier,'revision':revision,'label':identifier,'implementation':{'name':'authored controls','revision':'1'},
            'config_digest':'sha256:authored-control-not-native','basis':'authored conformance case, not a training execution',
            'components_complete':complete,'components':components or [component()],
            'context':{'phase':'authored-test','scheduling':'asynchronous'}}


def packet(*values, experiment='exp', producer='trainer'):
    return {'schema':recipes.VERSION,'producer':producer,'experiment':experiment,'recipes':list(values)}


def ref(identifier='recipe', revision=0):
    return {'producer':'trainer','id':identifier,'revision':revision}


def record(kind, sample='a', **data):
    defaults={'sample':{'split':'train','group_id':'g','group_size':2,'step':1,'step_basis':'generation'},
              'score':{'component':'environment','definition':'authored/1','status':'scored','value':0},
              'use':{'batch_id':'b','learner_step':3,'stage':'backward_completed','loss_tokens':2,'model_tokens':3}}
    return {'id':kind+'/'+sample,'revision':0,'kind':kind,'sample':{'producer':'worker','rollout_id':sample},
            'evidence':{'basis':'authored control'},'data':defaults[kind]|data}


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'tracker.sqlite')

    def add(self,*rows,experiment='exp'):
        return lineage.receive(self.store,{'schema':lineage.VERSION,'producer':'worker','experiment':experiment,'records':list(rows)})

    def cohort(self):return health.snapshot(self.store)['cohorts'][0]
    def cap(self,value,name):return next(c for c in value['capabilities'] if c['id']==name)

    def test_identity_replay_conflict_and_atomic_packet(self):
        p=packet(manifest());self.assertEqual(recipes.receive(self.store,p)['inserted'],1)
        self.assertEqual(recipes.receive(self.store,p)['inserted'],0)
        changed=manifest();changed['label']='different'
        with self.assertRaises(ReviewConflict):recipes.receive(self.store,packet(manifest('new'),changed))
        self.assertEqual(len(recipes.snapshot(self.store)['recipes']),1)

    def test_late_delivery_changes_snapshot_but_never_substitutes_newer_revision(self):
        self.add(record('sample',recipe=ref()))
        before=health.snapshot(self.store)
        self.assertEqual(before['cohorts'][0]['recipe_context']['status'],'not_delivered')
        recipes.receive(self.store,packet(manifest(revision=2)))
        self.assertEqual(self.cohort()['recipe_context']['status'],'not_delivered')
        recipes.receive(self.store,packet(manifest()))
        after=health.snapshot(self.store)
        self.assertNotEqual(before['revision'],after['revision'])
        self.assertNotEqual(before['snapshot_id'],after['snapshot_id'])
        self.assertEqual(after['cohorts'][0]['recipe_context']['manifest']['revision'],0)
        self.assertEqual(before['cohorts'][0]['recipe_context']['status'],'not_delivered')

    def test_experiment_and_producer_scope_do_not_cross(self):
        self.add(record('sample',recipe=ref()))
        recipes.receive(self.store,packet(manifest(),experiment='other'))
        recipes.receive(self.store,packet(manifest(),producer='other'))
        self.assertEqual(self.cohort()['recipe_context']['status'],'not_delivered')
        self.assertEqual(lineage.snapshot(self.store)['recipes'],[])

    def test_teacher_only_zero_rewards_are_not_group_credit_failure(self):
        recipes.receive(self.store,packet(manifest(components=[component('opd','teacher','token_distribution','vocabulary','none')])))
        for s in ['a','b']:self.add(record('sample',s,recipe=ref()),record('score',s),record('use',s,recipe=ref()))
        c=self.cohort()
        self.assertEqual(c['rewards'][0]['constant_groups']['value'],1)
        self.assertEqual(self.cap(c,'group_contrast')['state'],'not_applicable')
        u=c['uses'][0]
        self.assertEqual(self.cap(u,'scalar_credit')['state'],'not_applicable')
        self.assertEqual(self.cap(u,'teacher_signal')['applicability'],'applicable')
        self.assertEqual(self.cap(u,'teacher_signal')['state'],'unsupported')
        self.assertEqual(u['positive_mask']['value'],1)

    def test_single_rollout_critic_requires_critic_evidence(self):
        recipes.receive(self.store,packet(manifest(components=[component(credit='critic',unit='token')])))
        self.add(record('sample',group_size=1,recipe=ref()),record('use',recipe=ref()))
        c=self.cohort()
        self.assertEqual(self.cap(c,'group_contrast')['state'],'not_applicable')
        self.assertEqual(self.cap(c['uses'][0],'scalar_credit')['state'],'not_applicable')
        self.assertEqual(self.cap(c['uses'][0],'critic_credit')['state'],'missing')

    def test_hybrid_components_remain_distinct(self):
        recipes.receive(self.store,packet(manifest(components=[component(),component('opd','teacher','token_distribution','vocabulary','none')])))
        for s in ['a','b']:self.add(record('sample',s,recipe=ref()),record('score',s),record('use',s,recipe=ref(),advantage=1))
        c=self.cohort();u=c['uses'][0]
        self.assertEqual(self.cap(c,'group_contrast')['state'],'captured')
        self.assertEqual(self.cap(u,'scalar_credit')['state'],'captured')
        self.assertEqual(self.cap(u,'teacher_signal')['state'],'unsupported')
        self.assertEqual(len(u['recipe_context']['manifest']['components']),2)

    def test_group_credit_needs_complete_evidence(self):
        recipes.receive(self.store,packet(manifest()))
        self.add(record('sample',recipe=ref()),record('score'))
        self.assertEqual(self.cap(self.cohort(),'group_contrast')['state'],'missing')
        self.add(record('sample','b',recipe=ref()),record('score','b'))
        self.assertEqual(self.cap(self.cohort(),'group_contrast')['state'],'captured')

    def test_partial_declaration_cannot_establish_absence(self):
        recipes.receive(self.store,packet(manifest(complete=False)))
        self.add(record('sample',recipe=ref()))
        c=self.cohort()
        self.assertEqual(self.cap(c,'group_contrast')['applicability'],'applicable')
        self.assertEqual(self.cap(c,'teacher_signal')['state'],'unknown')

    def test_custom_semantics_are_retained_without_unsupported_inference(self):
        recipes.receive(self.store,packet(manifest(components=[component('custom','vendor/signal','vendor/credit','vendor/unit','vendor/gate')])))
        self.add(record('sample',recipe=ref()))
        self.assertTrue(all(c['state']=='unknown' for c in self.cohort()['capabilities']))

    def test_use_recipe_never_inherits_generation_recipe(self):
        recipes.receive(self.store,packet(manifest()))
        self.add(record('sample',recipe=ref()),record('use',advantage=1))
        u=self.cohort()['uses'][0]
        self.assertEqual(u['recipe_context']['status'],'not_recorded')
        self.assertEqual(self.cap(u,'scalar_credit')['state'],'unknown')

    def test_generation_cohorts_split_recipe_and_legacy(self):
        self.add(record('sample','legacy'),record('sample','first',recipe=ref()),record('sample','second',recipe=ref(revision=1)))
        p=lineage.snapshot(self.store);h=health.snapshot(self.store)
        self.assertEqual(len(p['cohorts']),3)
        self.assertEqual([c['samples'] for c in h['cohorts']],[1,1,1])
        self.assertEqual(sum(c['counts']['generated'] for c in p['cohorts']),3)

    def test_reused_sample_splits_use_recipes_without_changing_generation(self):
        self.add(record('sample',recipe=ref()))
        for n in range(2):
            r=record('use',recipe=ref(revision=n));r['id']='use/'+str(n);self.add(r)
        c=self.cohort()
        self.assertEqual(c['samples'],1);self.assertEqual(len(c['uses']),2)
        self.assertEqual(len({u['id'] for u in c['uses']}),2)
        self.assertEqual([u['receipts'] for u in c['uses']],[1,1])

    def test_weighting_definitions_remain_native(self):
        for n,weight in enumerate(['capped','hard_gate','smooth']):
            recipes.receive(self.store,packet(manifest(revision=n,components=[component(weighting=weight)])))
        self.assertEqual([r['components'][0]['objective']['weighting'] for r in recipes.snapshot(self.store)['recipes']],['capped','hard_gate','smooth'])

    def test_invalid_reference_rejected_before_lineage_persistence(self):
        for bad in [None,{},ref(revision=True),ref(revision=-1),ref(revision=2**63),ref()|{'extra':'x'}]:
            with self.assertRaises(InputError):self.add(record('sample',recipe=bad))
        self.assertEqual(lineage.snapshot(self.store)['samples'],[])

    def test_invalid_manifests_rejected_before_persistence(self):
        for key,value in [('components_complete','true'),('components',[]),('implementation',{'name':'x'}),('revision',True),('context',{'unknown':'x'})]:
            m=manifest();m[key]=value
            with self.assertRaises(InputError):recipes.receive(self.store,packet(m))
        m=manifest();m['components']*=2
        with self.assertRaises(InputError):recipes.receive(self.store,packet(m))
        self.assertEqual(recipes.snapshot(self.store)['recipes'],[])

    def test_version_two_samples_and_use_references(self):
        rows=[record('sample',recipe=ref()),record('use',recipe=ref())]
        for r in rows:r['sample']={'producer':'worker','id':'sample'}
        lineage.receive(self.store,{'schema':'training-records/2','producer':'worker','experiment':'exp','records':rows})
        self.assertEqual(self.cohort()['uses'][0]['recipe_context']['reference'],ref())

    def test_outbox_restart_lost_ack_and_wrong_ack(self):
        path=Path(self.tmp.name)/'outbox.sqlite';out=Outbox(path,producer='trainer')
        first=out.log_recipes('exp',[manifest()]);self.assertTrue(out.log_recipes('exp',[manifest()])['duplicate'])
        def send(request,**kwargs):
            self.assertTrue(request.full_url.endswith('/api/training-recipes'))
            result=recipes.receive(self.store,json.loads(request.data))
            return io.BytesIO(json.dumps(result).encode())
        def lost(request,**kwargs):send(request);raise OSError('Lost acknowledgement')
        with patch('tracker.capture.urlopen',side_effect=lost):out.drain()
        restarted=Outbox(path,producer='trainer')
        with patch('tracker.capture.urlopen',return_value=io.BytesIO(b'{"id":"wrong","revision":0}')):
            self.assertEqual(restarted.drain()['sent_now'],0)
        with patch('tracker.capture.urlopen',side_effect=send):self.assertEqual(restarted.drain()['sent_now'],1)
        self.assertEqual(len(recipes.snapshot(self.store)['recipes']),1)


if __name__=='__main__':unittest.main()
