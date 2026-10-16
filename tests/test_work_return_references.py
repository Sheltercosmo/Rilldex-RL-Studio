"""Authored structural/measurement controls, not automatic semantic evaluation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tracker import work_subjects as ws, work_return_references as refs
from tracker import graph_store as gs, investigation_plans as plans, monitoring, monitor_evidence
from tracker.schema import InputError, digest
from tracker.store import Store
from tests.test_work_subjects import fixture, annotation
from tests.test_work_route_context import edge, rehash, example


def graph(names=('A','B','A'), links=((2,0,'revises'),), metadata=None):
    run, g, units = fixture(tuple('Contribution '+str(i)+'.' for i in range(len(names))))
    if metadata:
        run['metadata'].update(metadata)
        run['id']=digest(run)[:24]
        g = gs.build(run,dict(observer=dict(id='authored-units',label='Authored units'),
            document=dict(source_hash=digest(run),units=units,relations=[])))
    for a,b,kind in links:
        edge(g, units[a]['id'], units[b]['id'], kind, cutoff=deepcopy(units[a]['source']), basis='Authored control')
    g = rehash(g)
    return run, ws.fork(g,annotation(g,units,names)), units


def query(scope='same_work_history', types=('revises',)):
    return {**refs.DEFAULT_QUERY, 'referent_scope':scope, 'relation_types':list(types)}


class WorkReturnReferenceTests(unittest.TestCase):
    def test_one_return_counts_once_with_multiple_units_or_relationships(self):
        _,g,_=graph(('A','A','B','A','A'),((3,0,'revises'),(4,1,'revises')))
        before=deepcopy(g);out=refs.evaluate(g,query())
        self.assertEqual(g,before);self.assertEqual(out['value'],1)
        self.assertEqual(len(out['records']),1);self.assertEqual(len(out['records'][0]['references']),2)
        self.assertTrue(set('unit-'+str(i) for i in range(1,5))<=set(out['records'][0]['node_ids']))

    def test_prior_same_work_intervening_and_any_prior_have_distinct_meanings(self):
        _,g,_=graph(('A','B','A','C','A'),((4,0,'revises'),(4,3,'uses_evidence'),(4,1,'responds_to')))
        for scope,types,want in [('same_work_history',('revises',),1),('intervening_work',('revises',),0),
                ('intervening_work',('uses_evidence',),1),('intervening_work',('responds_to',),0),
                ('all_prior_work',('responds_to',),1)]:
            self.assertEqual(refs.evaluate(g,query(scope,types))['value'],want)

    def test_current_visit_internal_relation_is_not_an_earlier_work_reference(self):
        _,g,_=graph(('A','B','A','A'),((3,2,'revises'),))
        out=refs.evaluate(g,query('all_prior_work'))
        self.assertEqual(out['value'],0);self.assertEqual(out['records'][0]['status'],'not_established')

    def test_unknown_work_gap_cannot_manufacture_return_opportunity(self):
        _,g,_=graph(('A',None,'A'))
        out=refs.evaluate(g,query());self.assertEqual(out['records'],[])
        self.assertEqual(out['coverage']['unresolved_work_switches'],1)
        self.assertEqual(out['value'],0)  # Recorded-witness count, not behavioral absence.

    def test_no_profile_is_unavailable_not_zero(self):
        _,g,_=fixture();out=refs.evaluate(g,query())
        self.assertFalse(out['available']);self.assertIsNone(out['value'])

    def test_namespace_preserved_and_unsupported_relation_rejected(self):
        _,g,_=graph(links=((2,0,'reasoningflow:backref:reason:execute'),))
        self.assertEqual(refs.evaluate(g,query())['value'],0)
        out=refs.evaluate(g,query(types=('reasoningflow:backref:reason:execute',)))
        self.assertEqual(out['value'],1)
        with self.assertRaises(InputError):refs.validate(query(types=('imagined_goal_drift',)))
        with self.assertRaises(InputError):refs.validate(query(types=('revises','revises')))

    def test_future_evidence_cannot_supply_a_match(self):
        _,g,units=graph(('A','B','A','C'))
        selected=next(e for e in g['edges'] if e['type']=='revises')
        selected['properties']['context_evidence']=[deepcopy(units[3]['source'])]
        out=refs.evaluate(rehash(g),query())
        self.assertEqual(out['value'],0);self.assertEqual(out['coverage']['rejected_relationships'],1)

    def test_feedback_reference_keeps_actual_response_and_origin_action(self):
        _,g,units=example()
        # Plan -> inspection action -> return to the plan while assessing feedback.
        g['semantic_context'].pop('work_subjects');g=rehash(g)
        g=ws.fork(g,annotation(g,units,('A','B','A','A','C','D')))
        out=refs.evaluate(g,query('intervening_work',('assesses',)))
        self.assertEqual(out['value'],1)
        witness=out['records'][0]['references'][0]
        self.assertEqual(set(witness['node_ids']),{'unit-1','unit-2','response-unit'})
        self.assertEqual(len(witness['edge_ids']),2)

    def test_preflight_cache_saved_count_and_unestablished_case_reconcile(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'test.sqlite');run,g,_=graph(('A','B','A','B'),((2,0,'revises'),))
            store.add([run])
            with store.connect() as c:gs.save(c,g)
            monitor=monitoring.create(store,dict(name='Return reference control',kind='analysis',observer=g['observer'],
                analysis={'measure':'work_return_references','query':query()}))
            plan=dict(schema=plans.VERSION,nodes=[dict(name='q',op='work_return_references',inputs=[],
                params=dict(run_id=run['id'],source_hash=g['source_hash'],graph_id=g['id'],query=query()))])
            check=plans.preflight(store,plan);self.assertFalse(check['persisted'])
            a=plans.execute(store,plan);b=plans.execute(store,plan)
            self.assertEqual(a['id'],b['id']);self.assertEqual(b['execution']['cache_hits'],1)
            monitoring.sync(store)
            values=monitoring.values(store,monitor['id'],{run['id']})
            value=values[run['id']];self.assertEqual(value['value'],1)
            receipt=monitor_evidence.read(store,value['id'])
            self.assertEqual(len(receipt['explanation']['analysis_cases']),2)
            self.assertEqual([c['taken'] for c in receipt['explanation']['analysis_cases']],[True,None])
            self.assertEqual(receipt['explanation']['coverage']['returns_without_established_reference'],1)

    def test_query_order_is_canonical_and_future_context_direction_is_preserved(self):
        self.assertEqual(refs.validate(query(types=('revises','assesses'))),refs.validate(query(types=('assesses','revises'))))
        _,g,_=graph(links=((0,2,'revises'),))
        out=refs.evaluate(g,query());self.assertEqual(out['value'],0)
