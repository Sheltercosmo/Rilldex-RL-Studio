"""Atomic progress replacement while Windows status readers hold a file."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tracker.semantic_extraction import read,write


class ReceiptTests(unittest.TestCase):
    def test_transient_windows_reader_lock_retains_then_replaces_whole_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'progress.json';write(path,{'inspected':1})
            original=Path.replace;attempts=[]
            def replace(source,target):
                attempts.append(1)
                if len(attempts)<3:
                    self.assertEqual(read(target),{'inspected':1})
                    error=PermissionError('reader lock');error.winerror=32;raise error
                return original(source,target)
            with patch.object(Path,'replace',replace),patch('time.sleep') as pause:
                write(path,{'inspected':2})
            self.assertEqual(read(path),{'inspected':2});self.assertEqual(len(attempts),3)
            self.assertEqual(pause.call_count,2)

    def test_persistent_or_unrelated_permission_error_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'progress.json';write(path,{'inspected':1})
            error=PermissionError('persistent');error.winerror=5
            with patch.object(Path,'replace',side_effect=error) as replace,patch('time.sleep'):
                with self.assertRaises(PermissionError):write(path,{'inspected':2})
                self.assertEqual(replace.call_count,8)
            self.assertEqual(read(path),{'inspected':1})
            with patch.object(Path,'replace',side_effect=PermissionError('access denied')) as replace:
                with self.assertRaises(PermissionError):write(path,{'inspected':2})
                self.assertEqual(replace.call_count,1)


if __name__=='__main__':unittest.main()
