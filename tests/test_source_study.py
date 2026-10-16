import copy
from pathlib import Path
import tempfile
import unittest

from tracker.schema import InputError, digest
from tracker.source_study import build, compare, score
from tracker.store import Store


def episode(cp, slot, task, numerator, denominator=1, unknown=0):
    raw = {"checkpoint": cp, "slot": slot, "task": task, "evidence": numerator}
    return {"id": digest(raw)[:24], "checkpoint": cp, "slot": slot, "task_id": task, "task": task,
            "raw": raw, "source_hash": digest(raw), "source": {"line": slot + 1},
            "metrics": {"rate": {"numerator": numerator, "denominator": denominator, "unknown": unknown}}}


def study(rows, **kwargs):
    return build(title="test", pack="test/1", checkpoints=[{"id": c, "recorded_context": {"seed": 0}} for c in ("a", "b")],
                 episodes=rows, metrics={"rate": {"label": "Source rate", "unit": "fraction"}}, provenance={}, limitations=[], **kwargs)


class SourceStudyTests(unittest.TestCase):
    def test_game_weighting_differs_from_episode_and_action_weighting(self):
        rows = [episode("a", 0, "g", 0), episode("a", 1, "g", 0), episode("a", 2, "h", 1),
                episode("b", 0, "g", 1), episode("b", 1, "g", 1), episode("b", 2, "h", 1)]
        s = study(rows); c = compare(s, "a", "b")["metrics"]["rate"]
        self.assertEqual(c["before"]["value"], .5)
        self.assertEqual(s["cohorts"]["a"]["episode_weighted"]["rate"]["value"], 1/3)
        self.assertEqual(c["delta"], .5)
        self.assertIsNone(c["interval_95"])
        self.assertEqual(score([{"numerator":1,"denominator":2,"unknown":0}, {"numerator":0,"denominator":100,"unknown":0}])["value"], .25)

    def test_unknown_retains_bounds_and_prevents_false_point_change(self):
        rows = [episode("a", 0, "g", 1, 10, 8), episode("b", 0, "g", 2, 10)]
        s = study(rows); m = compare(s, "a", "b")["metrics"]["rate"]
        self.assertIsNone(m["delta"]); self.assertIsNone(m["interval_95"])
        self.assertAlmostEqual(m["missingness_delta_bounds"][0], -.7)
        self.assertAlmostEqual(m["missingness_delta_bounds"][1], .1)
        self.assertEqual(m["before"]["unknown"], 8)

    def test_no_opportunity_and_unmatched_games_are_excluded_not_zero(self):
        rows = [episode("a", 0, "g", 0, 0), episode("b", 0, "g", 1),
                episode("a", 1, "h", 0), episode("b", 1, "h", 1), episode("a", 2, "onlya", 1)]
        c = compare(study(rows), "a", "b")
        self.assertEqual(c["excluded_before"], ["onlya"])
        self.assertEqual(c["matched_tasks"], 2)
        self.assertEqual(c["metrics"]["rate"]["excluded_tasks"], 1)
        self.assertEqual(c["metrics"]["rate"]["delta"], 1)

    def test_cluster_interval_is_deterministic_and_all_games_retained(self):
        rows = [episode(cp, i, f"g{i}", int(cp == "b" and i < 5)) for cp in ("a", "b") for i in range(10)]
        s = study(rows); first = compare(s, "a", "b"); second = compare(s, "a", "b")
        self.assertEqual(first, second)
        m = first["metrics"]["rate"]
        self.assertEqual(m["delta"], .5)
        self.assertLessEqual(m["interval_95"][0], .5)
        self.assertGreaterEqual(m["interval_95"][1], .5)
        self.assertEqual(len(first["tasks"]), 10)

    def test_duplicate_slots_raw_tampering_invalid_counts_and_task_swap_rejected(self):
        rows = [episode("a", 0, "g", 0), episode("b", 0, "g", 1)]
        for mutation in (lambda r: r.append(copy.deepcopy(r[0])),
                         lambda r: r[0]["raw"].update(evidence=9),
                         lambda r: r[0]["metrics"]["rate"].update(unknown=2),
                         lambda r: r[0]["metrics"]["rate"].update(numerator=True),
                         lambda r: r[1].update(task_id="other")):
            changed = copy.deepcopy(rows); mutation(changed)
            with self.assertRaises(InputError): study(changed)
        with self.assertRaises(InputError): compare(study(rows), "a", "a")
        with self.assertRaises(InputError): compare(study(rows), "a", "missing")

    def test_immutable_store_idempotence_and_summary_reconciliation(self):
        rows = [episode("a", 0, "g", 0), episode("b", 0, "g", 1)]
        s = study(rows)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/"test.sqlite")
            self.assertTrue(store.add_study(s, rows)["imported"])
            self.assertFalse(store.add_study(s, rows)["imported"])
            self.assertEqual(store.study_episode(s["id"], rows[0]["id"]), rows[0])
            self.assertEqual(store.study(s["id"]), s)
            self.assertEqual(len(store.studies()), 1)
            changed = copy.deepcopy(s); changed["cohorts"]["a"]["metrics"]["rate"]["value"] = 1
            with self.assertRaises(InputError): store.add_study(changed, rows)
            with self.assertRaises(KeyError): store.study_episode("wrongstudy", rows[0]["id"])

    def test_context_change_blocks_comparison(self):
        rows = [episode("a", 0, "g", 0), episode("b", 0, "g", 1)]
        s = study(rows); cps = copy.deepcopy(s["checkpoints"]); cps[1]["recorded_context"]["seed"] = 7
        with self.assertRaises(InputError):
            build(title="test", pack="test/1", checkpoints=cps, episodes=rows, metrics=s["metrics"], provenance={}, limitations=[])


if __name__ == "__main__":
    unittest.main()
