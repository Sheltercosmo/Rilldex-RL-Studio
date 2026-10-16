"""Independent sample identities; authored contract controls, not trainer execution."""
import copy
import json
import unittest

from tracker import training_samples, training_lineage, training_selection, monitoring
from tracker import training_investigations, training_comparisons, population_comparisons
from tracker.population_statistics import summary
from tracker.schema import InputError, digest
from tracker.store import ReviewConflict
import test_training_lineage as fixtures


def record(kind, name='s1', **data):
    r=fixtures.record(kind,name,**data)
    r['sample']={'producer':'learner-export','id':name}
    r['evidence']={'basis':'Authored independent-sample contract control'}
    return r


class IndependentSampleTests(unittest.TestCase):
    setUp=fixtures.TrainingLineageTests.setUp
    source=fixtures.TrainingLineageTests.source

    def packet(self, records):
        return {'schema':training_samples.VERSION,'producer':'learner-export','experiment':'exp','records':records}

    def add(self,*records):return training_lineage.receive(self.store,self.packet(list(records)))

    def declaration(self,name='s1',source='episode',**data):
        return record('sample',name,source={'producer':'worker','rollout_id':source,'revision':0},**data)

    def prepare(self):
        self.source('episode','123456789');self.source('other','x')
        for name,episode,state in [('s1','episode','admitted'),('s2','episode','rejected'),('s3','other','admitted')]:
            self.add(self.declaration(name,episode),record('selection',name,decision=state),record('score',name,value=1 if name=='s1' else 0))
        self.add(record('use','s1'),record('use','s1',identifier='reuse',learner_step=1))
        monitor=monitoring.create(self.store,{'name':'Length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        monitoring.sync(self.store)
        scope={'monitor':monitor['id'],'selection':training_lineage.snapshot(self.store)['selection_options'][0]['id']}
        snap=training_lineage.snapshot(self.store,**scope)
        return snap,scope

    def test_independent_score_gate_use_and_source_weight(self):
        snap,_=self.prepare();c=snap['cohorts'][0]
        self.assertEqual(c['counts']['generated'],3);self.assertEqual(c['counts']['scored'],3)
        self.assertEqual(c['counts']['admitted'],2);self.assertEqual(c['counts']['backward'],1)
        self.assertEqual(c['comparison']['generated']['mean_per_rollout'],5)
        self.assertEqual(c['comparison']['generated']['source_rollouts'],2)
        self.assertEqual(c['comparison']['generated']['population'],3)
        self.assertEqual(c['selection_comparison']['within_group']['comparisons'][0]['shared_source_rollouts'],1)
        self.assertEqual([r['sample_id'] for r in snap['samples']],['s1','s2','s3'])
        self.assertEqual(snap['samples'][0]['use_count'],2)
        self.assertEqual(snap['samples'][0]['source_mapping_status'],'episode_reference')
        self.assertEqual(snap['samples'][0]['producer'],'learner-export')
        self.assertEqual(snap['samples'][0]['source']['producer'],'worker')
        self.assertEqual([r['data']['value'] for r in snap['samples'][1]['records'] if r['kind']=='score'],[0])

    def test_late_out_of_order_evidence_stays_on_pinned_source(self):
        self.add(record('score',revision=3,value=1));self.add(record('score',revision=0,value=0))
        self.assertEqual(training_lineage.snapshot(self.store)['orphan_samples'],1)
        self.add(self.declaration());self.assertEqual(training_lineage.snapshot(self.store)['samples'][0]['join_status'],'source_not_delivered')
        old=self.source('episode');self.source('episode','new source',1)
        got=training_lineage.snapshot(self.store)['samples'][0]
        self.assertEqual(got['run_id'],old['id'])
        self.assertEqual([r['data']['value'] for r in got['records'] if r['kind']=='score'],[1])

    def span(self,run):
        e=next(e for e in run['events'] if e['kind']=='message')
        return {'event_id':e['id'],'source_pointer':e['source_pointer'],'start':0,'end':2,'text':e['text'][:2]}

    def test_unicode_spans_resolve_exact_source_not_latest(self):
        source=self.source('episode','🔧x ready');run=self.store.get(source['id'])['run']
        d=self.declaration(interaction_ids=['native-call-a']);d['data']['source']['spans']=[self.span(run)]
        self.add(d);got=training_lineage.snapshot(self.store)['samples'][0]
        self.assertEqual(got['source_mapping_status'],'exact_source_spans');self.assertEqual(got['run_id'],source['id'])
        self.assertEqual(got['measurement_grain'],'source_rollout_context')

    def test_wrong_spans_never_fall_back_to_whole_source(self):
        source=self.source('episode','abc');run=self.store.get(source['id'])['run']
        d=self.declaration();d['data']['source']['spans']=[self.span(run)|{'text':'zz'}]
        self.add(d);got=training_lineage.snapshot(self.store)['samples'][0]
        self.assertEqual(got['join_status'],'invalid_source_spans');self.assertIsNone(got['run_id'])

    def test_visibility_and_pointer_boundaries(self):
        source=self.source('episode','abc');run=self.store.get(source['id'])['run'];span=self.span(run)
        for field,value in [('copied_context',True),('agent_visibility','not_established'),('kind','external_evaluation')]:
            changed=copy.deepcopy(run);next(e for e in changed['events'] if e['id']==span['event_id'])[field]=value
            self.assertEqual(training_samples.binding_status(changed,{'spans':[span]}),'invalid_source_spans')
        self.assertEqual(training_samples.binding_status(run,{'spans':[span|{'source_pointer':'/private'}]}),'invalid_source_spans')

    def test_unknown_source_and_experiment_conflict_are_separate(self):
        self.add(record('sample'));r=training_lineage.snapshot(self.store)['samples'][0]
        self.assertEqual(r['join_status'],'source_not_declared');self.assertIsNone(r['rollout_id'])
        from tracker.portable import generation_document
        self.store.ingest({'producer':'worker','rollout_id':'episode','revision':0,'state':'complete',
            'document':generation_document('q','a',metadata={'experiment':'different'})})
        self.add(self.declaration('s2'));r=training_lineage.snapshot(self.store)['samples'][1]
        self.assertEqual(r['join_status'],'experiment_conflict');self.assertIsNone(r['run_id'])

    def test_mapping_contract_rejects_ambiguous_bounds_and_legacy_reference(self):
        bad=[{'source':{}},{'source':{'producer':'w','rollout_id':'e','revision':True}},
            {'interaction_ids':[]},{'interaction_ids':['duplicate','duplicate']},{'interaction_ids':[1]},
            {'source':{'producer':'w','rollout_id':'e','revision':0,'spans':[]}}]
        span={'event_id':'e','source_pointer':'/x','start':0,'end':2,'text':'ab'}
        for spans in [[span,span],[span|{'end':3}],[span|{'start':True}]]:
            bad.append({'source':{'producer':'w','rollout_id':'e','revision':0,'spans':spans}})
        for data in bad:
            with self.subTest(data=data),self.assertRaises(InputError):self.add(record('sample',**data))
        with self.assertRaises(InputError):self.add(fixtures.record('sample'))
        d=self.declaration();d['evidence']['source_revision']=0
        with self.assertRaises(InputError):self.add(d)

    def test_duplicate_identity_conflict_is_atomic_across_versions(self):
        declaration=self.declaration();self.assertEqual(self.add(declaration)['inserted'],1)
        self.assertEqual(self.add(declaration)['inserted'],0)
        with self.assertRaises(ReviewConflict):self.add(record('score'),self.declaration(interaction_ids=['changed']))
        self.assertFalse(training_lineage.snapshot(self.store)['samples'][0]['populations']['scored'])
        legacy=fixtures.record('score',identifier=declaration['id'])
        with self.assertRaises(ReviewConflict):training_lineage.receive(self.store,self.packet([legacy])|{'schema':training_lineage.VERSION})
        self.add(self.declaration(identifier='second-declaration'))
        self.assertEqual(training_lineage.snapshot(self.store)['conflicting_samples'],1)

    def test_legacy_and_independent_samples_keep_separate_cohorts_and_ids(self):
        self.source('episode');self.add(self.declaration('episode'))
        training_lineage.receive(self.store,{'schema':training_lineage.VERSION,'producer':'worker','experiment':'exp','records':[fixtures.record('sample','episode')]})
        s=training_lineage.snapshot(self.store)
        self.assertEqual(len(s['cohorts']),2);self.assertEqual(len({digest(training_samples.identity(r)) for r in s['samples']}),2)

    def test_sdk_opt_in_uses_existing_durable_queue(self):
        first=self.out.log_training('exp',[self.declaration()],schema=training_samples.VERSION)
        second=self.out.log_training('exp',[self.declaration()],schema=training_samples.VERSION)
        self.assertFalse(first['duplicate']);self.assertTrue(second['duplicate'])
        with self.out.connect() as c:
            columns=[r['name'] for r in c.execute('PRAGMA table_info(queue)')]
        self.assertIn('payload',columns)
        with self.out.connect() as c:packet=json.loads(c.execute('SELECT payload FROM queue').fetchone()[0])['training_records']
        self.assertEqual(training_lineage.receive(self.store,packet)['inserted'],1)

    def test_saved_comparison_retains_every_sample_and_shared_source(self):
        snap,scope=self.prepare()
        parent=training_investigations.save(self.store,{'scope':scope,'snapshot_id':snap['snapshot_id'],
            'view':{'stage':'generated','selection':None},'title':'Independent sample control','hypothesis':''})
        self.assertEqual(len({r['sample_id'] for r in parent['selected_samples']}),3)
        spec={'cohort':snap['cohorts'][0]['cohort'],'focus':{'kind':'filter','value':'admitted'},
            'reference':{'kind':'filter','value':'rejected'},'monitors':[scope['monitor']]}
        result=training_comparisons.preview(self.store,{'parent_id':parent['id'],'spec':spec})
        m=result['metrics'][0];self.assertEqual(m['focus']['mean_per_rollout'],5)
        self.assertEqual(m['reference']['mean_per_rollout'],9);self.assertEqual(m['shared_source_rollouts'],1)
        self.assertEqual(len({s['id'] for s in result['samples']}),3)
        saved=training_comparisons.save(self.store,{'parent_id':parent['id'],'spec':spec,'preview_id':result['id']})
        self.source('episode','changed',1)
        self.assertEqual(training_comparisons.preview(self.store,{'parent_id':saved['id'],'spec':spec})['metrics'][0]['focus']['mean_per_rollout'],5)


class SourceWeightTests(unittest.TestCase):
    def rows(self):
        return [{'id':str(i),'experiment':'e','producer':'p','run_id':rid,'sample_identity_schema':training_samples.VERSION,
                 'sample_id':str(i),'measurement':m} for i,(rid,m) in enumerate([
            ('a',{'status':'available','value':1,'numerator':1,'denominator':1,'opportunities':1,'unknown':0}),
            ('a',{'status':'available','value':1,'numerator':1,'denominator':1,'opportunities':1,'unknown':0}),
            ('b',{'status':'available','value':0,'numerator':0,'denominator':3,'opportunities':3,'unknown':0}),
            ('c',{'status':'unavailable','value':None,'numerator':0,'denominator':0,'opportunities':2,'unknown':2}),
            (None,{'status':'source_unavailable','value':None})])]

    def test_unique_source_mean_and_opportunities_with_unknowns(self):
        r=summary(self.rows(),True)
        self.assertEqual((r['population'],r['measured'],r['source_rollouts'],r['source_measured']),(5,3,3,2))
        self.assertEqual(r['mean_per_rollout'],.5);self.assertEqual(r['samples_without_source'],1)
        self.assertEqual(r['pooled_opportunities'],{'value':.25,'numerator':1,'denominator':4,'opportunities':6,'unknown':2,'rollouts_with_counts':3,'rollouts_without_counts':0})

    def test_conflicting_copies_are_rejected_instead_of_arrival_order_selection(self):
        rows=self.rows();rows[1]['measurement']['value']=0
        with self.assertRaisesRegex(InputError,'Conflicting measurements'):summary(rows,True)

    def test_associations_use_sources_and_retain_all_sample_members(self):
        samples=self.rows()[:3];a={'monitor':{'id':'a'},'aggregation':'mean','values':{s['id']:s['measurement'] for s in samples}}
        result=population_comparisons.compare(samples,['0','1'],['1','2'],[a,a|{'monitor':{'id':'b'}}])
        self.assertEqual(result['associations'][0]['sample_ids'],['0','1','2'])
        self.assertEqual(result['associations'][0]['n'],2)
        self.assertIsNone(result['associations'][0]['rho'])
        self.assertEqual(result['metrics'][0]['shared_source_rollouts'],1)

    def test_legacy_arithmetic_is_unchanged(self):
        rows=self.rows()
        for r in rows:r.pop('sample_identity_schema')
        got=summary(rows,True)
        self.assertEqual(got['mean_per_rollout'],2/3);self.assertEqual(got['pooled_opportunities']['value'],2/5)
        self.assertNotIn('source_rollouts',got)

    def test_group_namespace_and_mixed_grains_are_not_silently_pooled(self):
        rows=self.rows()[:3]
        for r in rows:r['group_id']='g';r['filter_decision']={'state':'rejected' if r['id']=='2' else 'admitted'}
        rows[1]['producer']='other'
        got=training_selection.matched_groups(rows)
        self.assertEqual(got['excluded_groups'],{'ambiguous_group_namespace':1})
        rows[1].pop('sample_identity_schema')
        with self.assertRaisesRegex(InputError,'one sample identity contract'):
            population_comparisons.compare(rows,['0'],['1'],[{'monitor':{'id':'m'},'aggregation':'mean','values':{}}])


if __name__=='__main__':unittest.main()
