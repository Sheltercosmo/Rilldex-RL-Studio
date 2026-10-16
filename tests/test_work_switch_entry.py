"""Decision-boundary controls, not independent semantic label validation."""
from copy import deepcopy
import unittest

from tracker import analysis_metrics, work_subjects, work_visits
from tracker.measurement_reviews import source_evidence
from tracker.schema import InputError
from tests.test_work_subjects import fixture, annotation


def case_set(names, *, one_event=True):
    texts=tuple(f'Work {name}, contribution {i}.' for i,name in enumerate(names))
    run, graph, units = fixture(texts,one_event=one_event)
    graph = work_subjects.fork(graph,annotation(graph,units,names))
    spec = analysis_metrics.catalog()['work_switch_return_fraction']
    output = work_visits.project(graph,scope_consistency=spec['scope_consistency'])
    cases = analysis_metrics.measure(output,spec)['cases']
    return run,graph,output,cases,units


class WorkSwitchEntryTests(unittest.TestCase):
    def test_return_evidence_stops_at_entry_not_end_of_visit(self):
        run,graph,output,cases,units = case_set(('A','B','A','A'))
        case = next(c for c in cases if c['taken'] is True); before=deepcopy(output)
        scope = work_visits.entry_evidence(graph,output,case)
        self.assertEqual(scope['entry_unit_id'],units[2]['id'])
        self.assertEqual(scope['excluded_later_unit_ids'],[units[3]['id']])
        self.assertEqual(scope['cutoff'],units[2]['source'])
        source,_,focus = source_evidence(run,graph,case,scope=scope)
        self.assertNotIn(units[3]['source']['text'],'\n'.join(e['text'] for e in source))
        self.assertEqual(focus[-1]['text'],units[2]['source']['text'])
        self.assertEqual(output,before)

    def test_later_continuations_and_switches_do_not_rewrite_earlier_boundary(self):
        prefix = case_set(('A','B','A'))
        longer = case_set(('A','B','A','A','C','A'))
        for i in range(2):
            small = work_visits.entry_evidence(prefix[1],prefix[2],prefix[3][i])
            large = work_visits.entry_evidence(longer[1],longer[2],longer[3][i])
            self.assertEqual(prefix[3][i]['taken'],longer[3][i]['taken'])
            self.assertEqual([s['text'] for s in small['source_refs']],[s['text'] for s in large['source_refs']])
            self.assertEqual((small['cutoff']['start'],small['cutoff']['end']),
                             (large['cutoff']['start'],large['cutoff']['end']))

    def test_a_first_seen_subject_does_not_expose_its_later_continuations(self):
        for one_event in (True,False):
            with self.subTest(one_event=one_event):
                run,graph,output,cases,units = case_set(('A','B','B','A'),one_event=one_event)
                case=cases[0];self.assertIs(case['taken'],False)
                scope=work_visits.entry_evidence(graph,output,case)
                self.assertEqual(scope['entry_unit_id'],units[1]['id'])
                source,_,_=source_evidence(run,graph,case,scope=scope)
                self.assertNotIn(units[2]['source']['text'],'\n'.join(e['text'] for e in source))

    def test_incomplete_history_remains_unknown(self):
        _,graph,output,cases,_ = case_set(('A',None,'B','B'))
        self.assertIsNone(cases[0]['taken'])
        scope=work_visits.entry_evidence(graph,output,cases[0])
        self.assertNotIn('prediction',scope)
        self.assertEqual(output['metrics']['unknown'],1)

    def test_wrong_saved_case_is_rejected(self):
        _,graph,output,cases,_ = case_set(('A','B','A'))
        wrong=deepcopy(cases[0]);wrong['node_ids']=[]
        with self.assertRaisesRegex(InputError,'differs'):
            work_visits.entry_evidence(graph,output,wrong)


if __name__=='__main__':unittest.main()
