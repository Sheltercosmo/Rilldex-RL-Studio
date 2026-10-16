import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tracker import teacher_signals as signals, training_lineage as lineage, training_health as health
from tracker import training_recipes as recipes
from tracker.tinker_capture import prepared_record, UPSTREAM_COMMIT
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict


def signal():
    return {'schema': signals.VERSION, 'provider': {'producer':'lab','id':'teacher','revision':'v1'},
        'student_policy':'student/7', 'tokenizer_id':'vocab/1',
        'probability_basis':{'student':'recorded sampler probability','teacher':'teacher scoring distribution'},
        'context':{'student_digest':'a','teacher_digest':'a','definition':'identical token context'},
        'coefficient':1.0,'discount':0.0,'target_tokens':[11,12,13,14], 'mask':[0,1,0,1],
        'student_logprobs':[None,-2,None,-1], 'teacher_logprobs':[None,-1,None,-3],
        'advantage_delta':[0,1,0,-2]}


def recipe_ref(): return {'producer':'trainer','id':'opd','revision':0}


def record(identifier='signal/1', sample='a', step=10, value=None):
    return {'id':identifier,'revision':0,'kind':'supervision','sample':{'producer':'worker','id':sample},
        'evidence':{'basis':'authored control'},'data':{'recipe':recipe_ref(),'component':'teacher',
        'step':step,'step_basis':'preparation iteration','stage':'prepared','boundary':'native delta prepared',
        'signal':value or signal()}}


def manifest():
    return {'schema':recipes.VERSION,'producer':'trainer','experiment':'test','recipes':[{
        'id':'opd','revision':0,'label':'OPD control','implementation':{'name':'authored','revision':'1'},
        'config_digest':'authored','basis':'authored control','components_complete':True,'context':{},
        'components':[{'id':'teacher','label':'Teacher','supervision':'teacher',
            'provider':signal()['provider'],'credit':{'kind':'token_distribution','unit':'token'},
            'objective':{'definition':'sampled OPD','unit':'token','weighting':'none','reduction':'native'}}]}]}


class TeacherSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'teacher.sqlite')

    def add(self,*records):
        return lineage.receive(self.store,{'schema':'training-records/2','producer':'trainer','experiment':'test','records':list(records)})

    def sample(self, sample='a'):
        self.add({'id':'sample/'+sample,'revision':0,'kind':'sample','sample':{'producer':'worker','id':sample},
                  'evidence':{'basis':'authored control'},'data':{'split':'train'}})

    def cohort(self):return health.snapshot(self.store)['cohorts'][0]

    def test_token_weighted_mean_negative_allowed_and_zero_denominator(self):
        a=signal();b=signal();b['mask']=[0,1,0,0]
        result=signals.summarize([a,b])
        self.assertEqual(result['sampled_log_ratio'],{'value':0,'numerator':0,'denominator':3})
        self.assertEqual(signals.summarize([b])['sampled_log_ratio']['value'],-1)
        b['mask']=[0]*4
        self.assertIsNone(signals.summarize([b])['sampled_log_ratio']['value'])
        self.assertEqual(signals.summarize([b])['off_mask_delta']['numerator'],2)

    def test_validation_rejects_misalignment_nonfinite_positive_logp_and_fractional_mask(self):
        for field,value in [('teacher_logprobs',[-1]),('mask',[0,.5,0,1]),
                            ('advantage_delta',[0,float('nan'),0,0]),
                            ('student_logprobs',[None,0.1,None,-1]),
                            ('teacher_logprobs',[None,None,None,-1]),('discount',1.1)]:
            with self.subTest(field=field):
                s=signal();s[field]=value
                with self.assertRaises(InputError):signals.validate(s)
        signals.validate(signal())

    def test_late_declaration_replay_immutability_and_no_training_use(self):
        self.add(record());self.assertEqual(health.snapshot(self.store)['orphan_samples'],1)
        self.sample();before=health.snapshot(self.store)
        self.assertEqual(self.cohort()['teachers'][0]['component_binding'],'not_delivered')
        recipes.receive(self.store,manifest())
        self.assertEqual(self.cohort()['teachers'][0]['component_binding'],'matched')
        self.assertEqual(self.add(record())['inserted'],0)
        changed=record();changed['data']['signal']['coefficient']=2
        with self.assertRaises(ReviewConflict):self.add(changed)
        self.assertEqual(self.cohort()['uses'],[])
        self.assertFalse(lineage.snapshot(self.store)['samples'][0]['populations']['backward'])
        self.assertNotEqual(before['snapshot_id'],health.snapshot(self.store)['snapshot_id'])

    def test_provider_conflict_and_semantics_split_streams(self):
        self.sample();recipes.receive(self.store,manifest());self.add(record())
        for i,field,value in [(1,'provider',{'producer':'lab','id':'teacher','revision':'v2'}),
                              (2,'discount',0.5),(3,'tokenizer_id','different/1'),
                              (4,'probability_basis',{'student':'raw model','teacher':'scoring'})]:
            r=record(str(i));r['data']['signal'][field]=value;self.add(r)
        streams=self.cohort()['teachers'];self.assertEqual(len(streams),5)
        self.assertEqual(sum(s['component_binding']=='provider_conflict' for s in streams),1)

    def test_missing_observations_and_repeated_preparation_are_visible(self):
        self.sample();self.sample('b');self.add(record(),record('signal/2',step=20))
        s=self.cohort()['teachers'][0]
        self.assertEqual((s['observations'],s['unique_samples'],s['samples_without_this_signal']),(2,1,1))
        self.assertEqual([p['step'] for p in s['points']],[10,20])

    def test_supervision_cannot_be_revised_or_imported_as_legacy(self):
        r=record();r['revision']=1
        with self.assertRaises(InputError):self.add(r)
        r=record();r['sample']={'producer':'worker','rollout_id':'a'}
        with self.assertRaises(InputError):lineage.validate({'schema':'training-records/1','producer':'trainer','experiment':'test','records':[r]})

    def test_independent_recipe_reference_does_not_inherit_sample(self):
        self.sample();self.add(record());recipes.receive(self.store,manifest())
        self.assertEqual(self.cohort()['recipe_context']['status'],'not_recorded')
        self.assertEqual(self.cohort()['teachers'][0]['recipe_context']['status'],'recorded')


class TinkerCaptureTests(unittest.TestCase):
    def args(self):
        def model(tokens):return SimpleNamespace(chunks=[SimpleNamespace(type='encoded_text',tokens=tokens)])
        s=signal();s['student_logprobs']=[0,-2,0,-1]
        return dict(record_id='signal/a',sample={'producer':'worker','id':'a'},
            datum=SimpleNamespace(model_input=model([10,11,12,13]),loss_fn_inputs={
                'target_tokens':s['target_tokens'],'logprobs':s['student_logprobs'],'mask':s['mask']}),
            teacher_input=model([10,11,12,13,14]),teacher_logprobs=[None,0,-1,0,-3],
            native_advantage_delta=s['advantage_delta'],provider=s['provider'],student_policy='student/7',
            tokenizer_id=s['tokenizer_id'],probability_basis=s['probability_basis'],recipe=recipe_ref(),
            component='teacher',step=10,step_basis='preparation iteration',coefficient=1,discount=0,
            upstream_commit=UPSTREAM_COMMIT)

    def test_capture_preserves_native_values_without_mutation(self):
        args=self.args();prior=copy.deepcopy(args);r=prepared_record(**args)
        self.assertEqual(args,prior)
        self.assertEqual(r['data']['signal']['advantage_delta'],[0,1,0,-2])
        self.assertEqual(r['data']['signal']['teacher_logprobs'],[0,-1,0,-3])

    def test_revision_shift_multimodal_and_teacher_length_fail_closed(self):
        for kind in ['revision','shift','multimodal','length']:
            args=self.args()
            if kind=='revision':args['upstream_commit']='unknown'
            elif kind=='shift':args['teacher_input'].chunks[0].tokens[-1]=99
            elif kind=='multimodal':args['teacher_input'].chunks[0].type='image'
            else:args['teacher_logprobs'].pop()
            with self.subTest(kind=kind),self.assertRaises(InputError):prepared_record(**args)


if __name__=='__main__':unittest.main()
