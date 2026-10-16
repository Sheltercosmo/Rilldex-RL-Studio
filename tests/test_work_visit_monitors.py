"""Macro measurement and population controls; no model accuracy claims."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import work_subjects as ws, work_visits as wv, graph_store as gs
from tracker import monitoring as m, monitor_evidence, behavior_distributions as bd, analysis_metrics as am
from tracker.schema import digest, InputError
from tracker.store import Store
from tests.test_work_subjects import fixture, annotation


class WorkVisitTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'test.sqlite')

    def source(self, names=('A','B','A'), step=None, profile=None, task='authored-task'):
        texts=tuple(f'Contribution {i} at authored step {step}.' for i in range(len(names)))
        run,g,units=fixture(texts)
        run['metadata'].update(task_id=task, experiment='authored-work-visits', training_step=step,
                               source_selection={'note':'Authored measurement control, not a training observation.'})
        g=gs.build(run,dict(observer=dict(id='authored-units',label='Authored units'),
            document=dict(source_hash=digest(run),units=units,relations=[])))
        d=annotation(g,units,names)
        if profile:d['profile']=profile
        derived=ws.fork(g,d);self.store.add([run])
        with self.store.connect() as c:gs.save(c,g);gs.save(c,derived)
        return run,g,derived,units

    def monitor(self,observer,measure='work_switch_return_fraction'):
        return m.create(self.store,dict(name='Work visit control',
            kind='analysis',observer=observer,analysis={'measure':measure}))

    def test_shared_profile_is_stable_across_rollouts_and_definition_changes_split_it(self):
        _,_,a,_=self.source(step=1);_,_,b,_=self.source(step=2)
        self.assertEqual(a['observer'],b['observer']);self.assertNotEqual(a['id'],b['id'])
        profile=deepcopy(ws.DEFAULT_PROFILE);profile['definition']+=' Distinct experimental rule.'
        _,_,c,_=self.source(step=3,profile=profile)
        self.assertNotEqual(a['observer'],c['observer'])

    def test_v1_reviews_remain_readable_and_do_not_silently_share_profile(self):
        _,g,units=fixture();d=annotation(g,units);d['schema']=ws.LEGACY_VERSION;d.pop('profile')
        a=ws.fork(g,d);self.assertTrue(a['observer'].startswith('work-review-'))
        self.assertEqual(ws.template(a)['document']['schema'],ws.LEGACY_VERSION)
        self.assertEqual(wv.project(a)['metrics']['value'],.5)

    def test_complete_return_fraction_has_intervening_witnesses(self):
        _,_,g,units=self.source();out=wv.project(g)
        self.assertEqual(out['metrics'],dict(value=.5,numerator=1,denominator=2,opportunities=2,unknown=0))
        returned=next(r for r in out['switches'] if r['value'] is True)
        self.assertTrue(set(u['id'] for u in units)<=set(returned['node_ids']))
        self.assertEqual(len(returned['edge_ids']),3)
        record=next(r for r in out['records'] if r['category']=='returned')
        self.assertEqual(record['edge_ids'],returned['edge_ids'])

    def test_same_target_segmentation_does_not_change_macro_distribution_or_rate(self):
        _,_,a,_=self.source(('A','B','A'),step=1)
        _,_,b,_=self.source(('A','A','A','B','B','A','A'),step=2)
        x,y=wv.project(a),wv.project(b)
        self.assertEqual(x['counts'],y['counts']);self.assertEqual(x['metrics'],y['metrics'])
        self.assertNotEqual(x['coverage']['contributions'],y['coverage']['contributions'])

    def test_unknown_history_cannot_establish_negative(self):
        for seq in [('A',None,'B'),('A',None,'A'),('A','B',None,'A')]:
            _,_,g,_=self.source(seq);out=wv.project(g)
            self.assertIsNone(out['switches'][-1]['value']);self.assertGreater(out['metrics']['unknown'],0)
        _,_,g,_=self.source((None,'A','B','A'));out=wv.project(g)
        self.assertEqual([r['value'] for r in out['switches']],[None,True])

    def test_not_applicable_resumption_is_not_a_switch_and_missing_profile_is_unavailable(self):
        _,g,derived,units=self.source(('A',None,'A'))
        d=ws.template(derived)['document'];d['bindings'][1]['status']='not_applicable'
        out=wv.project(ws.fork(derived,d));self.assertEqual(out['counts']['resumed'],1)
        self.assertEqual(out['metrics']['opportunities'],0);self.assertIsNone(out['metrics']['value'])
        self.assertFalse(wv.project(g)['available'])

    def test_live_monitors_reconcile_cases_preserve_receipts_and_track_revisions(self):
        run,_,g,units=self.source(step=1);monitor=self.monitor(g['observer']);count=self.monitor(g['observer'],'work_return_visits')
        m.sync(self.store);old=m.values(self.store,monitor['id'],{run['id']})[run['id']]
        self.assertEqual(old['value'],.5)
        self.assertEqual(m.values(self.store,count['id'],{run['id']})[run['id']]['value'],1)
        receipt=monitor_evidence.read(self.store,old['id']);self.assertEqual(len(receipt['explanation']['analysis_cases']),2)
        d=ws.template(g)['document'];d['bindings'][-1]['subject_id']='C'
        d['subjects'].append(dict(id='C',label='Different subject',origin_unit_id=units[-1]['id']))
        revised=ws.receive(self.store,d);m.sync(self.store)
        current=m.values(self.store,monitor['id'],{run['id']})[run['id']]
        self.assertEqual(current['value'],0);self.assertEqual(current['graph_id'],revised['graph_id'])
        self.assertEqual(monitor_evidence.read(self.store,old['id'])['explanation']['value'],.5)
        altered=deepcopy(old);altered['denominator']=4
        with self.assertRaises(InputError):am.receipt(self.store,altered,monitor)

    def test_cohort_series_retains_unobserved_step_unknowns_and_exact_visit_links(self):
        a,_,g,_=self.source(('A','B','A'),step=1)
        b,_,_,_=self.source(('A',None,'A'),step=2)
        c,_,_,_=self.source(('A','B','C'),step=3)
        out=bd.snapshot(self.store,lens='work_visits',observer=g['observer'])
        self.assertEqual(out['observed_rollouts'],3);self.assertEqual(len(out['cohorts']),1)
        self.assertEqual([p['step'] for p in out['points']],[1,2,3])
        self.assertTrue(out['comparable']);self.assertTrue(all('graph=' in c['map_url'] and 'work_visit=' in c['map_url'] for c in out['cases']))
        self.assertEqual(out['points'][1]['counts']['unknown'],1)
        self.assertEqual(out['points'][1]['counts']['interrupted'],1)
        monitor=self.monitor(g['observer']);m.sync(self.store)
        values=m.values(self.store,monitor['id'],{a['id'],b['id'],c['id']})
        self.assertIsNone(values[b['id']]['value']);self.assertEqual(values[b['id']]['unknown'],1)

    def test_unplaced_sources_do_not_get_a_training_trend_and_profile_tasks_do_not_pool(self):
        _,_,g,_=self.source();self.source(('A','C'),task='different-task')
        out=bd.snapshot(self.store,lens='work_visits',observer=g['observer'])
        self.assertEqual(len(out['cohorts']),2);self.assertEqual(out['bins'],[])
        self.assertEqual(out['unplaced_rollouts'],1)

    def test_empty_review_stays_unknown_and_latest_revision_wins_tied_timestamps(self):
        run,base,derived,_=self.source(step=1)
        d=ws.template(derived)['document'];d['subjects']=[];d['bindings']=[];empty=ws.fork(derived,d)
        with self.store.connect() as c:
            gs.save(c,empty);c.execute("UPDATE rollout_graphs SET created_at='same'")
        out=bd.snapshot(self.store,lens='work_visits',observer=derived['observer'])
        self.assertEqual(out['distribution']['counts']['unknown'],3)
        self.assertEqual({p['graph_id'] for p in out['points']},{empty['id']})
        monitor=self.monitor(derived['observer']);m.sync(self.store)
        self.assertIsNone(m.values(self.store,monitor['id'],{run['id']})[run['id']]['value'])


if __name__=='__main__':unittest.main()
