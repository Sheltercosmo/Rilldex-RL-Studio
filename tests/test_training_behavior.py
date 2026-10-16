"""Native identity joins and source-weighted accounting; no model-quality claim."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import training_behavior as behavior, training_health as health, training_lineage as lineage
from tracker import monitoring
from tracker.portable import generation_document
from tracker.schema import InputError
from tracker.store import Store
from tests.test_training_health import record


def sample(name, source, step=0, n=1, d=2, status='available', scope='included'):
    value={'id':'value-'+str(source),'status':status,'value':n/d if d and status=='available' else None,
           'numerator':n,'denominator':d,'opportunities':d+1,'unknown':1}
    return dict(producer='rollout-worker',sample_id=name,sample_identity_schema='training-records/2',
                run_id=source,step=step,monitor_population=scope,measurement=value)


def use(s, name, step):
    return dict(id=name,revision=0,record_producer='trainer',record_schema='training-records/2',
                sample=health.sample_ref(s),data=dict(learner_step=step,stage='backward_completed'),evidence={})


class BehaviorTimelineTests(unittest.TestCase):
    def test_shared_sources_and_reuse_count_once_per_position_but_keep_every_receipt(self):
        a=sample('a','short');b=sample('b','short');c=sample('c','long',n=9,d=10)
        receipts=[use(a,'use-a',10),use(a,'reuse-a',10),use(b,'use-b',10),use(c,'use-c',10),use(a,'later-a',20)]
        out=behavior.project([a,b,c],health.sample_ref,receipts=receipts,opportunity_ratio=True)
        first,later=out['points']
        self.assertEqual((first['declared_samples'],first['source_rollouts'],first['use_receipts']),(3,2,4))
        self.assertEqual(first['mean_per_rollout'],.7)
        self.assertAlmostEqual(first['pooled_opportunities']['value'],10/12)
        self.assertEqual(first['pooled_opportunities']['unknown'],2)
        self.assertEqual(later['mean_per_rollout'],.5)
        self.assertEqual(out['total']['use_receipts'],5)
        self.assertEqual(out['total']['source_rollouts'],2)
        self.assertEqual(out['total']['mean_per_rollout'],.7)
        self.assertEqual([r['id'] for r in first['samples'][0]['uses']],['use-a','reuse-a'])

    def test_missing_annotations_missing_sources_and_scope_are_not_zero(self):
        known=sample('known','source',0);missing=sample('missing','unreviewed',1,status='unavailable',n=0,d=0)
        unbound=sample('unbound',None,1);unbound['measurement']=None
        excluded=sample('outside','outside',0,n=9,d=10,scope='excluded')
        unknown=sample('unknown-scope',None,1,scope='unknown');unknown['measurement']=None
        out=behavior.project([known,missing,unbound,excluded,unknown],health.sample_ref,opportunity_ratio=True)
        self.assertEqual(out['points'][0]['mean_per_rollout'],.5)
        p=out['points'][1]
        self.assertIsNone(p['mean_per_rollout']);self.assertIsNone(p['pooled_opportunities']['value'])
        self.assertEqual((p['source_rollouts'],p['source_measured'],p['unbound_samples']),(1,0,2))
        self.assertEqual(p['monitor_scope'],{'included':2,'unknown':1})
        self.assertEqual(len(p['samples']),3)

    def test_unplaced_generation_is_retained_without_fabricated_progress(self):
        s=sample('unplaced','source');s.pop('step')
        out=behavior.project([s],health.sample_ref)
        self.assertEqual(out['points'],[]);self.assertEqual(out['unplaced']['declared_samples'],1)
        self.assertEqual(out['total']['mean_per_rollout'],.5)
        self.assertEqual(out['coordinate'],'generation')

    def test_receipt_and_measurement_versions_are_part_of_snapshot_identity(self):
        s=sample('a','source');r=use(s,'use',7)
        first=behavior.project([s],health.sample_ref,receipts=[r]);r=deepcopy(r);r['revision']=1
        revised=behavior.project([s],health.sample_ref,receipts=[r])
        self.assertNotEqual(first['id'],revised['id']);self.assertEqual(first['points'][0]['samples'][0]['uses'][0]['revision'],0)
        with self.assertRaises(InputError):behavior.project([s,s],health.sample_ref)

    def test_native_v2_join_separates_clocks_stages_and_exact_training_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'test.sqlite')
            for name,text in [('short','abcd'),('long','abcdefgh')]:
                store.ingest(dict(producer='worker',rollout_id=name,revision=0,state='complete',
                    document=generation_document('Authored join control',text,metadata={'experiment':'exp','split':'train'})))
            rows=[]
            for name,source,step in [('s1','short',2),('s2','short',2),('s3','long',3)]:
                row=record('sample',name,step=step,step_basis='rollout_batch',source=dict(producer='worker',rollout_id=source,revision=0))
                row['sample']={'producer':'worker','id':name};rows.append(row)
            for name,identifier,step,stage,recipe in [('s1','first',20,'backward_completed','one'),('s1','reuse',20,'backward_completed','one'),
                ('s2','second',20,'backward_completed','one'),('s3','third',30,'backward_completed','one'),
                ('s1','optimizer',20,'optimizer_step_completed','one'),('s1','other-method',20,'backward_completed','two')]:
                row=record('use',name,identifier=identifier,learner_step=step,stage=stage,recipe=dict(producer='config',id=recipe,revision=0))
                row['sample']={'producer':'worker','id':name};rows.append(row)
            lineage.receive(store,dict(schema='training-records/2',producer='worker',experiment='exp',records=rows))
            monitor=monitoring.create(store,dict(name='Authored text-length control',kind='metric',observer='source',metric='agent_text_chars'))
            cold=health.snapshot(store,monitor=monitor['id'])['cohorts'][0]
            self.assertTrue(all(p['mean_per_rollout'] is None for p in cold['behavior_timeline']['points']))
            monitoring.sync(store)
            out=health.snapshot(store,monitor=monitor['id']);c=out['cohorts'][0]
            self.assertEqual(out['schema'],health.VERSION)
            self.assertEqual([p['step'] for p in c['behavior_timeline']['points']],[2,3])
            self.assertEqual([p['mean_per_rollout'] for p in c['behavior_timeline']['points']],[4,8])
            self.assertEqual(len(c['uses']),3)
            stream=next(u for u in c['uses'] if u['stage']=='backward_completed' and u['recipe_context']['reference']['id']=='one')
            p=stream['behavior_timeline']['points'][0]
            self.assertEqual(p['step'],20);self.assertEqual(p['mean_per_rollout'],4)
            self.assertEqual((p['declared_samples'],p['source_rollouts'],p['use_receipts']),(2,1,3))
            self.assertTrue(all(s['measurement']['id'].startswith('value-') for s in p['samples']))
            self.assertEqual(sum(u['behavior_timeline']['total']['use_receipts'] for u in c['uses']),6)
            self.assertIsNone(health.snapshot(store)['cohorts'][0]['behavior_timeline'])


if __name__=='__main__':unittest.main()

