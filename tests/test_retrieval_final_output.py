from copy import deepcopy
import unittest
from research import retrieval_final_output as final
from tracker.schema import InputError
from tracker.semantic_extraction import read


class RetrievalFinalOutputTests(unittest.TestCase):
    def setUp(self):
        root=final.trial.DEST/'jobs'/final.KEY
        self.req=read(root/'packet.json')['request'];self.body=read(root/'output.json')
        _,self.run=final.trial.workspace.load(final.trial.OBSERVER)

    def test_finished_payload_passes_without_source_or_field_changes(self):
        before=deepcopy(self.body)
        result=final.validate(self.run,self.req,self.body)
        self.assertEqual(self.body,before)
        self.assertEqual(result['candidates'],before['candidates'])

    def test_invalid_evidence_is_still_rejected(self):
        self.body['candidates'][0]['fields']['target']['evidence'][0]['start']+=1
        with self.assertRaisesRegex(InputError,'Evidence mismatch'):
            final.validate(self.run,self.req,self.body)
