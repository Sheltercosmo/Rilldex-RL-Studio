import copy
import unittest
from pathlib import Path

from research.path_selection_audit import compose,evaluate_paths,render,study,ROOT
from tracker.schema import InputError


def edge(kind,a,b,doc='one'):return (doc,kind,a,b)
VERIFY='plan:verify';EXECUTE='reason:execute'
A=edge(VERIFY,'claim','intention');B=edge(EXECUTE,'intention','implementation')


def decision(key,choice='present',reference='present'):
    return dict(key=list(key),choice=choice,reference=reference,decision_id='decision-'+str(key))


def inspect(*edges):return {(e[0],e[1],e[3]) for e in edges}


class PathSelectionAuditTests(unittest.TestCase):
    def test_both_edges_are_needed_for_a_macro_path(self):
        self.assertEqual(compose([A,B]),[('one','claim','intention','implementation')])
        self.assertEqual(compose([A]),[])
        result=evaluate_paths([A,B],[decision(A),decision(B,'absent')],inspect(A,B))
        self.assertEqual(result['reference_paths'][0]['link_states'],['present','absent'])
        self.assertEqual(result['summary']['recovered_reference_paths'],0)
        self.assertEqual(result['summary']['predicted_paths'],0)

    def test_matching_text_or_node_ids_in_another_trace_do_not_join(self):
        other=edge(EXECUTE,'intention','implementation',doc='two')
        self.assertEqual(compose([A,other]),[])

    def test_parallel_implementations_count_as_separate_exact_paths(self):
        second=edge(EXECUTE,'intention','alternative')
        self.assertEqual(len(compose([A,B,second,A,B])),2)

    def test_no_cycles_promoted_to_three_stage_paths(self):
        self.assertEqual(compose([A,edge(EXECUTE,'intention','claim')]),[])

    def test_missing_job_candidate_and_unresolved_choice_are_distinct(self):
        not_inspected=evaluate_paths([A,B],[decision(A)],inspect(A))
        not_retrieved=evaluate_paths([A,B],[decision(A)],inspect(A,B))
        unresolved=evaluate_paths([A,B],[decision(A),decision(B,'unresolved')],inspect(A,B))
        self.assertEqual([r['reference_paths'][0]['link_states'][1] for r in [not_inspected,not_retrieved,unresolved]],
                         ['not_inspected','not_retrieved','unresolved'])
        self.assertEqual([r['summary']['fully_inspected_reference_paths'] for r in [not_inspected,not_retrieved,unresolved]],[0,1,1])
        self.assertEqual([r['summary']['reference_paths_with_both_candidates'] for r in [not_inspected,not_retrieved,unresolved]],[0,0,1])

    def test_native_reference_unknown_is_not_scored_as_negative(self):
        result=evaluate_paths([A],[decision(A),decision(B,reference=None)],inspect(A,B))
        self.assertEqual(result['summary']['predicted_reference_unresolved'],1)
        self.assertEqual(result['summary']['predicted_disagree'],0)
        self.assertEqual(result['summary']['native_reference_paths'],0)

    def test_one_reference_disagreement_is_enough_to_contradict_conjunction(self):
        result=evaluate_paths([],[decision(A,reference='absent'),decision(B,reference=None)],inspect(A,B))
        self.assertEqual(result['summary']['predicted_disagree'],1)
        self.assertEqual(result['summary']['predicted_reference_unresolved'],0)

    def test_exact_consensus_path_preserves_both_decision_identities(self):
        a,b=decision(A),decision(B)
        result=evaluate_paths([A,B],[a,b],inspect(A,B))
        self.assertEqual(result['summary']['predicted_agree'],1)
        self.assertEqual(result['summary']['recovered_reference_paths'],1)
        self.assertEqual(result['predicted_paths'][0]['decision_ids'],[a['decision_id'],b['decision_id']])

    def test_inconsistent_pair_reference_duplicate_and_undeclared_job_rejected(self):
        for refs,decisions,coverage in [([A],[decision(A,reference='absent')],inspect(A)),
                                       ([],[decision(A)],inspect(A)),
                                       ([A],[decision(A),decision(A)],inspect(A)),
                                       ([A],[decision(A)],set())]:
            with self.subTest(refs=refs,coverage=coverage),self.assertRaises(InputError):
                evaluate_paths(refs,decisions,coverage)

    def test_replays_frozen_choices_against_raw_paired_annotations(self):
        result=study(ROOT/'research/native-relations-probe-2026-10-06','hybrid')
        self.assertEqual(result['summary'],dict(native_reference_paths=1,fully_inspected_reference_paths=1,
            reference_paths_with_both_candidates=1,recovered_reference_paths=0,predicted_paths=2,
            predicted_agree=0,predicted_disagree=2,predicted_reference_unresolved=0))
        self.assertEqual(result['pair_counts'][VERIFY]['matching_choices'],168)
        self.assertEqual(result['pair_counts'][VERIFY]['scored_pairs'],183)
        self.assertEqual(result['pair_counts'][VERIFY]['true_positive'],1)
        self.assertEqual(result['pair_counts'][VERIFY]['reference_positive'],6)
        self.assertEqual(result['new_model_calls'],0)
        math=next(r for r in result['predicted_paths'] if r['path'][0].startswith('math'))
        self.assertIn("Let's simplify this equation",math['evidence'][1]['text'])
        self.assertEqual(math['reference_votes'],['absent','absent'])

    def test_smaller_binding_probe_does_not_report_a_missing_job_as_failure(self):
        result=study(ROOT/'research/native-relations-binding-2026-10-06','self_contained')
        self.assertEqual(result['summary']['fully_inspected_reference_paths'],0)
        self.assertIn('not_inspected',result['reference_paths'][0]['link_states'])
        self.assertEqual(result['summary']['predicted_disagree'],2)

    def test_report_escapes_source_text(self):
        result=study(ROOT/'research/native-relations-probe-2026-10-06','hybrid')
        result['predicted_paths'][0]['evidence'][0]['text']='<script>untrusted()</script>'
        document=render([result])
        self.assertNotIn('<script>untrusted()',document)
        self.assertIn('&lt;script&gt;untrusted()',document)


if __name__=='__main__':unittest.main()
