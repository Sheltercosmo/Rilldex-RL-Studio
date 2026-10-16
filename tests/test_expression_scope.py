from copy import deepcopy
import random
import unittest

from tracker.expression_scope import request, scopes, interpret, MAX_SCOPES
from tracker.activity import packet, units
from tracker.adapters import normalize
from tracker.schema import InputError


def source(text, syntax="text", start=0):
    return {"id": "u-test", "kind": "model_span", "syntax": syntax, "start": start,
            "end": start+len(text), "text": text, "source_pointer": "/steps/2/message"}


class ExpressionScopeTests(unittest.TestCase):
    def test_mixed_requests_and_claims_keep_exact_separate_content(self):
        text = "I checked the ledger; please confirm the balance."
        result = scopes(source(text, start=40))
        a, b = result["scopes"]
        self.assertEqual(a["text"], "I checked the ledger; ")
        self.assertEqual(b["text"], "please confirm the balance.")
        self.assertEqual(a["start"], 40)
        self.assertEqual(a["end"], b["start"])
        self.assertEqual(b["end"], 40+len(text))
        self.assertEqual(len(scopes(source("The balance may be wrong, so I will check it."))["scopes"]), 2)

    def test_code_quotes_and_parentheses_are_not_cut_into_false_claims(self):
        for text, syntax in [
            ('```python\nprint("done"); send()\n```', "code_or_payload"),
            ("> I checked; please confirm.", "quoted"),
            ('The example is "done; send".', "text"),
            ("The example is 'done; send'.", "text"),
            ("The example is ‘done; send’.", "text"),
            ("Use `read(); write()` as an example.", "text"),
            ("## Status (ready; queued)", "text"),
            ("A nested list [one (x; y); two] follows.", "text")]:
            with self.subTest(text=text):
                self.assertEqual([s["text"] for s in scopes(source(text, syntax))["scopes"]], [text])
        self.assertEqual(len(scopes(source("We'll check it; please wait."))["scopes"]), 2)
        self.assertEqual(len(scopes(source('He said "I checked; done"; please confirm.'))["scopes"]), 2)

    def test_limit_retains_complete_parent_and_discloses_candidate_shortfall(self):
        text = "; ".join(f"item {i}" for i in range(MAX_SCOPES+2))
        result = scopes(source(text))
        self.assertTrue(result["candidate_limit_exceeded"])
        self.assertEqual(result["proposed_scope_count"], MAX_SCOPES+2)
        self.assertEqual([s["text"] for s in result["scopes"]], [text])

    def test_ordinary_coordinated_lists_are_not_split_into_assertions(self):
        text = "I can help you verify your identity using your first name, last name, and zip code."
        self.assertEqual([s["text"] for s in scopes(source(text))["scopes"]], [text])
        self.assertEqual(len(scopes(source("Bring the card, certificate, and passport."))["scopes"]), 1)

    def test_unicode_sources_have_lossless_contiguous_nonduplicated_coverage(self):
        randomizer = random.Random(815)
        for _ in range(200):
            text = "😀前 " + "".join(randomizer.choice([' x', '; ', '；', '界', '"', "'", '`', '(', ')', '\n']) for _ in range(40))
            parts = scopes(source(text, start=100))["scopes"]
            self.assertEqual("".join(p["text"] for p in parts), text)
            self.assertEqual(parts[0]["start"], 100)
            self.assertEqual(parts[-1]["end"], 100+len(text))
            self.assertTrue(all(a["end"] == b["start"] for a, b in zip(parts, parts[1:])))
            self.assertEqual(len({p["id"] for p in parts}), len(parts))

    def test_module_preserves_parent_cutoff_and_does_not_mutate_activity_request(self):
        run = normalize({"schema_version": "ATIF-v1.7", "agent": {"name": "test"}, "steps": [
            {"step_id": 1, "source": "user", "message": "Check the balance."},
            {"step_id": 2, "source": "agent", "message": "I checked the ledger; please confirm the balance."},
            {"step_id": 3, "source": "agent", "message": "FUTURE DO NOT INCLUDE"}]})[0]
        unit = next(u for u in units(run) if u["event_index"] == 1)
        base = packet(run, unit["id"]); saved = deepcopy(base)
        scoped = request(base)
        self.assertEqual(base, saved)
        self.assertNotIn("activity_definitions", scoped["state"])
        self.assertEqual(scoped["state"]["cutoff_codepoint"], unit["end"])
        self.assertNotIn("FUTURE DO NOT INCLUDE", str(scoped))
        self.assertEqual(len(scoped["questions"]), 2)
        self.assertTrue(all(k.startswith("form_s") for k in scoped["questions"]))
        base["state"]["subject"]["text"] = "clipped"
        with self.assertRaisesRegex(InputError, "complete subject"):
            request(base)

    def test_argmax_is_preserved_for_each_scope_and_missing_evidence_is_separate(self):
        base = {"state": {"harness": "activity-test", "subject": source("I checked; please confirm."),
                           "cutoff_event_id": "e2", "cutoff_codepoint": 26, "missingness": {}}}
        req = request(base)
        answers = {}
        for i, (key, q) in enumerate(req["questions"].items()):
            winner = ("retrospective_claim", "requested")[i]
            answers[key] = {"type": "choice", "choice": "unresolved", "confidence": 0.999,
                            "probabilities": {k: 0.28 if k == winner else 0.08 for k in q["criteria"]}}
        response = {"answers": answers, "model": req["model"]}
        result = interpret(response, req)
        self.assertEqual([a["value"] for a in result["answers"].values()], ["retrospective_claim", "requested"])
        self.assertTrue(all(a["status"] == "decided" for a in result["answers"].values()))
        req["state"]["missingness"]["required_truncated_event_ids"] = ["tool_contract"]
        gated = interpret(response, req)
        self.assertTrue(all(a["status"] == "unresolved" and a["selection_status"] == "decided" for a in gated["answers"].values()))
        self.assertEqual([a["value"] for a in gated["answers"].values()], ["retrospective_claim", "requested"])
        with self.assertRaisesRegex(InputError, "model version"):
            interpret({**response, "model": "unknown"}, req)


if __name__ == "__main__": unittest.main()
