import random
import string
import unittest
from unittest.mock import patch

from tracker.activity import ActivityClient, SEGMENTATION_VERSION, analyze, packet, units
from tracker.text_units import segments
from test_activity import reasoning_run, response


def split_text(text):
    return [text[a:b] for a, b, _ in segments(text)]


class TextUnitTests(unittest.TestCase):
    def test_list_ordinals_stay_with_content_without_merging_separate_sentences(self):
        text = "1. Inspect the account. Then check the balance.\n  2. Report the result.\n"
        self.assertEqual(split_text(text), ["1. Inspect the account. ", "Then check the balance.\n", "  2. Report the result.\n"])
        self.assertEqual(split_text("3) Inspect the account. Next step."), ["3) Inspect the account. ", "Next step."])
        # A literal numeric answer remains a valid unit, never silently removed.
        self.assertEqual(split_text("1.\n"), ["1.\n"])

    def test_numbered_markdown_headings_keep_the_complete_title(self):
        text = "### **1. First traveler (using a certificate)**\n### **2. Second traveler**\n"
        self.assertEqual(split_text(text), text.splitlines(keepends=True))
        self.assertEqual(split_text("# Plan. Follow-up details.\n"), ["# Plan. Follow-up details.\n"])
        self.assertEqual(split_text("Issue #1. Next sentence."), ["Issue #1. ", "Next sentence."])

    def test_inline_code_and_fenced_payloads_do_not_create_internal_sentence_units(self):
        self.assertEqual(split_text("Use `A. B` as the label. Then verify."), ["Use `A. B` as the label. ", "Then verify."])
        self.assertEqual(split_text("Use ``A ` B. C`` as the label. Then verify."), ["Use ``A ` B. C`` as the label. ", "Then verify."])
        self.assertEqual(split_text("An unmatched `tick. Next sentence."), ["An unmatched `tick. ", "Next sentence."])
        text = "```python\nvalue = 1\n```javascript\nStill inside the payload. Not prose.\n```\nDone. Next."
        pieces = list(segments(text))
        self.assertEqual(pieces[0][2], "code_or_payload")
        self.assertIn("Not prose.", text[pieces[0][0]:pieces[0][1]])
        self.assertEqual([text[a:b] for a, b, _ in pieces[1:]], ["Done. ", "Next."])

    def test_wrong_or_short_fence_does_not_close_payload(self):
        text = "````py\n~~~\n```\nStill payload. More content.\n````` \t\nAfter."
        pieces = list(segments(text))
        self.assertEqual(len(pieces), 2)
        self.assertEqual(text[pieces[1][0]:pieces[1][1]], "After.")

    def test_format_candidates_and_quoted_text_remain_preserved_not_dropped(self):
        text = "> 1. Quoted plan. Another claim.\n---\n</think>\n"
        self.assertEqual(split_text(text), text.splitlines(keepends=True))
        self.assertEqual(list(segments(text))[0][2], "quoted")

    def test_arbitrary_unicode_and_line_endings_have_contiguous_lossless_offsets(self):
        rng = random.Random(476)
        fragments = ["### 2. Title\r\n", "1. Do it. Then retry.\n", "```py\n", "```\r", "> quote\n", "🧭界é", "  ", "\n", "\r\n", "A. B", "`x. Y`", "~~~suffix\n"]
        for _ in range(300):
            text = "".join(rng.choice(fragments + [rng.choice(string.ascii_letters)]) for _ in range(rng.randrange(0, 30)))
            spans = list(segments(text))
            self.assertEqual("".join(text[a:b] for a, b, _ in spans), text)
            self.assertEqual([b for _, b, _ in spans][:-1], [a for a, _, _ in spans][1:])
            if text:
                self.assertEqual(spans[0][0], 0); self.assertEqual(spans[-1][1], len(text))

    def test_unchanged_exact_requests_reuse_predictions_across_parser_revisions(self):
        run = reasoning_run(); subject = units(run)[0]; client = ActivityClient(transport=response)
        result = client.evaluate(run, subject["id"])
        result["_provenance"]["segmentation_version"] = "text-boundaries/1"
        self.assertTrue(client.cache_matches(result, run, subject["id"]))
        self.assertEqual(analyze(run, {subject["id"]: result})["segmentation_version"], SEGMENTATION_VERSION)

    def test_changed_boundaries_preserve_old_records_but_do_not_retarget_their_labels(self):
        run = reasoning_run(); run["events"][1]["text"] = "1. Inspect the account."
        def old_split(text):
            if text == "1. Inspect the account.":
                yield 0, 3, "text"; yield 3, len(text), "text"
            else: yield from segments(text)
        client = ActivityClient(transport=lambda r: response(r, {"plan": "present"}))
        with patch("tracker.activity.segments", old_split):
            old_unit = units(run)[0]; saved = client.evaluate(run, old_unit["id"])
        result = analyze(run, {old_unit["id"]: saved})
        self.assertNotEqual(units(run)[0]["id"], old_unit["id"])
        self.assertEqual(result["units"][0]["status"], "unobserved")
        self.assertEqual(result["historical_units"][0]["subject"]["text"], "1. ")
        self.assertEqual(result["historical_units"][0]["unit_id"], old_unit["id"])


if __name__ == "__main__": unittest.main()
