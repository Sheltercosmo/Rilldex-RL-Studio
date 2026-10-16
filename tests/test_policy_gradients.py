import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker.schema import InputError
from tracker.store import Store, ReviewConflict
from tracker import policy_gradients as gradients, training_lineage, training_recipes, training_health
from test_training_recipes import manifest, packet, record


def signal(**change):
    return {'schema':gradients.VERSION,'component':'reward','definition':'authored native derivative control',
        'tokenizer_id':'tok/1','input_digest':'input/1','probability_basis':'authored raw target log probabilities',
        'normalization':'authored loss sum / 4', 'target_tokens':[11,12,13], 'loss_mask':[1,1,0],
        'd_loss_d_logp':[-.5,0,0], **change}


def use(**change):
    return record('use',recipe={'producer':'trainer','id':'recipe','revision':0},model_tokens=3,loss_tokens=2,
                  advantage=1,policy_gradient=signal(),**change)


class PolicyGradientTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'store.sqlite')
        self.context={'manifest':manifest(),'status':'recorded'}

    def receive(self,*rows):
        return training_lineage.receive(self.store,{'schema':'training-records/1','producer':'worker','experiment':'exp','records':list(rows)})

    def test_target_shape_types_finiteness_and_budget(self):
        gradients.validate(signal())
        for change in [{'loss_mask':[1,0]}, {'loss_mask':[True,1,0]}, {'d_loss_d_logp':[float('nan'),0,0]},
                       {'target_tokens':[]},{'target_tokens':[-1,1,2]},{'target_tokens':[1]*131073},
                       {'normalization_context':{'scale':float('inf')}}]:
            with self.subTest(change=str(change)[:60]),self.assertRaises(InputError):gradients.validate(signal(**change))

    def test_zero_mask_and_missing_are_distinct(self):
        row=use();summary=gradients.summarize([row,record('use','missing')],self.context)
        self.assertEqual(summary['zero_gradient'],{'value':.5,'numerator':1,'denominator':2})
        self.assertEqual(summary['mean_absolute_gradient']['value'],.25)
        self.assertEqual(summary['missing_uses'],1)
        row['data']['policy_gradient']=signal(loss_mask=[0,0,0])
        self.assertIsNone(gradients.summarize([row],self.context)['zero_gradient']['value'])
        self.assertEqual(gradients.sample_state(row,self.context),'masked_out')

    def test_nonzero_advantage_is_not_nonzero_gradient(self):
        row=use();row['data']['policy_gradient']=signal(d_loss_d_logp=[0,0,0])
        self.assertEqual(gradients.sample_state(row,self.context),'zero')
        self.assertEqual(gradients.summarize([row],self.context)['zero_gradient_nonzero_advantage']['value'],1)
        row['data'].pop('advantage')
        self.assertIsNone(gradients.summarize([row],self.context)['zero_gradient_nonzero_advantage']['value'])

    def test_component_binding_and_definition_compatibility(self):
        row=use();wrong=copy.deepcopy(row);wrong['data']['policy_gradient']['component']='unknown'
        self.assertEqual(gradients.summarize([wrong],self.context)['unbound_uses'],1)
        missing={'status':'not_delivered','manifest':None}
        self.assertIsNone(gradients.summarize([row],missing)['zero_gradient']['value'])
        changed=copy.deepcopy(row);changed['data']['policy_gradient']['normalization']='different declared reduction'
        view=gradients.summarize([row,changed],self.context)
        self.assertFalse(view['compatible_definitions']);self.assertIsNone(view['mean_absolute_gradient']['value'])

    def test_off_mask_gradient_not_silently_discarded(self):
        row=use();row['data']['policy_gradient']=signal(d_loss_d_logp=[-.5,0,2])
        self.assertEqual(gradients.summarize([row],self.context)['off_mask_nonzero'],1)

    def test_scalar_receipts_must_match_arrays(self):
        for key,value in [('recipe',None),('model_tokens',2),('loss_tokens',1)]:
            row=use()
            if value is None:row['data'].pop(key)
            else:row['data'][key]=value
            with self.assertRaises(InputError):self.receive(row)

    def test_immutable_replay_and_late_recipe_updates_health(self):
        self.receive(record('sample'),use())
        c=training_health.snapshot(self.store)['cohorts'][0]
        self.assertEqual(c['uses'][0]['policy_gradient']['unbound_uses'],1)
        training_recipes.receive(self.store,packet(manifest()))
        c=training_health.snapshot(self.store)['cohorts'][0]
        self.assertEqual(c['uses'][0]['policy_gradient']['zero_gradient']['value'],.5)
        self.assertEqual(c['uses'][0]['points'][0]['policy_gradient']['eligible_tokens'],2)
        self.assertEqual(self.receive(use())['inserted'],0)
        changed=use();changed['data']['policy_gradient']['d_loss_d_logp'][0]=1
        with self.assertRaises(ReviewConflict):self.receive(changed)

    def test_backward_and_optimizer_views_are_separate(self):
        back=use();opt=copy.deepcopy(back);opt['id']+='/optimizer';opt['data']['stage']='optimizer_step_completed'
        training_recipes.receive(self.store,packet(manifest()));self.receive(record('sample'),back,opt)
        views=training_health.snapshot(self.store)['cohorts'][0]['uses']
        self.assertEqual(len(views),2)
        self.assertTrue(all(v['policy_gradient']['observed_uses']==1 for v in views))

    def test_independent_samples_support_same_observation(self):
        row=use();row['sample']={'producer':'worker','id':'a'}
        training_lineage.validate({'schema':'training-records/2','producer':'worker','experiment':'exp','records':[row]})

    def test_overflow_is_unavailable_not_infinity(self):
        row=use();row['data']['policy_gradient']=signal(d_loss_d_logp=[1e308,1e308,0])
        result=gradients.summarize([row],self.context)
        self.assertTrue(result['magnitude_overflow']);self.assertIsNone(result['mean_absolute_gradient']['value'])
        json.dumps(result,allow_nan=False)

    def test_behavior_comparison_counts_sources_once_and_exposes_overlap(self):
        from tracker.monitoring import create, sync
        from tracker.portable import generation_document
        for name,text in [('short','xx'),('long','xxxxxx')]:
            self.store.ingest({'producer':'worker','rollout_id':name,'revision':0,'state':'complete',
                'document':generation_document('task',text,metadata={'experiment':'exp','split':'train'})})
        training_recipes.receive(self.store,packet(manifest()))
        rows=[]
        for sample,source in [('s1','short'),('s2','short'),('s3','long')]:
            declaration=record('sample',sample,source={'producer':'worker','rollout_id':source,'revision':0})
            declaration['sample']={'producer':'worker','id':sample};rows.append(declaration)
            receipt=use();receipt['id']='use/'+sample;receipt['sample']={'producer':'worker','id':sample};rows.append(receipt)
        repeated=copy.deepcopy(rows[1]);repeated['id']='use/repeated';rows.append(repeated)
        zero=copy.deepcopy(rows[1]);zero['id']='use/zero';zero['data']['policy_gradient']['d_loss_d_logp']=[0,0,0];rows.append(zero)
        training_lineage.receive(self.store,{'schema':'training-records/2','producer':'worker','experiment':'exp','records':rows})
        monitor=create(self.store,{'name':'Response length','kind':'metric','observer':'source','metric':'agent_text_chars'});sync(self.store)
        view=training_health.snapshot(self.store,monitor=monitor['id'])['cohorts'][0]['uses'][0]
        nonzero=view['behavior_by_policy_gradient']['nonzero']
        self.assertEqual(nonzero['receipts'],4)
        self.assertEqual(nonzero['source_measured'],2)
        self.assertEqual(nonzero['mean_per_rollout'],4)
        self.assertEqual(view['zero_nonzero_gradient_shared_sources'],1)


if __name__=='__main__':unittest.main()
