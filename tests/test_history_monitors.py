import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tracker import analysis_metrics as am, graph_store as gs, monitoring as m, monitor_evidence
from tracker import history_evidence as he, investigation_plans as plans
from tracker.adapters import normalize
from tracker.schema import InputError
from tracker.store import Store
from test_history_evidence import query, body
from test_tracker import harbor


class HistoryMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite');self.serial=0

    def source(self,approved=True,step=1,action=True):
        self.serial+=1;doc=harbor();doc['session_id']='history-'+str(self.serial)
        result=body(approved) if approved is not None else {'account':'A','items':{'x':{'id':'x'}}}
        import json
        doc['steps']=[{'step_id':1,'source':'user','message':'Use item x for account A.'},
            {'step_id':2,'source':'agent','message':'','tool_calls':[{'tool_call_id':'lookup','function_name':'lookup','arguments':{'account':'A'}}],
             'observation':{'results':[{'source_call_id':'lookup','content':json.dumps(result)}]}}]
        if action:doc['steps'].append({'step_id':3,'source':'agent','message':'','tool_calls':[{'tool_call_id':'use','function_name':'use','arguments':{'account':'A','ids':['x']}}]})
        run=normalize(doc,meta={'experiment':'authored-history-monitor-test','training_step':step})[0]
        self.store.add([run]);return run

    def monitor(self,spec=None,**kw):
        return m.create(self.store,{'name':'Recorded approval at dispatch','kind':'analysis','observer':'source',
            'analysis':{'measure':'history_query','query':spec or query()},**kw})

    def value(self,monitor,run):return m.values(self.store,monitor['id'],{run['id']})[run['id']]

    def test_requires_explicit_valid_query_and_source_observer(self):
        with self.assertRaises(InputError):am.validate({'measure':'history_query'})
        with self.assertRaises(InputError):am.validate({'measure':'returns','query':query()})
        with self.assertRaises(InputError):self.monitor(observer='semantic')
        q=query();q['history']['bindings']=[]
        with self.assertRaises(InputError):self.monitor(q)
        monitor=self.monitor();self.assertEqual(monitor['analysis_definition']['query'],query())

    def test_real_import_sync_receipt_and_reuse(self):
        run=self.source();monitor=self.monitor();out=m.sync(self.store);self.assertEqual(out['errors'],0)
        value=self.value(monitor,run);self.assertEqual((value['value'],value['numerator'],value['denominator'],value['unknown']),(1,1,1,0))
        receipt=monitor_evidence.read(self.store,value['id']);case=receipt['explanation']['analysis_cases'][0]
        self.assertTrue(case['history_evidence']);self.assertEqual(case['status'],'match')
        self.assertTrue(any(e['type']=='same_recorded_json_value' for e in receipt['graph']['edges']))
        plan=plans.read_plan(self.store,receipt['explanation']['plan_id']);self.assertEqual(plan['nodes'][0]['inference_calls'],0)
        self.assertEqual(m.sync(self.store)['inserted'],0)

    def test_unknown_zero_and_inapplicable_have_distinct_denominators(self):
        yes=self.source(True);no=self.source(False);unknown=self.source(None);unselected=self.source(action=False)
        monitor=self.monitor();m.sync(self.store)
        self.assertEqual(self.value(monitor,no)['value'],0)
        self.assertEqual((self.value(monitor,unknown)['value'],self.value(monitor,unknown)['unknown']),(None,1))
        absent=self.value(monitor,unselected);self.assertEqual((absent['value'],absent['opportunities'],absent['unknown']),(None,0,0))
        source=gs.build(unselected);self.assertEqual(absent['graph_id'],source['id'])
        self.assertEqual(monitor_evidence.read(self.store,absent['id'])['explanation']['analysis_cases'],[])
        chart=m.snapshot(self.store)['monitors'][0];b=chart['series'][0]['bins'][0]
        self.assertEqual((b['value'],b['opportunities'],b['unknown_opportunities']),(.5,3,1))
        self.assertEqual(chart['coverage']['query_selection'],{'with_dispatches':3,'without_dispatches':1,'unavailable':0})

    def test_query_edit_creates_new_monitor_and_preserves_old_evidence(self):
        run=self.source();first=self.monitor();m.sync(self.store);old=self.value(first,run)
        q=query();q['checks'][0]['equals']=False
        second=m.create(self.store,{'name':'Changed requirement','kind':'analysis','observer':'source','analysis':{'measure':'history_query','query':q}},replace=first['id'])
        self.assertNotEqual(first['id'],second['id']);m.sync(self.store)
        self.assertEqual(self.value(second,run)['value'],0)
        receipt=monitor_evidence.read(self.store,old['id']);self.assertEqual(receipt['explanation']['value'],1)
        self.assertEqual(receipt['monitor']['analysis']['query'],query())

    def test_query_and_measurement_tampering_fail_receipt_checks(self):
        run=self.source();monitor=self.monitor();m.sync(self.store);value=self.value(monitor,run)
        bad=copy.deepcopy(monitor);bad['analysis_definition']['query']['checks'][0]['equals']=False
        with self.assertRaises(InputError):am.receipt(self.store,value,bad)
        bad=copy.deepcopy(value);bad['unknown']=7
        with self.assertRaisesRegex(InputError,'arithmetic'):am.receipt(self.store,bad,monitor)

    def test_old_version_remains_readable_but_does_not_run_new_definition(self):
        run=self.source();monitor=self.monitor();m.sync(self.store);old=self.value(monitor,run)
        with patch.dict(plans.OPS,history_evidence='history-evidence-query/future'):
            new=self.source(step=2);m.sync(self.store);self.assertEqual(self.value(monitor,new)['status'],'error')
            self.assertEqual(monitor_evidence.read(self.store,old['id'])['explanation']['value'],1)

    def test_new_rollouts_are_materialized_without_recomputing_older_values(self):
        first=self.source();monitor=self.monitor();m.sync(self.store);old=self.value(monitor,first)
        later=self.source(False,step=2);m.sync(self.store)
        self.assertEqual(self.value(monitor,first)['id'],old['id']);self.assertEqual(self.value(monitor,later)['value'],0)
        points=m.snapshot(self.store)['monitors'][0]['series'][0]['points'];self.assertEqual([p['step'] for p in points],[1,2])
