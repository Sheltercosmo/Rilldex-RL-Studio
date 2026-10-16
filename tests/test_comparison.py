import copy
import unittest

from tracker.adapters import normalize
from tracker.compare import compare
from tracker.observe import MODES, analyze
from test_tracker import harbor


def row(task, checkpoint, explore, **metadata):
    return {"id": f"{task}-{checkpoint}", "metadata": {
        "task_id": task, "checkpoint": checkpoint, "training_step": int(checkpoint[1:]),
        "environment": "harbor", "environment_version": "fixture-v1", "split": "fixed-eval", "experiment": "fixture", **metadata},
        "harness_version": "fixture", "inspector_signature": "heuristic", "semantic_coverage": 0,
        "metrics": {"actions": 100, "mode_counts": {m: explore if m == "explore" else 100-explore if m == "apply" else 0 for m in MODES},
                    "exact_repeats": 0, "goal_scope_counts": {"unresolved": 100},
                    "feedback_opportunities": 0, "feedback_response_counts": {}}}


class ComparisonTests(unittest.TestCase):
    def test_paired_intervals_preserve_constant_within_task_change(self):
        rows = [row(f"t{i}", cp, i*10 + offset) for i in range(1,6) for cp,offset in [("c0",0),("c1",10)]]
        result = compare(rows)
        delta = result["paired_deltas"][0]["metrics"]["purpose.explore"]
        self.assertAlmostEqual(delta["delta"], .1)
        self.assertAlmostEqual(delta["interval_95"][0], .1)
        self.assertAlmostEqual(delta["interval_95"][1], .1)
        self.assertEqual(result, compare(list(reversed(rows))))

    def test_small_cohort_has_point_estimate_without_precise_interval(self):
        result = compare([row("t", "c0", 10), row("t", "c1", 30)])
        metric = result["paired_deltas"][0]["metrics"]["purpose.explore"]
        self.assertAlmostEqual(metric["delta"], .2)
        self.assertIsNone(metric["interval_95"])
        self.assertEqual(metric["task_count"], 1)

    def test_task_weight_is_independent_of_rollout_count(self):
        rows = [row("a", "c0", 0), row("b", "c0", 100), row("a", "c1", 0), row("b", "c1", 100)]
        for i in range(9):
            extra = copy.deepcopy(rows[0]); extra["id"] = f"extra-{i}"; rows.append(extra)
        result = compare(rows)
        self.assertEqual(result["checkpoints"][0]["modes"]["explore"], .5)
        self.assertEqual(result["checkpoints"][0]["rollout_count"], 11)

    def test_feedback_requires_opportunities_on_both_checkpoints(self):
        rows = [row(t, cp, 50) for t in ["a","b"] for cp in ["c0","c1"]]
        for r in rows:
            if r["metadata"]["task_id"] == "a" or r["metadata"]["checkpoint"] == "c1":
                r["metrics"].update(feedback_opportunities=10, feedback_response_counts={"unresolved":10})
        result = compare(rows)["paired_deltas"][0]
        self.assertEqual(result["feedback_matched_tasks"], ["a"])
        self.assertEqual(result["feedback_excluded_tasks"], ["b"])
        self.assertEqual(result["metrics"]["feedback.unresolved"]["task_count"], 1)

    def test_reviewed_and_mixed_inspection_are_not_automatic_trends(self):
        rows = [row("t", "c0", 10), row("t", "c1", 30)]
        rows[0]["reviewed_actions"] = 1
        self.assertEqual(compare(rows)["status"], "selective_reviews")
        rows[0]["reviewed_actions"] = 0
        rows[0]["inspector_profiles"] = [["model","old",.9],["model","new",.9]]
        self.assertEqual(compare(rows)["status"], "mixed_inspector_profiles")

    def test_partial_coverage_of_excluded_task_does_not_block_matched_comparison(self):
        rows = [row("t", "c0", 10), row("t", "c1", 30), row("other", "c1", 70)]
        rows[-1]["semantic_coverage"] = 1
        result = compare(rows)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["excluded"]), 1)

    def test_missing_steps_do_not_create_a_training_axis(self):
        result = compare([row("t", "c0", 10, training_step=None), row("t", "c1", 30, training_step=None)])
        self.assertFalse(result["ordered_by_training_step"])
        self.assertEqual(result["reference_checkpoint"], "c0")

    def test_parallel_tool_batch_does_not_invent_feedback_opportunities(self):
        analysis = analyze(normalize(harbor())[0])
        # A later action has both results, but the batch's last executed action
        # is unestablished. Do not pick the last enumerated call as its predecessor.
        self.assertEqual([a["feedback_opportunity"] for a in analysis["actions"]], [False, False, False])
        self.assertEqual(analysis["metrics"]["feedback_opportunities"], 0)
        self.assertEqual(analysis["metrics"]["feedback_response_counts"], {})


if __name__ == "__main__":
    unittest.main()
