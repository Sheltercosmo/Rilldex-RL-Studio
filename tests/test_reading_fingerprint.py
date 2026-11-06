from pathlib import Path
import unittest
from unittest.mock import patch

from tracker import semantic_watch as watch
from tracker.readable_context import LINKED_VERSION,RETRIEVED_VERSION


class ReadingFingerprintTests(unittest.TestCase):
    def test_retrieval_change_requires_refresh_only_for_readers_using_it(self):
        options=[{'context_policy':{'schema':version}} for version in (LINKED_VERSION,RETRIEVED_VERSION)]
        before=[watch.fingerprint(value) for value in options]
        read=Path.read_text
        def changed(path,*args,**kwargs):
            return read(path,*args,**kwargs)+('\n# Changed source lookup' if path.name=='source_retrieval.py' else '')
        with patch.object(Path,'read_text',changed):after=[watch.fingerprint(value) for value in options]
        self.assertEqual(before[0],after[0]);self.assertNotEqual(before[1],after[1])

    def test_encoding_interpretation_change_requires_refresh(self):
        before=watch.fingerprint();read=Path.read_text
        def changed(path,*args,**kwargs):
            return read(path,*args,**kwargs)+('\n# Changed encoding reader' if path.name=='environment_contracts.py' else '')
        with patch.object(Path,'read_text',changed):self.assertNotEqual(before,watch.fingerprint())
