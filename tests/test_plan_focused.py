"""Focused plan packets, coverage and replay; authored choices test plumbing only."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import plan_relations as plans, plan_scope_pages as pages, plan_scope_roles as direct
from tracker import semantic_watch as watch
from tracker.adapters import normalize
from tracker.schema import digest, dumps
from tracker.semantic_budget import BudgetReached, ExecutionBudget
from tracker.semantic_extraction import Pipeline, checked_span, read, write
from tests.test_plan_relations import fixture, Provider
from tests.test_plan_scope_pages import transport as extraction_transport


FIXTURES = Path(__file__).parent / "fixtures"


def retained_cases():
    saved = read(FIXTURES / "plan_direct_roles.json")
    public = read(FIXTURES / saved["public_fixture"])
    for case in saved["cases"]:
        run, extraction = ((public["run"], public["extraction"]) if case["kind"] == "public_development"
                           else (case["run"], case["extraction"]))
        action = next(unit for unit in extraction["units"] if unit["kind"] == "action" and
                      (unit["source"]["event_id"] == case["event"] if "event" in case else unit["id"] == case["action_id"]))
        pool, _ = pages.candidates(run, extraction, action)
        yield saved, case, run, extraction, action, pool


def structural_response(request):
    """Deliberately synthetic argmax patterns, not source-semantic expectations."""
    labels = {"s0": "performs_or_updates_step+inspects_step_result", "s1": "sets_up_execution",
              "s2": "upstream_work_only"}
    answers = {}
    for key, question in request["questions"].items():
        selected = labels.get(key, direct.UNRESOLVED)
        answers[key] = {"type": "choice", "choice": "another_step_or_unrelated", "confidence": 0,
                        "probabilities": {label: 0.3 if label == selected else 0.7 / (len(question["criteria"]) - 1)
                                          for label in question["criteria"]}}
    return {"model": request["model"], "answers": answers}


class FocusedPlanTests(unittest.TestCase):
    def extracted(self, directory):
        run = fixture()
        engine = Pipeline(directory, Provider(Path(directory) / "candidates"), extraction_transport)
        return run, engine, engine.run(run)

    def test_version_four_packets_keep_frozen_live_request_hashes(self):
        observed = 0
        for saved, case, run, extraction, action, pool in retained_cases():
            with self.subTest(case=case["name"]):
                baseline = direct.request(run, extraction, action, pool)
                key = digest(baseline)
                self.assertIn(key, saved["decisions"])
                self.assertEqual(baseline, saved["decisions"][key]["request"])
                v4_pages = list(pages.request_pages(run, extraction, action, pool, direct.request, plans.DIRECT_VERSION))
                self.assertEqual(v4_pages, [(pool, baseline)])
                # Producing /5 packets must not mutate the old packet or candidate pool.
                before = deepcopy((baseline, pool))
                list(pages.request_pages(run, extraction, action, pool, direct.request, plans.FOCUSED_VERSION))
                self.assertEqual((baseline, pool), before)
                self.assertEqual(digest(direct.request(run, extraction, action, pool)), key)
                observed += len(pool)
        self.assertEqual(observed, 30)

    def test_focused_packets_only_select_one_candidate_and_keep_source_contracts(self):
        contract_count = 0
        cases = list(retained_cases())
        # The historical /4 fixtures predate native contract capture. Add a
        # structured call solely to exercise lossless contract projection.
        with tempfile.TemporaryDirectory() as directory:
            run = normalize({"messages": [
                {"role": "user", "content": "Prepare a report."},
                {"role": "assistant", "content": "First write a report in Markdown, then convert it to PDF."},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "edit-1", "type": "function",
                    "function": {"name": "write_report", "arguments": '{"file":"report.md"}'}}]},
                {"role": "tool", "tool_call_id": "edit-1", "content": "FUTURE RESULT: saved report."}],
                "tools": [{"type": "function", "function": {"name": "write_report",
                    "description": "Write Markdown report content to the named file.", "parameters": {"type": "object"}}}]})[0]
            engine = Pipeline(directory, Provider(Path(directory) / "candidates"), extraction_transport)
            extraction = engine.run(run)
            action = next(unit for unit in extraction["units"] if unit["kind"] == "action")
            pool, _ = pages.candidates(run, extraction, action)
            cases.append((None, {"name": "native-contract-projection"}, run, extraction, action, pool))
        for _, case, run, extraction, action, pool in cases:
            baseline = direct.request(run, extraction, action, pool)
            focused = list(pages.request_pages(run, extraction, action, pool, direct.request, plans.FOCUSED_VERSION))
            self.assertEqual([chunk[0]["id"] for chunk, _ in focused], [candidate["id"] for candidate in pool])
            events = {event["id"]: event for event in run["events"]}
            cutoff = events[action["source"]["event_id"]]
            for chunk, request in focused:
                with self.subTest(case=case["name"], candidate=chunk[0]["id"]):
                    key = chunk[0]["id"]
                    expected = deepcopy(baseline)
                    expected["state"]["relation_harness"] = plans.FOCUSED_VERSION
                    expected["state"]["plan_stage_candidates"] = deepcopy(chunk)
                    expected["questions"] = {key: expected["questions"][key]}
                    self.assertEqual(request, expected)
                    self.assertEqual(len(request["questions"]), 1)
                    self.assertEqual(len(request["state"]["plan_stage_candidates"]), 1)
                    self.assertEqual(request["state"]["subject"], action["source"])
                    self.assertEqual(request["state"]["cutoff_event_id"], cutoff["id"])
                    self.assertEqual(request["state"]["cutoff_codepoint"], action["source"]["end"])
                    checked_span(run, chunk[0]["plan_source"], action["source"])
                    for event in request["state"]["prefix"]:
                        self.assertLessEqual(events[event["id"]]["index"], cutoff["index"])
                        if "tool_contract_ref" in event:
                            self.assertEqual(request["state"]["tool_contracts"][event["tool_contract_ref"]],
                                             events[event["id"]]["tool_contract"])
                            contract_count += 1
                    self.assertLessEqual(len(dumps(request).encode("utf-8")), pages.MAX_BYTES)
        self.assertGreater(contract_count, 0)

    def test_budget_resume_considers_all_steps_without_repaying_completed_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            run, engine, extraction = self.extracted(directory)
            plan = next(unit for unit in extraction["units"] if unit["activity"] == "plan")
            step = plan["plan_structure"]["steps"][0]
            plan["plan_structure"]["steps"] = [{**deepcopy(step), "id": f"step-{index}"} for index in range(17)]
            progress_path = Path(directory) / "focused-progress.json"
            first_budget = ExecutionBudget(directory, "first-focused", {"jev_requests": 3, "input_bytes": 100_000_000})
            seen = []

            def send(request):
                self.assertEqual(len(request["questions"]), 1)
                seen.append(digest(request))
                return structural_response(request)

            engine.transport = lambda request: first_budget.invoke("jev", request, lambda: send(request))
            with self.assertRaises(BudgetReached):
                pages.build(run, extraction, engine.decide, version=plans.FOCUSED_VERSION,
                            progress=lambda result: write(progress_path, result))
            partial = read(progress_path)
            self.assertEqual((partial["coverage"]["candidate_pairs"], partial["coverage"]["compared_pairs"],
                              partial["coverage"]["pending_pairs"]), (68, 3, 65))
            self.assertEqual(partial["status"], "running")
            inspecting = next(row for row in partial["actions"] if row["status"] == "inspecting")
            self.assertEqual(len(inspecting["pages"]), 3)
            self.assertIn("next_request", inspecting)
            self.assertEqual(first_budget.used["jev_requests"], 3)
            second_budget = ExecutionBudget(directory, "resume-focused", {"jev_requests": 65, "input_bytes": 100_000_000})
            engine.transport = lambda request: second_budget.invoke("jev", request, lambda: send(request))
            complete = pages.build(run, extraction, engine.decide, version=plans.FOCUSED_VERSION)
            self.assertEqual(second_budget.used["jev_requests"], 65)
            self.assertEqual((len(seen), len(set(seen))), (68, 68))
            self.assertEqual(complete["coverage"]["pending_pairs"], 0)
            self.assertEqual(complete["coverage"]["compared_pairs"], 68)
            self.assertEqual(complete["coverage"]["indirect_pairs"], 4)
            self.assertEqual(complete["coverage"]["unresolved_pairs"], 56)
            for row in complete["actions"]:
                if not row["candidate_count"]:
                    continue
                self.assertEqual([pair["step_id"] for pair in row["pairs"]], [f"step-{i}" for i in range(17)])
                self.assertEqual([page["compared_pairs"] for page in row["pages"]], [1] * 17)
                self.assertEqual(row["status"], "unresolved")
            engine.transport = lambda _: self.fail("All focused decisions should replay from cache")
            self.assertEqual(pages.build(run, extraction, engine.decide, version=plans.FOCUSED_VERSION), complete)

    def test_independent_steps_and_compound_roles_preserve_all_graph_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            run, engine, extraction = self.extracted(directory)
            engine.transport = structural_response
            result, audit = plans.execute(run, extraction, engine, version=plans.FOCUSED_VERSION)
            self.assertTrue(audit["argmax_replayed"])
            self.assertEqual(audit["semantic_accuracy"], "not independently measured")
            self.assertFalse(audit["completion_inferred"])
            self.assertEqual(len(result["relations"]), 12)
            for row in result["actions"]:
                if not row["candidate_count"]:
                    continue
                self.assertEqual([pair["roles"] for pair in row["pairs"]], [["attempts", "checks"], ["prepares"]])
                edges = [edge for edge in result["relations"] if edge["from"] == row["action_unit_id"]]
                self.assertEqual({(edge["plan_step_id"], edge["type"]) for edge in edges},
                                 {("draft", "attempts_plan_step"), ("draft", "checks_plan_step"),
                                  ("convert", "prepares_plan_step")})
                self.assertEqual(len({edge["request"] for edge in edges}), 2)
            self.assertNotEqual(plans.path_for(directory, extraction, plans.DIRECT_VERSION),
                                plans.path_for(directory, extraction, plans.FOCUSED_VERSION))

    def test_oversized_steps_remain_pending_while_other_steps_are_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            run, engine, extraction = self.extracted(directory)
            plan = next(unit for unit in extraction["units"] if unit["activity"] == "plan")
            plan["plan_structure"]["steps"][0]["target"] = "x" * pages.MAX_BYTES
            engine.transport = structural_response
            result = pages.build(run, extraction, engine.decide, version=plans.FOCUSED_VERSION)
            self.assertEqual(result["status"], "needs_evidence")
            self.assertEqual((result["coverage"]["candidate_pairs"], result["coverage"]["compared_pairs"],
                              result["coverage"]["pending_pairs"], result["coverage"]["oversized_pairs"]), (8, 4, 4, 4))
            for row in result["actions"]:
                if row["candidate_count"]:
                    self.assertEqual(row["status"], "evidence_too_large")
                    self.assertEqual([item["step_id"] for item in row["oversized_pairs"]], ["draft"])
                    self.assertEqual([item["step_id"] for item in row["pairs"]], ["convert"])
            with patch.object(pages, "MAX_BYTES", 1):
                blocked = pages.build(run, extraction, lambda _: self.fail("Oversized evidence cannot be trimmed"),
                                      version=plans.FOCUSED_VERSION)
            self.assertEqual(blocked["coverage"]["compared_pairs"], 0)
            self.assertEqual(blocked["coverage"]["pending_pairs"], 8)
            self.assertEqual(blocked["coverage"]["oversized_pairs"], 8)
            self.assertEqual(blocked["relations"], [])

    def test_focused_watch_fingerprint_tracks_the_direct_role_implementation(self):
        self.assertEqual(watch.behavior_options()["plan_relation_version"], plans.FOCUSED_VERSION)
        read_text = Path.read_text
        versions = (plans.PAGED_VERSION, plans.DIRECT_VERSION, plans.FOCUSED_VERSION)
        original = {version: watch.fingerprint({"plan_relation_version": version}) for version in versions}

        def changed(path, *args, **kwargs):
            result = read_text(path, *args, **kwargs)
            return result + "\n# Test-only direct-role implementation change" if path.name == "plan_scope_roles.py" else result

        with patch.object(Path, "read_text", changed):
            updated = {version: watch.fingerprint({"plan_relation_version": version}) for version in versions}
        self.assertEqual(original[plans.PAGED_VERSION], updated[plans.PAGED_VERSION])
        self.assertNotEqual(original[plans.DIRECT_VERSION], updated[plans.DIRECT_VERSION])
        self.assertNotEqual(original[plans.FOCUSED_VERSION], updated[plans.FOCUSED_VERSION])

    def test_new_pilot_uses_focused_version_and_existing_pin_keeps_version_four(self):
        from rilldex import models
        from tracker.store import Store
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "study.sqlite")
            run = fixture()
            store.add([run])
            env = {"RILLDEX_LLM_PRESET": "custom", "RILLDEX_LLM_MODEL": "focused-contract-test",
                   "RILLDEX_LLM_URL": "http://127.0.0.1:1/v1/chat/completions"}
            with patch.dict(os.environ, env), patch("urllib.request.urlopen", side_effect=AssertionError("Offline zero-budget test")):
                fresh = models.pilot(store, root / "fresh", run["id"], transport=lambda _: self.fail("Zero budget"))
                self.assertEqual(fresh["model"]["plan_relation_version"], plans.FOCUSED_VERSION)
                old_pin = deepcopy(fresh["model"])
                old_pin["plan_relation_version"] = plans.DIRECT_VERSION
                write(root / "existing" / "model.json", old_pin)
                existing = models.pilot(store, root / "existing", run["id"], transport=lambda _: self.fail("Zero budget"))
                self.assertEqual(existing["model"], old_pin)
                self.assertEqual(read(root / "existing" / "extraction" / "workspace.json")["plan_relation_version"],
                                 plans.DIRECT_VERSION)


if __name__ == "__main__":
    unittest.main()
