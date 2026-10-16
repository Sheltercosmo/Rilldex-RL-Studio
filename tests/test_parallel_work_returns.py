"""Ordering/measurement controls, not semantic-label accuracy evaluation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import graph_store as gs, work_subjects as ws, work_navigation as wn, work_visits as wv
from tracker import work_order, analysis_metrics as am, investigation_plans as plans
from tracker import monitoring, monitor_evidence
from tracker.schema import InputError, digest
from tracker.store import Store
from tracker.adapters import normalize
from tracker.portable import chat_document
from tests.test_work_subjects import annotation


def fixture(reverse=False, batches=1):
    calls=[{'id':name,'type':'function','function':{'name':'search','arguments':json.dumps({'query':name})}}
           for name in ('first date','second date')]
    if reverse: calls.reverse()
    messages=[{'role':'user','content':'Which happened first?'},
              {'role':'assistant','content':'Compare the two event dates.'}]
    for batch in range(batches):
        native=deepcopy(calls)
        for call in native:call['id']+='-'+str(batch)
        messages.extend([{'role':'assistant','content':'','tool_calls':native},
            {'role':'tool','tool_call_id':native[0]['id'],'content':'A date.'},
            {'role':'tool','tool_call_id':native[1]['id'],'content':'Another date.'}])
    messages.append({'role':'assistant','content':'The first event happened earlier.'})
    run=normalize(chat_document(messages))[0]
    units=[]
    for e in run['events']:
        if e.get('actor')!='agent' or not e['text'].strip():continue
        units.append(dict(id='u'+e['id'],actor='agent',kind='action' if e['kind']=='action' else 'semantic',
            status='selected',activity='execute' if e['kind']=='action' else 'reason',
            source=dict(event_id=e['id'],start=0,end=len(e['text']),text=e['text'],source_pointer=e['source_pointer'])))
    return run,units


def graph(run, units, names=('A','B','C','A'), modify=None):
    base=gs.build(run,dict(observer=dict(id='authored-parallel',label='Authored ordering control'),
        document=dict(source_hash=digest(run),units=units,relations=[])))
    d=annotation(base,units,names)
    if modify:modify(d)
    return ws.fork(base,d)


class ParallelReturnTests(unittest.TestCase):
    def test_bracketed_parallel_work_preserves_order_uncertainty_and_agrees_across_views(self):
        run,units=fixture();g=graph(run,units);frozen=deepcopy(g)
        legacy=wn.project(g);new=wn.project(g,recurrence_order=work_order.VERSION)
        metrics=wv.project(g,recurrence_order=work_order.VERSION)
        self.assertEqual(legacy['counts']['returned'],0);self.assertEqual(new['counts']['returned'],1)
        self.assertEqual(sum(not v['order_known'] for v in new['visits']),2)
        self.assertEqual(metrics['counts']['returned'],1)
        self.assertEqual(metrics['metrics'],dict(value=1.,numerator=1,denominator=1,opportunities=3,unknown=2))
        episode=new['episodes'][0];self.assertEqual(episode['ordering']['status'],'bracketed_parallel')
        self.assertEqual(episode['ordering']['parallel_groups'][0]['mutual_order'],'unknown')
        self.assertEqual({c['unit_id'] for c in episode['cards']},{u['id'] for u in units})
        self.assertEqual(len(episode['edge_ids']),4)
        self.assertEqual(g,frozen);self.assertEqual(wn.project(g),legacy)

    def test_sibling_serialization_order_does_not_change_return(self):
        results=[]
        for reverse in (False,True):
            run,units=fixture(reverse);out=wv.project(graph(run,units),recurrence_order=work_order.VERSION)
            results.append((out['counts'],out['metrics']))
        self.assertEqual(*results)

    def test_multiple_parallel_batches_can_be_bracketed(self):
        run,units=fixture(batches=2)
        out=wn.project(graph(run,units,('A','B','C','D','E','A')),recurrence_order=work_order.VERSION)
        self.assertEqual(out['counts']['returned'],1)
        self.assertEqual(len(out['episodes'][0]['ordering']['parallel_groups']),2)

    def test_source_message_index_alone_marks_siblings_unordered(self):
        run,units=fixture()
        for e in run['events']:
            if e['kind']=='action':e.pop('parent_id',None);e['source_message_index']=2
        out=wn.project(graph(run,units),recurrence_order=work_order.VERSION)
        self.assertEqual(out['counts']['returned'],1)
        self.assertEqual(sum(not v['order_known'] for v in out['visits']),2)

    def test_missing_work_membership_and_annotation_gaps_stay_unknown(self):
        for mode in ('unresolved','unreviewed','gap'):
            run,units=fixture();names=('A',None,'C','A')
            if mode=='gap':units.pop(1);names=('A','C','A')
            def modify(d):
                if mode=='unreviewed':d['bindings'].pop(1)
            out=wn.project(graph(run,units,names,modify),recurrence_order=work_order.VERSION)
            self.assertEqual(out['counts']['returned'],0);self.assertEqual(out['counts']['interrupted'],1)

    def test_incomplete_unidentified_or_crossing_batch_stays_unknown(self):
        for mode in ('missing_member','no_identity','crossing'):
            run,units=fixture();events=[e for e in run['events'] if e['kind']=='action']
            if mode=='missing_member':
                for e in events:e['batch_size']=3
            elif mode=='no_identity':
                for e in events:e.pop('parent_id',None);e.pop('source_message_index',None);e['batch_size']=2
            else:events[0]['index']=0  # A group now crosses the earlier recurrence endpoint.
            out=wn.project(graph(run,units),recurrence_order=work_order.VERSION)
            self.assertEqual(out['counts']['returned'],0)
            self.assertTrue(out['episodes'][0]['ordering']['blockers'])

    def test_unordered_same_target_predecessor_is_not_replaced_by_an_older_convenient_witness(self):
        run,units=fixture();out=wn.project(graph(run,units,('A','B','A','A')),recurrence_order=work_order.VERSION)
        self.assertEqual(out['counts']['returned'],0)
        self.assertTrue(all(e['category']=='interrupted' for e in out['episodes']))

    def test_reviewed_no_target_parallel_contributions_are_resumption_not_return(self):
        run,units=fixture()
        def modify(d):
            for r in d['bindings'][1:3]:r['status']='not_applicable'
        out=wv.project(graph(run,units,('A',None,None,'A'),modify),recurrence_order=work_order.VERSION)
        self.assertEqual(out['counts']['resumed'],1);self.assertEqual(out['metrics']['opportunities'],0)

    def test_live_metrics_and_receipts_keep_policies_separate(self):
        run,units=fixture();g=graph(run,units)
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db.sqlite');store.add([run])
            with store.connect() as c:gs.save(c,g)
            monitors={key:monitoring.create(store,dict(name=key,kind='analysis',observer=g['observer'],analysis={'measure':key}))
                for key in ('work_return_visits','work_return_visits_parallel','work_switch_return_fraction_parallel')}
            monitoring.sync(store)
            values={key:monitoring.values(store,m['id'],{run['id']})[run['id']] for key,m in monitors.items()}
            self.assertEqual(values['work_return_visits']['value'],0)
            self.assertEqual(values['work_return_visits_parallel']['value'],1)
            for key,value in values.items():
                evidence=monitor_evidence.read(store,value['id'])
                self.assertEqual(evidence['explanation']['value'],value['value'])
            new=values['work_return_visits_parallel'];old=values['work_return_visits']
            self.assertNotEqual(new['analysis']['plan_id'],old['analysis']['plan_id'])
            output=plans.read_output(store,new['analysis']['output_id'])
            with self.assertRaises(InputError):am.measure(output,am.catalog()['work_return_visits'])
            ratio=monitor_evidence.read(store,values['work_switch_return_fraction_parallel']['id'])
            self.assertTrue(all(c['recurrence_order']==work_order.VERSION for c in ratio['explanation']['analysis_cases']))

    def test_policy_parameters_are_explicit_and_validated(self):
        run,units=fixture();g=graph(run,units)
        for fn in (wn.project,wv.project,ws.project):
            with self.assertRaises(InputError):fn(g,recurrence_order='guess-parallel-order')
        spec=am.catalog()['work_return_visits_parallel']
        node=am.projection_plan(spec,run['id'],digest(run),g['id'])['nodes'][-1]
        self.assertEqual(node['params']['recurrence_order'],work_order.VERSION)

    def test_real_retained_trace_changes_projection_only(self):
        path=Path(__file__).resolve().parents[1]/'research/pair-work-grouping-2026-10-12/completion-pilot/graph.json'
        raw=path.read_bytes();g=json.loads(raw)
        out=wn.project(g,target_relations='contribution-scope-pairs/2',recurrence_order=work_order.VERSION)
        self.assertEqual(out['counts']['returned'],1);self.assertEqual(out['counts']['interrupted'],0)
        self.assertEqual(wn.project(g)['counts']['returned'],0)
        visit=wv.project(g,recurrence_order=work_order.VERSION)
        self.assertEqual(visit['metrics'],dict(value=.5,numerator=1,denominator=2,opportunities=4,unknown=2))
        self.assertEqual(path.read_bytes(),raw)


if __name__=='__main__':unittest.main()
