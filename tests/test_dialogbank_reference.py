"""Reference-reader integrity only; synthetic fixtures are not human labels."""
from copy import deepcopy
import unittest

from research.dialogbank_reference import parse, packet
from tracker.schema import InputError


DOCUMENT = b'''<TEI xmlns="http://www.tei-c.org/ns/1.0">
<profileDescr><particDescr xml:id="p1"/><particDescr xml:id="p2"/></profileDescr>
<text><div><timeline unit="s"><when xml:id="t0" absolute="00:00:00"/>
<when xml:id="t1" interval="1" since="#t0"/><when xml:id="t2" interval="2" since="#t0"/>
<when xml:id="t3" interval="3" since="#t0"/><when xml:id="t4" interval="4" since="#t0"/>
</timeline><u who="p1"><w xml:id="w1" start="#t0" end="#t1">Open</w>
<w xml:id="w2" start="#t1" end="#t2">uh</w><w xml:id="w3" start="#t2" end="#t3">folder</w>
<w xml:id="w4" start="#t3" end="#t4">FUTURE</w></u>
<u who="p2"><w xml:id="w5" start="#t1" end="#t2">okay</w></u></div>
<div><spanGrp xml:id="g1"><span xml:id="duplicate" from="#w1"/><span xml:id="s2" from="#w3"/></spanGrp>
<spanGrp xml:id="g2"><span xml:id="duplicate" from="#w5"/></spanGrp>
<fs xml:id="f1"><f name="verbalComponent" fVal="#g1"/></fs>
<fs xml:id="f2"><f name="verbalComponent" fVal="#g2"/></fs></div></text>
<diaml><dialogueAct xml:id="a1" target="#f1" sender="#p1" addresse="#p2" dimension="task" communicativeFunction="instruct"/></diaml>
</TEI>'''


class DialogBankReferenceTests(unittest.TestCase):
    def test_discontinuous_token_binding_is_preserved_without_flattening_gaps(self):
        corpus = parse(DOCUMENT); segment = corpus["segments"]["f1"]
        self.assertEqual(segment["text"], "Open folder")
        self.assertTrue(segment["discontiguous"])
        self.assertEqual(segment["token_ids"], ["w1", "w3"])
        self.assertEqual(segment["cutoff_seconds"], "3")
        self.assertIn("not verbatim",segment["rendering"])
        self.assertEqual(corpus["duplicate_leaf_ids"], ["duplicate"])
        self.assertNotEqual(segment["source_bindings"][0]["source_pointer"], corpus["segments"]["f2"]["source_bindings"][0]["source_pointer"])

    def test_packet_keeps_visible_other_speaker_context_and_excludes_future_words(self):
        corpus = parse(DOCUMENT); req = packet(corpus, corpus["segments"]["f1"])
        self.assertNotIn("FUTURE", str(req))
        self.assertEqual({t["id"] for t in req["state"]["context"]}, {"w2", "w5"})
        self.assertEqual({t["actor"] for t in req["state"]["context"]}, {"p1", "p2"})
        self.assertEqual(req["state"]["subject"]["actor"], "p1")
        bounded = packet(corpus, corpus["segments"]["f1"], context_tokens=1)
        self.assertEqual(bounded["state"]["missingness"]["earlier_context_tokens_omitted"],1)

    def test_external_labels_do_not_enter_or_influence_jev_inputs(self):
        corpus = parse(DOCUMENT); first = packet(corpus, corpus["segments"]["f1"])
        changed = deepcopy(corpus)
        changed["annotations"][0]["source_attributes"].update(communicativeFunction="SECRET_LABEL",dimension="SECRET_DIMENSION")
        second = packet(changed, changed["segments"]["f1"])
        self.assertEqual(first,second)
        self.assertNotIn("communicativeFunction",str(first))
        self.assertNotIn("source_attributes",str(first))
        self.assertNotIn("proposed_mapping",str(first))

    def test_unknown_and_ambiguous_bindings_fail_without_silent_join(self):
        for data in [DOCUMENT.replace(b'from="#w1"',b'from="#missing"'),
                     DOCUMENT.replace(b'xml:id="w4"',b'xml:id="w1"'),
                     DOCUMENT.replace(b'fVal="#g1"',b'fVal="#duplicate"')]:
            with self.subTest(data=data[:40]), self.assertRaises(InputError): parse(data)

    def test_speaker_and_time_conflicts_are_rejected(self):
        for data in [DOCUMENT.replace(b'sender="#p1"',b'sender="#p2"'),
                     DOCUMENT.replace(b'interval="1" since="#t0"',b'interval="1" since="#t1"'),
                     DOCUMENT.replace(b'start="#t3" end="#t4"',b'start="#t4" end="#t3"'),
                     DOCUMENT.replace(b'unit="s"',b'unit="ms"')]:
            with self.subTest(data=data[:40]), self.assertRaises(InputError): parse(data)

    def test_mixed_speakers_and_repeated_tokens_cannot_define_a_false_unit(self):
        for data in [DOCUMENT.replace(b'from="#w3"',b'from="#w5"'),
                     DOCUMENT.replace(b'from="#w3"',b'from="#w1"')]:
            with self.subTest(data=data[:40]), self.assertRaises(InputError): parse(data)


if __name__ == "__main__": unittest.main()
