import copy
import tempfile
import unittest
from pathlib import Path

from tracker import adapters, graph_store, training_spans as spans, training_lineage, training_recipes
from tracker.portable import generation_document
from tracker.schema import InputError, digest
from tracker.semantic_map import evidence
from tracker.store import Store
from test_policy_gradients import signal
from test_training_recipes import manifest, packet, record


def run_and_graph(text='Read test. Fix code. Check it.', ranges=None):
    run = adapters.normalize(generation_document('Fix the issue', text, metadata={'experiment':'exp'}),
        meta={'producer':'worker','logical_rollout_id':'a'})[0]
    event = run['events'][-1]
    ranges = ranges if ranges is not None else [(0,10,'orient'),(11,20,'construct'),(21,len(text),'verify')]
    units = [{'id':'u'+str(i), 'source': evidence(run,event['id'],start=a,end=b), 'activity':activity,
              'actor':'agent','kind':'semantic'} for i,(a,b,activity) in enumerate(ranges)]
    graph = graph_store.build(run, {'observer':{'id':'authored','label':'Authored controls'},
        'document':{'source_hash':digest(run), 'units':units, 'provenance':{'origin':'authored-control'}}})
    return run, graph


def mapped(run, intervals):
    return {'schema':spans.VERSION, 'status':'mapped', 'basis':'Authored offset control', 'source_hash':digest(run),
            'spans':[None if interval is None else {'event_id':run['events'][-1]['id'],'start':interval[0],'end':interval[1]} for interval in intervals]}


