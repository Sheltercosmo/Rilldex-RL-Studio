from copy import deepcopy
import json
import unittest

from tracker import measurement_reviews as review, monitoring as monitoring, work_subjects
from tracker.schema import InputError, digest, dumps
from tests import test_work_visit_monitors as fixtures


class MeasurementReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = fixtures.WorkVisitTests(); self.fixtures.setUp(); self.addCleanup(self.fixtures.doCleanups)
        self.store = self.fixtures.store
        self.a, _, self.graph, _ = self.fixtures.source(('A','B','A'),step=1)
        self.b, _, _, _ = self.fixtures.source(('A','B','C'),step=2)
        self.c, _, _, _ = self.fixtures.source(('A',None,'B'),step=3)
        self.monitor = self.fixtures.monitor(self.graph['observer']); monitoring.sync(self.store)
        self.request = dict(monitor_id=self.monitor['id'],run_ids=[self.a['id'],self.b['id'],self.c['id']],size=100,seed='frozen')

    def label(self, sample, cid, label='taken', reviewer='Reviewer A', **changes):
        case = review.case_view(self.store,sample['id'],cid,reviewer)
        e = next(e for e in case['source_events'] if e['text'])
        value = dict(sample_id=sample['id'],case_id=cid,reviewer=reviewer,reviewer_role='not_declared',label=label,
            note='Authored test judgment; not independent semantic evidence.',
            citations=[dict(event_id=e['id'],start=0,end=len(e['text']))],supersedes=(case['annotation'] or {}).get('id'))
        value.update(changes); return value

    def test_frame_includes_unknowns_and_resampling_is_reproducible(self):
        sample = review.create(self.store,self.request)
        self.assertEqual(sample['frame_cases'],5); self.assertEqual(sample['sample_size'],5)
        raw = review.load(self.store,sample['id'])
        self.assertEqual([sum(r['prediction'] is v for r in raw['frame']) for v in (True,False,None)],[1,3,1])
        again = review.create(self.store,{**self.request,'run_ids':self.request['run_ids'][::-1]})
        self.assertEqual(again['id'],sample['id'])
        smaller = review.create(self.store,{**self.request,'size':2})
        self.assertEqual([c['id'] for c in smaller['cases']],[c['id'] for c in sample['cases'][:2]])
        self.assertNotIn('prediction',json.dumps(sample))

    def test_prediction_is_hidden_until_this_reviewer_records_a_judgment(self):
        sample = review.create(self.store,self.request); cid = sample['cases'][0]['id']
        self.assertNotIn('prediction',review.case_view(self.store,sample['id'],cid,'Reviewer A'))
        result = review.receive(self.store,self.label(sample,cid))
        self.assertIn('prediction',result['case'])
        self.assertNotIn('prediction',review.case_view(self.store,sample['id'],cid,'Reviewer B'))
        self.assertEqual(len(result['case']['annotation']['citations']),1)

    def test_disagreements_unknowns_and_eligibility_disputes_are_separate(self):
        sample = review.create(self.store,self.request); raw = review.load(self.store,sample['id'])
        positive = next(r for r in raw['frame'] if r['prediction'] is True)
        negatives = [r for r in raw['frame'] if r['prediction'] is False]
        unknown = next(r for r in raw['frame'] if r['prediction'] is None)
        for row, reference in [(positive,'not_taken'),(negatives[0],'taken'),(negatives[1],'not_opportunity'),(negatives[2],'unknown'),(unknown,'taken')]:
            review.receive(self.store,self.label(sample,row['id'],reference))
        stats = review.public(self.store,sample['id'])['reviewers'][0]
        self.assertEqual((stats['false_positive'],stats['false_negative'],stats['comparable'],stats['agreement']),(1,1,2,0))
        self.assertEqual((stats['reference_unknown'],stats['eligibility_disputes'],stats['prediction_unknown_with_decidable_reference']),(1,1,1))
        review.receive(self.store,self.label(sample,positive['id'],'taken','Reviewer B'))
        self.assertEqual(len(review.public(self.store,sample['id'])['reviewers']),2)

    def test_revision_is_append_only_idempotent_and_rejects_stale_writes(self):
        sample = review.create(self.store,self.request); cid = sample['cases'][0]['id']
        first = self.label(sample,cid); saved = review.receive(self.store,first)
        self.assertEqual(review.receive(self.store,first)['annotation_id'],saved['annotation_id'])
        second = self.label(sample,cid,'unknown'); review.receive(self.store,second)
        with self.assertRaisesRegex(InputError,'reload'):
            review.receive(self.store,{**first,'note':'Stale edit'})
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM measurement_review_labels').fetchone()[0],2)
        self.assertEqual(review.case_view(self.store,sample['id'],cid,'Reviewer A')['annotation']['label'],'unknown')

    def test_sample_stays_pinned_after_work_review_changes_the_live_measurement(self):
        sample = review.create(self.store,self.request)
        old = review.load(self.store,sample['id'])
        document = work_subjects.template(self.graph)['document']; document['bindings'][-1]['status']='unresolved'; document['bindings'][-1]['subject_id']=None
        work_subjects.receive(self.store,document); monitoring.sync(self.store)
        self.assertEqual(review.load(self.store,sample['id']),old)
        cid = next(c['id'] for c in sample['cases'] if c['run_id'] == self.a['id'])
        self.assertFalse(review.case_view(self.store,sample['id'],cid)['freshness']['current_measurement'])
        self.assertNotEqual(review.create(self.store,self.request)['id'],sample['id'])

    def test_rejects_outside_cases_bad_citations_and_non_opportunity_monitors(self):
        sample = review.create(self.store,self.request); cid = sample['cases'][0]['id']
        for change in ({'case_id':'outside'}, {'citations':[dict(event_id='unknown',start=0,end=1)]}, {'citations':[]}, {'label':[]}):
            with self.subTest(change=change),self.assertRaises(InputError):
                review.receive(self.store,self.label(sample,cid,**change) if 'case_id' not in change else {**self.label(sample,cid),**change})
        count = self.fixtures.monitor(self.graph['observer'],'work_return_visits')
        with self.assertRaisesRegex(InputError,'analysis rate'):
            review.create(self.store,{**self.request,'monitor_id':count['id']})

    def test_frame_and_label_tampering_are_detected(self):
        sample = review.create(self.store,self.request); cid = sample['cases'][0]['id']
        review.receive(self.store,self.label(sample,cid))
        with self.store.connect() as db:
            db.execute("UPDATE measurement_review_labels SET document=json_set(document,'$.label','not_taken')")
        with self.assertRaisesRegex(InputError,'label content changed'): review.public(self.store,sample['id'])

    def test_recorded_state_excludes_later_edits_and_deliveries(self):
        from tests.test_investigation_process import captured
        run = captured(); checks = [e for e in run['events'] if e['kind'] == 'feedback']
        source = [e for e in run['events'] if e['index'] <= checks[2]['index']]
        state = review.captured_prefix(run,source)
        self.assertEqual([s['id'] for s in state['snapshots']],['initial','fixed'])
        self.assertEqual(len(state['checks']),2); self.assertEqual(len(state['edits']),1)
        self.assertEqual(state['deliveries'],[])

    def test_containing_event_cannot_expose_future_units(self):
        from tests.test_work_subjects import fixture
        run, graph, units = fixture(('First idea.','Check it 🧪.','Future result.'),one_event=True)
        event_id = units[0]['source']['event_id']
        event_node = next(n['id'] for n in graph['nodes'] if n['kind']=='event' and n['properties']['id']==event_id)
        unit_nodes = [n['id'] for n in graph['nodes'] if n['kind']=='unit' and n['properties']['id'] in {u['id'] for u in units[:2]}]
        source, witness, focus = review.source_evidence(run,graph,{'node_ids':[event_node,*unit_nodes]})
        visible = next(e['text'] for e in source if e['id']==event_id)
        self.assertEqual(visible,'First idea.\nCheck it 🧪.')
        self.assertEqual([p['text'] for p in focus],['First idea.','Check it 🧪.'])
        self.assertEqual(witness,{event_id})
        for p in focus: self.assertEqual(visible[p['start']:p['end']],p['text'])
        full_source, _, full_focus = review.source_evidence(run,graph,{'node_ids':[event_node]})
        self.assertIn('Future result.',next(e['text'] for e in full_source if e['id']==event_id))
        self.assertEqual(len(full_focus),1)

    def test_new_samples_pin_entry_scope_and_legacy_samples_keep_their_source(self):
        run,_,graph,units=self.fixtures.source(('A','B','A','A'),step=4)
        monitoring.sync(self.store)
        sample=review.create(self.store,{**self.request,'run_ids':[run['id']]})
        raw=review.load(self.store,sample['id'])
        row=next(r for r in raw['frame'] if r['prediction'] is True);cid=row['id']
        view=review.case_view(self.store,sample['id'],cid)
        self.assertEqual(view['entry_scope']['entry_unit_id'],units[2]['id'])
        self.assertNotIn(units[3]['source']['event_id'],[e['id'] for e in view['source_events']])
        with self.assertRaisesRegex(InputError,'outside'):
            review.receive(self.store,self.label(sample,cid,citations=[
                dict(event_id=units[3]['source']['event_id'],start=0,end=1)]))
        legacy=deepcopy(raw);legacy['schema']=review.LEGACY_VERSION;legacy.pop('evidence_scopes')
        lid='review-sample-'+digest(legacy)
        with self.store.connect() as c:
            c.execute('INSERT INTO measurement_review_samples VALUES (?,?,?,?)',(lid,legacy['monitor_id'],dumps(legacy),'authored-test'))
        old=review.case_view(self.store,lid,cid)
        self.assertNotIn('entry_scope',old)
        self.assertIn(units[3]['source']['event_id'],[e['id'] for e in old['source_events']])
        self.assertEqual(review.load(self.store,lid),legacy)


if __name__ == '__main__': unittest.main()
