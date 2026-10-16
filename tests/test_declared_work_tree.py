from copy import deepcopy
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError, digest
from tracker.graph_store import build
from tracker.work_hierarchy import build as hierarchy
from tracker.declared_work_tree import capture


def fixture():
    lines=['Make artifact','sequence: Build, Check','Build','Act: edit','Act: failure','Check','Act: done']
    def ref(i,t):
        a=lines[i-1].index(t);return dict(event_id='e'+str(i),start=a,end=a+len(t),text=t)
    return dict(trajectory_format='chat-messages/1',messages=[dict(role='assistant',content=t) for t in lines],
        declared_work_tree=dict(schema='declared-work-tree/1',producer='authored contract control',nodes=[
            dict(id='a',kind='goal',label=lines[0],parent_id=None,evidence=ref(1,lines[0])),
            dict(id='b',kind='sequence',label='sequence',parent_id='a',evidence=ref(2,'sequence')),
            dict(id='c',kind='goal',label='Build',parent_id='b',evidence=ref(2,'Build')),
            dict(id='d',kind='goal',label='Check',parent_id='b',evidence=ref(2,'Check'))],records=[
            dict(node_id='c',kind='entered',evidence=ref(3,'Build')),
            dict(node_id='c',kind='operation',evidence=ref(4,'Act: edit')),
            dict(node_id='c',kind='reported_failed',evidence=ref(5,'Act: failure')),
            dict(node_id='d',kind='entered',evidence=ref(6,'Check')),
            dict(node_id='d',kind='reported_complete',evidence=ref(7,'Act: done'))]))


