"""Population fidelity and no-inference setup; no semantic accuracy claims."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker import monitoring as m, graph_store, investigation_plans
from tracker.adapters import normalize
from tracker.portable import generation_document
from tracker.schema import InputError, digest
from tracker.store import Store


class QuestionSetupTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'tracker.sqlite')

    def add(self,text='4',**metadata):
        run=normalize(generation_document('Compute 2+2.',text,metadata=metadata))[0]
        self.store.add([run]);return run

    def definition(self,**updates):
        return {'name':'Feedback use','kind':'analysis','observer':'source','analysis':{'measure':'feedback_reference'},**updates}

    def counts(self):
        with self.store.connect() as c:
            names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {name:c.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in names}

    def test_scope_validation_and_legacy_identity(self):
        original=self.definition()
        self.assertEqual(m.validate(original),m.validate({**original,'population':{}}))
        for scope in (None,[],{'reward':1},{'experiment':''},{'split':False},{'environment':'x'*241}):
            with self.subTest(scope=scope),self.assertRaises(InputError):m.validate({**original,'population':scope})
        monitor=m.validate({**original,'population':{'experiment':'a','split':'train'}})
        self.assertFalse(m.in_population(monitor,{'metadata':{'experiment':'a'}}))
        self.assertFalse(m.in_population(monitor,{'metadata':{'experiment':'a','split':'eval'}}))
        self.assertTrue(m.in_population(monitor,{'metadata':{'experiment':'a','split':'train'}}))
        self.assertTrue(m.in_population({'population':{'experiment':'__unassigned__'}},{'metadata':{}}))

    def test_saved_population_controls_values_charts_and_cases(self):
        included=self.add(experiment='a',environment='math',split='train',training_step=1)
        self.add(experiment='a',environment='math',split='eval',training_step=1)
        self.add(experiment='b',environment='math',split='train',training_step=1)
        monitor=m.create(self.store,{'name':'Length','kind':'metric','metric':'agent_text_chars','observer':'source',
            'population':{'experiment':'a','split':'train'}})
        m.sync(self.store)
        result=next(r for r in m.snapshot(self.store)['monitors'] if r['id']==monitor['id'])
        self.assertEqual(result['coverage']['population'],1);self.assertEqual(result['outside_population'],2)
        self.assertEqual([r['run']['id'] for r in m.cases(self.store,monitor['id'])['rows']],[included['id']])
        self.assertEqual(m.cases(self.store,monitor['id'],experiment='b')['rows'],[])
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM monitor_values WHERE monitor_id=?',(monitor['id'],)).fetchone()[0],1)
        m.sync(self.store)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM monitor_values WHERE monitor_id=?',(monitor['id'],)).fetchone()[0],1)

    def test_preflight_is_read_only_and_source_only_reasoning_is_not_ready(self):
        self.add(experiment='a')
        before=self.counts()
        with patch.object(investigation_plans,'execute',side_effect=AssertionError('Must not execute')):
            result=m.preflight(self.store,{'definition':self.definition()})
        self.assertEqual(before,self.counts());self.assertFalse(result['persisted']);self.assertEqual(result['new_model_calls'],0)
        row=result['rows'][0]
        self.assertEqual(row['status'],'missing_inputs')
        self.assertEqual(row['recorded_counts']['native_actions'],0)
        self.assertIn('linked_text_feedback',row['nodes'][0]['missing_evidence'])
        self.assertNotIn('value',row)
        self.assertTrue(any('not applicable' in s for s in row['guidance']))

    def test_missing_observer_preserves_source_population(self):
        self.add(experiment='a');self.add(text='four',experiment='b')
        result=m.preflight(self.store,{'definition':self.definition(observer='not-yet-run',population={'experiment':'a'})})
        self.assertEqual(result['population'],1);self.assertEqual(result['rows'][0]['status'],'needs_observer')
        self.assertIsNone(result['rows'][0]['graph_id'])

    def test_bounded_pages_and_changed_population_rejected(self):
        a=self.add(experiment='a');b=self.add(text='four',experiment='a')
        definition=self.definition()
        first=m.preflight(self.store,{'definition':definition,'limit':1})
        second=m.preflight(self.store,{'definition':definition,'offset':first['next_offset'],'limit':1,'expected_revision':first['revision']})
        self.assertEqual([r['run_id'] for r in first['rows']+second['rows']],sorted([a['id'],b['id']]))
        self.assertIsNone(second['next_offset'])
        self.add(text='The answer is 4.',experiment='a')
        with self.assertRaisesRegex(InputError,'changed'):m.preflight(self.store,{'definition':definition,'expected_revision':first['revision']})
        for extra in ({'limit':0},{'limit':101},{'offset':-1},{'offset':True},{'limit':1.2}):
            with self.assertRaises(InputError):m.preflight(self.store,{'definition':definition,**extra})

    def test_revision_changes_on_observer_arrival(self):
        run=self.add();definition=self.definition(observer='review')
        before=m.preflight(self.store,{'definition':definition})
        graph=graph_store.build(run);graph.pop('id');graph['observer']='review';graph={'id':'graph-'+digest(graph),**graph}
        with self.store.connect() as c:graph_store.save(c,graph)
        after=m.preflight(self.store,{'definition':definition})
        self.assertNotEqual(before['revision'],after['revision'])
        self.assertEqual(after['rows'][0]['status'],'missing_inputs')

    def test_graph_question_reuses_bound_plan_validation(self):
        from tracker.graph_queries import PRESETS
        self.add()
        definition=self.definition(kind='graph',requirement=copy.deepcopy(PRESETS['assessment_of_inspection_feedback']))
        definition.pop('analysis')
        result=m.preflight(self.store,{'definition':definition})
        self.assertEqual(result['rows'][0]['recorded_anchors'],0)
        self.assertEqual(result['rows'][0]['nodes'][0]['operation'],'relation_query')
        definition['requirement']['within_units']=0
        with self.assertRaises(InputError):m.preflight(self.store,{'definition':definition})


if __name__=='__main__':unittest.main()
