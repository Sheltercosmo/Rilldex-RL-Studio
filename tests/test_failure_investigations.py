import copy
import tempfile
import unittest
from pathlib import Path

from tracker import failure_investigations as f, graph_store as gs, behavior_distributions as bd
from tracker.adapters import normalize
from tracker.rollout_metrics import save as save_measurement, source_record, measurement
from tracker.schema import digest, InputError
from tracker.store import Store
from test_tracker import harbor


class FailureInvestigationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.store=Store(Path(tmp.name)/'db.sqlite')

    def run_fixture(self,nonce=0,reward=0,success=None,**metadata):
        raw=harbor();raw['steps'][-1]['message']+=' '+str(nonce)
        run=normalize(raw,'harbor',{'experiment':'test','task_id':'same','training_step':2,**metadata})[0]
        run['outcome']={'recorded_reward':reward}
        if success is not None:run['outcome']['verified_success']=success
        self.store.add([run]);return run

    def test_matching_excludes_future_steps_and_config_changes(self):
        anchor=self.run_fixture(0,training_step=5)
        past=self.run_fixture(1,training_step=4,policy_version='old')
        self.run_fixture(2,training_step=6);self.run_fixture(3,task_id='other',training_step=5)
        self.run_fixture(4,sampling={'temperature':2},training_step=5)
        s=f.snapshot(self.store,run=anchor['id'],steps=3);self.assertEqual({r['id'] for r in s['rows']},{anchor['id'],past['id']})
        self.assertEqual((s['focus_count'],s['reference_count']),(1,1))
        broad=f.snapshot(self.store,run=anchor['id'],scope='configuration',steps=3);self.assertEqual(len(broad['rows']),3)
        self.assertEqual(broad['population']['task_count'],2)
        self.assertEqual(f.snapshot(self.store,run=anchor['id'])['population']['steps'],[5])

    def test_recent_step_window_has_no_inferred_intermediate_steps(self):
        runs=[self.run_fixture(i,training_step=step) for i,step in enumerate([1,50,140,280])]
        s=f.snapshot(self.store,run=runs[-1]['id'],steps=2)
        self.assertEqual({r['metadata']['training_step'] for r in s['rows']},{140,280})

    def test_manual_focus_and_signal_negative_reference_remain_disjoint(self):
        a=self.run_fixture(0,reward=0);b=self.run_fixture(1,reward=0);c=self.run_fixture(2,reward=1);u=self.run_fixture(3,reward=None)
        s=f.snapshot(self.store,run=a['id'],focus=[a['id'],b['id'],a['id']],reference='signal_negative')
        self.assertEqual((s['focus_count'],s['reference_count'],s['excluded_count']),(2,1,1))
        self.assertEqual([r['id'] for r in s['rows'] if r['reference']],[c['id']])
        self.assertIsNone(next(r for r in s['rows'] if r['id']==u['id'])['signal_flag'])

    def test_missing_semantics_and_unknown_success_are_not_zero(self):
        a=self.run_fixture();s=f.snapshot(self.store,run=a['id'])
        success=next(m for m in s['metrics'] if m['id']=='source:recorded_success')
        plan=next(m for m in s['metrics'] if m['id']=='mix:frame')
        self.assertEqual(success['focus']['n'],0);self.assertIsNone(success['focus']['mean'])
        self.assertEqual(plan['focus']['n'],0);self.assertEqual(plan['values'],{})

    def test_means_and_correlations_never_impute(self):
        d=f.describe({'a':{'value':0},'b':{'value':None},'c':{'value':4}},['a','b','c','d'])
        self.assertEqual((d['mean'],d['n'],d['missing']),(2,2,2))
        self.assertEqual(f.spearman([(1,2),(1,2),(3,6),(4,8),(4,8)])['rho'],1)
        self.assertEqual(f.spearman([(1,8),(1,8),(3,6),(4,2),(4,2)])['rho'],-1)
        self.assertIsNone(f.spearman([(1,2)]*8)['rho']);self.assertIsNone(f.spearman([(1,1),(2,2)])['rho'])

    def test_observer_selection_and_graph_evidence_are_bound(self):
        run=self.run_fixture();e=next(e for e in run['events'] if e['actor']=='agent')
        unit={'id':'u','actor':'agent','kind':'semantic','activity':'verify','source':{'event_id':e['id'],'text':e['text'],'start':0,'end':len(e['text'])}}
        graph=gs.build(run,{'document':{'source_hash':digest(run),'units':[unit],'relations':[]},'observer':{'id':'review','label':'Review'}})
        with self.store.connect() as c:gs.save(c,graph)
        bd.sync(self.store)
        s=f.snapshot(self.store,run=run['id'],observer='review');check=next(m for m in s['metrics'] if m['id']=='mix:check')
        self.assertEqual(check['focus']['mean'],1);self.assertIn('graph='+graph['id'],check['values'][run['id']]['map_url'])
        self.assertIn('focus_unit=u',check['values'][run['id']]['map_url'])
        source=f.snapshot(self.store,run=run['id'],observer='source')
        self.assertIsNone(next(m for m in source['metrics'] if m['id']=='mix:check')['focus']['mean'])

    def test_stale_source_measurement_never_enters_comparison(self):
        run=self.run_fixture();r=source_record(run);r.update(source_hash='wrong',observer='review')
        r['metrics']['activity_plan_share']=measurement(1)
        with self.store.connect() as c:save_measurement(c,r)
        s=f.snapshot(self.store,run=run['id'],observer='review')
        self.assertIsNone(next(m for m in s['metrics'] if m['id']=='observation:activity_plan_share')['focus']['mean'])

    def test_independent_monitor_harnesses_keep_separate_series_and_receipts(self):
        from tracker import monitoring
        run=self.run_fixture()
        for observer,value in [('primary',.25),('feedback-review',.75)]:
            r=source_record(run);r.update(observer=observer,observer_label=observer)
            r['metrics']['feedback_assessment_fraction']=measurement(value)
            with self.store.connect() as c:save_measurement(c,r)
        monitor=monitoring.create(self.store,{'name':'Feedback reviewed','kind':'metric','observer':'feedback-review','metric':'feedback_assessment_fraction'})
        monitoring.sync(self.store);s=f.snapshot(self.store,run=run['id'],observer='primary')
        primary=next(m for m in s['metrics'] if m['id']=='observation:feedback_assessment_fraction')
        independent=next(m for m in s['metrics'] if m['id']=='monitor:'+monitor['id'])
        self.assertEqual((primary['focus']['mean'],independent['focus']['mean']),(.25,.75))
        self.assertEqual(independent['protocol'],'feedback-review')
        self.assertIn('value=',independent['values'][run['id']]['map_url'])

    def test_saved_investigation_is_pinned_and_stale_save_rejected(self):
        a=self.run_fixture(0);self.run_fixture(1,reward=1);s=f.snapshot(self.store,run=a['id'])
        request={'controls':s['controls'],'snapshot_id':s['snapshot_id'],'title':'Failure review','hypothesis':'Test the alternative explanation.',
                 'x':'source:agent_text_chars','y':'source:recorded_reward'}
        saved=f.save(self.store,request);self.assertEqual(saved,f.read(self.store,saved['id']))
        self.run_fixture(2,reward=.5)
        self.assertEqual(f.read(self.store,saved['id'])['snapshot']['reference_count'],1)
        with self.assertRaisesRegex(InputError,'changed'):f.save(self.store,request)
        self.assertEqual(len(f.saved(self.store)),1)

    def test_unknown_task_identity_does_not_match_by_default(self):
        a=self.run_fixture(0,task_id=None);self.run_fixture(1,task_id=None)
        s=f.snapshot(self.store,run=a['id']);self.assertEqual(s['reference_count'],0)

    def test_invalid_controls_and_out_of_window_focus_rejected(self):
        a=self.run_fixture();b=self.run_fixture(1,training_step=100)
        for extra in [{'focus':[]},{'focus':[b['id']]},{'steps':0},{'threshold':'nan'},{'scope':'all'},{'limit':999},{'operator':'bad'}]:
            with self.assertRaises(InputError):f.snapshot(self.store,run=a['id'],**extra)

    def test_cap_preserves_anchor_without_duplicate_rows(self):
        a=self.run_fixture(0)
        for i in range(1,6):self.run_fixture(i)
        s=f.snapshot(self.store,run=a['id'],limit=2)
        self.assertEqual(len(s['rows']),2);self.assertEqual(len({r['id'] for r in s['rows']}),2)
        self.assertIn(a['id'],[r['id'] for r in s['rows']]);self.assertEqual(s['population']['truncated'],4)


if __name__=='__main__':unittest.main()