class DeclaredWorkTreeTests(unittest.TestCase):
    def test_nested_structure_uses_same_graph_without_semantic_units_or_parent_success(self):
        run=normalize(fixture())[0];g=build(run);saved=digest(g);out=hierarchy(g)
        self.assertEqual(digest(g),saved)
        self.assertEqual(out['declared_tree'],dict(roots=1,nodes=4,goals=3,records=5))
        states={n['label']:n['state'] for n in out['nodes']}
        self.assertEqual(states['Make artifact'],'Expanded into subgoals')
        self.assertEqual(states['Build'],'Reported failed');self.assertEqual(states['Check'],'Reported complete')
        self.assertFalse(any(n['kind']=='unit' for n in g['nodes']))
        self.assertEqual(out['counts']['linked_actions'],0)

    def test_cutoff_withholds_future_visits_and_reports(self):
        g=build(normalize(fixture())[0]);early=hierarchy(g,'e2');later=hierarchy(g,'e4')
        self.assertEqual({n['label']:n['state'] for n in early['nodes']}['Build'],'No recorded visit')
        b=next(n for n in later['nodes'] if n['label']=='Build')
        self.assertEqual(b['operation_count'],1);self.assertIsNone(b['last_report'])
        self.assertEqual({n['label']:n['state'] for n in later['nodes']}['Check'],'No recorded visit')

    def test_rejects_misbound_span_and_unquoted_label(self):
        for field,value in [('label','Other'),('evidence',dict(event_id='e1',start=0,end=5,text='wrong'))]:
            d=fixture();d['declared_work_tree']['nodes'][0][field]=value
            with self.subTest(field=field),self.assertRaises(InputError):normalize(d)

    def test_rejects_missing_parent_duplicate_ids_unknown_states_and_records_before_declaration(self):
        for case in ('parent','duplicate','unknown','early'):
            d=fixture();c=d['declared_work_tree']
            if case=='parent':c['nodes'][1]['parent_id']='absent'
            if case=='duplicate':c['nodes'].append(deepcopy(c['nodes'][0]))
            if case=='unknown':c['records'][0]['kind']='verified_success'
            if case=='early':c['records'][0]['evidence']=dict(event_id='e1',start=0,end=4,text='Make')
            with self.subTest(case=case),self.assertRaises(InputError):normalize(d)

    def test_rejects_cross_trajectory_and_copied_evidence(self):
        for case in ('trajectory','copied'):
            run=normalize(fixture())[0]
            if case=='trajectory':run['events'][2]['trajectory_id']='other'
            else:run['events'][2]['copied_context']=True
            with self.subTest(case=case),self.assertRaises(InputError):capture(run)

    def test_controls_do_not_assert_concurrency_or_execution_dependencies(self):
        d=fixture();d['messages'][1]['content']='parallel: Build, Check';nodes=d['declared_work_tree']['nodes']
        nodes[1].update(kind='parallel',label='parallel');nodes[1]['evidence'].update(text='parallel',end=8)
        g=build(normalize(d)[0]);out=hierarchy(g)
        self.assertIn('concurrency not established',next(n for n in out['nodes'] if n['control'])['state'])
        self.assertFalse(any(e['type'] in {'precedes','requires'} for e in out['links']))

    def test_later_work_keeps_old_report_but_does_not_leave_completed_badge(self):
        d=fixture();d['messages'].append(dict(role='assistant',content='Act: recheck'))
        d['declared_work_tree']['records'].append(dict(node_id='d',kind='operation',evidence=dict(event_id='e8',start=0,end=12,text='Act: recheck')))
        d['declared_work_tree']['records'][-1]['evidence']['end']=len('Act: recheck')
        out=hierarchy(build(normalize(d)[0]));n=next(n for n in out['nodes'] if n['label']=='Check')
        self.assertEqual(n['state'],'Work after earlier report');self.assertEqual(n['last_report']['kind'],'reported_complete')

    def test_legacy_graph_unchanged_without_optional_capture(self):
        d=fixture();del d['declared_work_tree'];g=build(normalize(d)[0])
        self.assertFalse(any(n['kind'].startswith('declared_work') for n in g['nodes']))
        self.assertNotIn('declared_tree',hierarchy(g))

    def test_activity_without_entry_marker_is_observed_not_unvisited(self):
        d=fixture();d['declared_work_tree']['records']=[r for r in d['declared_work_tree']['records'] if r['kind']=='operation']
        out=hierarchy(build(normalize(d)[0]));n=next(n for n in out['nodes'] if n['label']=='Build')
        self.assertEqual(n['state'],'Recorded work')

    def test_one_source_operation_can_have_two_scope_links_without_two_occurrences(self):
        d=fixture();r=deepcopy(d['declared_work_tree']['records'][1]);r['node_id']='d';d['declared_work_tree']['records'].append(r)
        out=hierarchy(build(normalize(d)[0]));ops=[r for n in out['nodes'] for r in n['records'] if r['kind']=='operation']
        self.assertEqual(len(ops),2);self.assertNotEqual(ops[0]['id'],ops[1]['id']);self.assertEqual(ops[0]['occurrence_id'],ops[1]['occurrence_id'])

    def test_conflicting_simultaneous_reports_stay_conflicting(self):
        d=fixture();r=deepcopy(d['declared_work_tree']['records'][-1]);r['kind']='reported_failed';d['declared_work_tree']['records'].append(r)
        out=hierarchy(build(normalize(d)[0]));n=next(n for n in out['nodes'] if n['label']=='Check')
        self.assertEqual(n['state'],'Conflicting reports')

    def test_control_root_duplicate_record_and_malformed_ref_are_rejected(self):
        for case in ('control_root','duplicate_record','bad_event','bad_kind'):
            d=fixture();v=d['declared_work_tree']
            if case=='control_root':v['nodes'][1]['parent_id']=None
            if case=='duplicate_record':v['records'].append(deepcopy(v['records'][0]))
            if case=='bad_event':v['records'][0]['evidence']['event_id']=[]
            if case=='bad_kind':v['nodes'][0]['kind']=[]
            with self.subTest(case=case),self.assertRaises(InputError):normalize(d)

    def test_public_example_replays_exact_parentage_and_reports(self):
        import importlib.util
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'research/nested-plan-map-2026-10-13/replay.py'
        spec=importlib.util.spec_from_file_location('nested_example',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        run=normalize(m.document())[0];out=hierarchy(build(run))
        self.assertEqual(out['declared_tree']['nodes'],14)
        self.assertEqual(sum(n['state']=='Reported failed' for n in out['nodes']),2)
        self.assertEqual(sum(n['state']=='Reported complete' for n in out['nodes']),4)


if __name__=='__main__':unittest.main()