class TrainingSpansTests(unittest.TestCase):
    def test_partition_masks_and_crossing_boundaries(self):
        run, graph = run_and_graph()
        source = mapped(run, [(0,4),(5,9),(8,14),(11,14),(21,26),None])
        s = signal(target_tokens=[1,2,3,4,5,6], loss_mask=[1,0,1,1,1,1],
                   d_loss_d_logp=[1,9,7,0,-2,8],source_alignment=source)
        result = spans.project(run,graph,s)
        self.assertEqual(result['coverage']['eligible_tokens'], {'unit_assigned':3,'boundary_or_overlap':1,'unmapped_token':1})
        self.assertEqual(sum(result['coverage']['all_tokens'].values()),6)
        by = {u['id']:u for u in result['units']}
        self.assertEqual((by['u0']['mapped_tokens'],by['u0']['eligible_tokens'],by['u0']['mean_absolute_derivative']),(2,1,1))
        self.assertEqual(by['u1']['zero_derivatives'],1)
        self.assertEqual(by['u2']['nonzero_derivatives'],1)
        self.assertEqual(sum(a['eligible_tokens'] for a in result['activities']),3)

    def test_source_only_does_not_invent_activities(self):
        run,_ = run_and_graph(); graph = graph_store.build(run)
        s = signal(source_alignment=mapped(run,[(0,4),(5,9),None]))
        result=spans.project(run,graph,s)
        self.assertEqual(result['coverage']['eligible_tokens'],{'unannotated_source':2})
        self.assertEqual(result['activities'],[])
        self.assertEqual(result['events'][0]['mapped_tokens'],2)

    def test_overlapping_units_are_not_double_counted(self):
        run,graph=run_and_graph(ranges=[(0,10,'orient'),(2,6,'reason')])
        s=signal(source_alignment=mapped(run,[(0,4),(5,9),(11,14)]))
        result=spans.project(run,graph,s)
        self.assertEqual(result['coverage']['eligible_tokens'],{'boundary_or_overlap':2})
        self.assertEqual(sum(u['eligible_tokens'] for u in result['units']),0)

    def test_hash_bounds_and_stale_graph_fail_closed(self):
        run,graph=run_and_graph(); s=signal(source_alignment=mapped(run,[(0,4),(5,9),None]))
        s['source_alignment']['source_hash']='old'
        self.assertEqual(spans.project(run,graph,s)['status'],'source_mismatch')
        s['source_alignment']=mapped(run,[(0,100),(5,9),None])
        self.assertEqual(spans.project(run,graph,s)['status'],'invalid_source_spans')
        changed=copy.deepcopy(run);changed['metadata']['task_id']='different'
        with self.assertRaises(InputError):spans.project(changed,graph,s)

    def test_non_agent_tokens_are_not_agent_behavior(self):
        run,graph=run_and_graph(); source=mapped(run,[(0,4),(5,9),None])
        source['spans'][0]={'event_id':run['events'][0]['id'],'start':0,'end':3}
        result=spans.project(run,graph,signal(source_alignment=source))
        self.assertEqual(result['coverage']['eligible_tokens'],{'non_agent_source':1,'unit_assigned':1})

    def test_missing_mapping_is_not_zero(self):
        run,graph=run_and_graph()
        self.assertEqual(spans.project(run,graph,signal())['status'],'unavailable')
        s=signal(source_alignment=spans.unavailable('Round-trip mismatch'))
        self.assertEqual(spans.project(run,graph,s)['reason'],'Round-trip mismatch')

    def test_shape_validation(self):
        run,_=run_and_graph(); base=mapped(run,[(0,4),(5,9),None])
        changes=[{'spans':[]},{'spans':[{'event_id':'e','start':True,'end':2},None,None]},
                 {'spans':[{'event_id':'e','start':2,'end':2},None,None]}, {'schema':'unknown'}, {'basis':''}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(InputError):spans.validate(base|change,3)

    def test_fast_bridge_requires_decode_and_token_id_roundtrip(self):
        run,_=run_and_graph('a a',[(0,3,'orient')]); eid=run['events'][-1]['id']
        class Tokenizer:
            is_fast=True;all_special_ids=[0]
            def decode(self,*args,**kwargs):return 'a a'
            def __call__(self,*args,**kwargs):return {'input_ids':[5,5],'offset_mapping':[(0,1),(2,3)]}
        t=Tokenizer(); value=spans.from_tokenizer(t,[5,5,0],run,eid)
        self.assertEqual(value['spans'],[{'event_id':eid,'start':0,'end':1},{'event_id':eid,'start':2,'end':3},None])
        self.assertEqual(spans.from_tokenizer(t,[5,6,0],run,eid)['status'],'unavailable')
        t.decode=lambda *a,**k:'different'
        self.assertEqual(spans.from_tokenizer(t,[5,5,0],run,eid)['status'],'unavailable')

    def test_reordered_multi_event_tokens_keep_declared_source(self):
        run,graph=run_and_graph(); source=mapped(run,[(21,26),(0,4),(11,14)])
        result=spans.project(run,graph,signal(source_alignment=source))
        self.assertEqual([(u['id'],u['eligible_tokens']) for u in result['units']],[('u0',1),('u1',0),('u2',1)])

    def test_interval_sweep_matches_independent_overlap_oracle(self):
        import random
        rng=random.Random(73)
        for _ in range(40):
            ranges=[(a,a+rng.randint(1,10),'unresolved') for a in [rng.randrange(40) for _ in range(12)]]
            run,graph=run_and_graph('x'*50,ranges)
            intervals=[(a,a+rng.randint(1,10)) for a in [rng.randrange(40) for _ in range(30)]]
            expected=[0]*len(ranges)
            for a,b in intervals:
                intersections=[i for i,(c,d,_) in enumerate(ranges) if max(a,c)<min(b,d)]
                if len(intersections)==1:
                    i=intersections[0];c,d,_=ranges[i]
                    if c<=a and b<=d:expected[i]+=1
            result=spans.project(run,graph,signal(target_tokens=list(range(30)),loss_mask=[1]*30,
                d_loss_d_logp=[.1]*30,source_alignment=mapped(run,intervals)))
            self.assertEqual({u['id']:u['eligible_tokens'] for u in result['units']},{'u'+str(i):n for i,n in enumerate(expected)})

    def test_inspect_immutable_use_and_exact_source_for_both_schemas(self):
        for schema in ['training-records/1','training-records/2']:
            with self.subTest(schema=schema),tempfile.TemporaryDirectory() as directory:
                store=Store(Path(directory)/'db.sqlite');run,graph=run_and_graph()
                document=generation_document('Fix the issue','Read test. Fix code. Check it.',metadata={'experiment':'exp'})
                sample=record('sample');sample['evidence']['source_revision']=0
                use=record('use',recipe={'producer':'trainer','id':'recipe','revision':0},
                    policy_gradient=signal(source_alignment=mapped(run,[(0,4),(11,14),(21,26)])))
                if schema.endswith('/2'):
                    sample['sample']=use['sample']={'producer':'worker','id':'sample-a'}
                    sample['evidence'].pop('source_revision')
                    sample['data']['source']={'producer':'worker','rollout_id':'a','revision':0}
                training_lineage.receive(store,{'schema':schema,'producer':'worker','experiment':'exp','records':[sample,use]})
                store.ingest({'producer':'worker','rollout_id':'a','revision':0,'state':'complete','document':document})
                with store.connect() as c:graph_store.save(c,graph)
                selector={'schema':schema,'producer':'worker','experiment':'exp','id':use['id']}
                self.assertEqual(spans.inspect_use(store,selector,graph['id'])['status'],'component_unresolved')
                training_recipes.receive(store,packet(manifest()))
                result=spans.inspect_use(store,selector,graph['id'])
                self.assertEqual(result['projection']['status'],'mapped')
                self.assertEqual(result['projection']['coverage']['eligible_tokens'],{'unit_assigned':2})
                self.assertEqual(result['snapshot_id'],spans.inspect_use(store,selector,graph['id'])['snapshot_id'])
                from tracker.training_health import snapshot
                exported=snapshot(store)['cohorts'][0]['uses'][0]['points'][0]['records'][0]
                self.assertEqual(exported['record_schema'],schema)
                self.assertEqual(exported['record_producer'],'worker')
                with self.assertRaises(KeyError):spans.inspect_use(store,selector|{'producer':'other'},graph['id'])


if __name__=='__main__':unittest.main()
