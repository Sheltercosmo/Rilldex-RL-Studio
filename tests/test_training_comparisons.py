import copy
import unittest
from tracker import monitoring, training_comparisons as comparisons, training_investigations
from tracker import training_lineage, population_comparisons, failure_investigations
from tracker.schema import InputError, digest, dumps
import test_training_lineage as fixtures
from test_training_lineage import record


class TrainingComparisonTests(unittest.TestCase):
    setUp = fixtures.TrainingLineageTests.setUp
    packet = fixtures.TrainingLineageTests.packet
    add = fixtures.TrainingLineageTests.add
    source = fixtures.TrainingLineageTests.source

    def prepare(self):
        for name, text, group, state in [('a','x'*9,'hard','admitted'),('b','x'*10,'hard','rejected'),
            ('c','x'*9,'hard','admitted'),('d','x','easy','admitted'),('e','xx','easy','rejected'),('f','xx','easy','rejected')]:
            self.source(name,text);self.add(record('sample',name,group_id=group),record('selection',name,decision=state))
        self.add(record('use','a'),record('use','a',identifier='reuse'))
        primary=monitoring.create(self.store,{'name':'Length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        monitoring.sync(self.store)
        scope={'monitor':primary['id'],'selection':training_lineage.snapshot(self.store)['selection_options'][0]['id']}
        snapshot=training_lineage.snapshot(self.store,**scope)
        parent=training_investigations.save(self.store,{'scope':scope,'snapshot_id':snapshot['snapshot_id'],
            'view':{'stage':'generated','selection':None},'title':'Authored comparison control','hypothesis':''})
        self.parent=parent
        self.spec={'cohort':snapshot['cohorts'][0]['cohort'],'focus':{'kind':'filter','value':'admitted'},
            'reference':{'kind':'filter','value':'rejected'},'monitors':[primary['id']]}
        return parent,primary

    def preview(self):return comparisons.preview(self.store,{'parent_id':self.parent['id'],'spec':self.spec})

    def test_task_mix_reversal_and_sample_reuse_are_explicit(self):
        self.prepare();got=self.preview();m=got['metrics'][0]
        self.assertEqual((len(got['focus_ids']),len(got['reference_ids'])),(3,3))
        self.assertGreater(m['difference'],0)
        self.assertEqual(m['within_group']['mean_group_difference'],-1)
        self.assertEqual(m['common_support']['difference'],m['difference'])
        self.assertEqual(m['within_group']['compared_groups'],2)
        self.assertEqual(got['inference_calls'],0)

    def test_independent_coverage_and_common_support_do_not_impute(self):
        self.prepare()
        second=monitoring.create(self.store,{'name':'Eval only','kind':'metric','observer':'source','metric':'actions','population':{'split':'evaluation'}})
        self.spec['monitors'].append(second['id']);got=self.preview()
        self.assertEqual(got['common_support_ids'],[])
        self.assertEqual(got['metrics'][0]['focus']['measured'],3)
        self.assertIsNone(got['metrics'][0]['common_support']['difference'])
        self.assertEqual(got['metrics'][1]['focus']['missing_statuses'],{'outside_monitor_population':3})
        self.assertEqual(got['associations'][0]['n'],0)

    def test_pinned_primary_is_not_refreshed_when_adding_current_measures(self):
        parent,primary=self.prepare()
        second=monitoring.create(self.store,{'name':'Alternate length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        monitoring.sync(self.store);self.spec['monitors'].append(second['id'])
        with self.store.connect() as c:
            c.execute('DELETE FROM monitor_latest WHERE monitor_id=?',(primary['id'],))
        got=self.preview()
        self.assertEqual(got['metrics'][0]['observation_origin'],'saved_primary')
        self.assertEqual(got['metrics'][0]['focus']['measured'],3)
        self.assertEqual(got['metrics'][1]['observation_origin'],'current_saved_observations')
        self.assertEqual(len(got['common_support_ids']),6)
        saved=comparisons.save(self.store,{'parent_id':parent['id'],'spec':self.spec,'preview_id':got['id']})
        self.assertEqual(saved['snapshot'],parent['snapshot'])
        self.assertEqual(saved['measure_comparison'],got)
        self.assertEqual(failure_investigations.read(self.store,parent['id']),parent)

    def test_late_measurement_rejects_stale_preview_then_saved_result_stays_fixed(self):
        parent,_=self.prepare()
        second=monitoring.create(self.store,{'name':'Alternate length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        self.spec['monitors'].append(second['id']);before=self.preview()
        self.assertEqual(before['metrics'][1]['focus']['missing_statuses'],{'not_materialized':3})
        monitoring.sync(self.store)
        with self.assertRaisesRegex(InputError,'Preview and review'):
            comparisons.save(self.store,{'parent_id':parent['id'],'spec':self.spec,'preview_id':before['id']})
        self.assertEqual(len(failure_investigations.saved(self.store)),1)
        current=self.preview();saved=comparisons.save(self.store,{'parent_id':parent['id'],'spec':self.spec,'preview_id':current['id']})
        child=training_investigations.save(self.store,{'parent_id':saved['id'],'view':parent['view'],'title':'Next experiment','hypothesis':'Control group mix.'})
        self.assertEqual(child['measure_comparison'],current)
        with self.store.connect() as c:c.execute('DELETE FROM monitor_latest WHERE monitor_id=?',(second['id'],))
        self.parent=saved
        self.assertEqual(self.preview()['metrics'][1]['values'],current['metrics'][1]['values'])

    def test_retained_missingness_is_not_replaced_by_new_measurements(self):
        parent,_=self.prepare()
        second=monitoring.create(self.store,{'name':'Pending length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        self.spec['monitors'].append(second['id']);before=self.preview()
        self.parent=comparisons.save(self.store,{'parent_id':parent['id'],'spec':self.spec,'preview_id':before['id']})
        monitoring.sync(self.store)
        self.assertEqual(self.preview()['metrics'][1]['values'],before['metrics'][1]['values'])

    def test_stage_overlap_is_reported_and_repeated_uses_count_once(self):
        self.prepare();self.spec['focus']={'kind':'stage','value':'backward'};self.spec['reference']={'kind':'stage','value':'generated'}
        result=self.preview();self.assertEqual(len(result['focus_ids']),1)
        self.assertEqual(len(result['overlap_ids']),1);self.assertEqual(len(result['reference_ids']),6)

    def test_recorded_recovery_monitor_composes_with_training_decisions_and_censoring(self):
        from test_recovery_windows import captured,check,change
        controls=[('a',[check(),change(),check('passed')],'admitted'),
                  ('b',[check(),change(),check()],'admitted'),
                  ('c',[check(),check(),check(),check()],'rejected')]
        for name,steps,decision in controls:
            raw=captured(steps)['raw'];raw['metadata']={'experiment':'exp','split':'train'}
            self.store.ingest({'producer':'worker','rollout_id':name,'revision':0,'state':'complete','document':raw})
            self.add(record('sample',name),record('selection',name,decision=decision))
        m=monitoring.create(self.store,{'name':'Recorded recovery','kind':'analysis','observer':'source','analysis':{'measure':'criterion_recovery_window'}})
        monitoring.sync(self.store)
        scope={'monitor':m['id'],'selection':training_lineage.snapshot(self.store)['selection_options'][0]['id']}
        snapshot=training_lineage.snapshot(self.store,**scope)
        self.parent=training_investigations.save(self.store,{'scope':scope,'snapshot_id':snapshot['snapshot_id'],
            'view':{'stage':'generated','selection':None},'title':'Authored state controls','hypothesis':''})
        self.spec={'cohort':snapshot['cohorts'][0]['cohort'],'focus':{'kind':'filter','value':'admitted'},
            'reference':{'kind':'filter','value':'rejected'},'monitors':[m['id']]}
        r=self.preview()['metrics'][0]
        self.assertEqual(r['difference'],1)
        self.assertEqual(r['focus']['measured'],1);self.assertEqual(r['focus']['missing'],1)
        self.assertEqual(r['focus']['pooled_opportunities']['unknown'],2)
        self.assertEqual(r['reference']['pooled_opportunities']['unknown'],3)
        self.assertEqual(r['reference']['pooled_opportunities']['denominator'],1)

    def test_tampered_current_value_cannot_enter_saved_comparison(self):
        import json
        self.prepare()
        second=monitoring.create(self.store,{'name':'Other length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        monitoring.sync(self.store);self.spec['monitors'].append(second['id'])
        with self.store.connect() as c:
            row=c.execute('SELECT id,document FROM monitor_values WHERE monitor_id=? LIMIT 1',(second['id'],)).fetchone()
            value=json.loads(row['document']);value['value']=999
            c.execute('UPDATE monitor_values SET document=? WHERE id=?',(dumps(value),row['id']))
        with self.assertRaisesRegex(InputError,'Measurement identity mismatch'):self.preview()

    def test_invalid_coordinates_selectors_and_monitor_sets_fail_without_saving(self):
        self.prepare()
        for changes in [{'step':True},{'step':99},{'cohort':{}},{'focus':{'kind':'filter','value':'success'}},
            {'reference':self.spec['focus']},{'monitors':[]},{'monitors':['missing']},
            {'monitors':self.spec['monitors']*2},{'extra':True}]:
            with self.subTest(changes=changes),self.assertRaises(InputError):
                comparisons.preview(self.store,{'parent_id':self.parent['id'],'spec':self.spec|changes})
        self.assertEqual(len(failure_investigations.saved(self.store)),1)


class PopulationArithmeticTests(unittest.TestCase):
    def measure(self,values,ratio=False):
        return {'monitor':{'id':'m'},'aggregation':'opportunity_ratio' if ratio else 'mean',
            'values':{k:({'status':'available','value':v} if type(v) in (int,float) else v) for k,v in values.items()}}

    def samples(self):
        return [{'id':str(i),'experiment':'e','producer':'worker','group_id':'g','task_id':'t','policy_version':'p','step':0} for i in range(6)]

    def test_common_support_changes_a_mean_without_hiding_missingness(self):
        samples=self.samples();a=self.measure({'0':1,'1':100,'2':2,'3':20})
        b=self.measure({'0':5,'2':10});b['monitor']['id']='n'
        result=population_comparisons.compare(samples,['0','1'],['2','3'],[a,b])
        self.assertEqual(result['metrics'][0]['difference'],39.5)
        self.assertEqual(result['metrics'][0]['common_support']['difference'],-1)
        self.assertEqual(result['common_support_ids'],['0','2'])
        self.assertEqual(result['metrics'][1]['focus']['missing'],1)

    def test_opportunity_counts_include_unknown_but_do_not_change_sample_mean(self):
        samples=self.samples()
        m=self.measure({'0':{'status':'available','value':1,'numerator':1,'denominator':1,'opportunities':1,'unknown':0},
            '1':{'status':'available','value':0,'numerator':0,'denominator':9,'opportunities':9,'unknown':0},
            '2':{'status':'unavailable','value':None,'numerator':0,'denominator':0,'opportunities':3,'unknown':3}},True)
        r=population_comparisons.compare(samples,['0','1','2'],[],[m])['metrics'][0]['focus']
        self.assertEqual(r['mean_per_rollout'],.5);self.assertEqual(r['pooled_opportunities']['value'],.1)
        self.assertEqual(r['pooled_opportunities']['unknown'],3);self.assertEqual(r['missing'],1)

    def test_group_namespace_collision_and_context_conflict_are_not_pooled(self):
        samples=self.samples();samples[1]['producer']='other';m=self.measure({str(i):i for i in range(6)})
        r=population_comparisons.compare(samples,['0','1'],['2','3'],[m])['metrics'][0]['within_group']
        self.assertEqual(r['excluded_groups'],{'ambiguous_group_namespace':1})
        samples[1]['producer']='worker';samples[1]['policy_version']='new'
        r=population_comparisons.compare(samples,['0','1'],['2','3'],[m])['metrics'][0]['within_group']
        self.assertEqual(r['excluded_groups'],{'conflicting_recorded_context':1})

    def test_associations_deduplicate_overlap_and_nonfinite_values_fail(self):
        samples=self.samples();a=self.measure({str(i):i for i in range(6)});b=self.measure({str(i):-i for i in range(6)});b['monitor']['id']='n'
        r=population_comparisons.compare(samples,['0','1','2','3'],['2','3','4','5'],[a,b])
        self.assertEqual(r['associations'][0]['n'],6);self.assertEqual(r['associations'][0]['rho'],-1)
        a['values']['0']['value']=float('nan')
        with self.assertRaises(InputError):population_comparisons.compare(samples,['0'],['1'],[a])

    def test_declared_samples_sharing_a_source_are_counted_and_disclosed(self):
        samples=self.samples();samples[0]['run_id']='same';samples[1]['run_id']='same';samples[2]['run_id']='other'
        m=self.measure({'0':1,'1':1,'2':2})
        result=population_comparisons.compare(samples,['0','1'],['2','3'],[m])
        self.assertEqual(result['source_coverage'],{'sample_members':4,'source_bound_samples':3,
            'unique_source_rollouts':2,'samples_without_source':1,
            'shared_sources':[{'run_id':'same','sample_ids':['0','1']}]})
        self.assertEqual(result['metrics'][0]['focus']['population'],2)


if __name__=='__main__':unittest.main()
