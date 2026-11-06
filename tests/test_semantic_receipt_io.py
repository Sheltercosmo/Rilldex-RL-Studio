"""Progress readers tolerate only bounded transient Windows sharing errors."""
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from tracker.semantic_extraction import read


def sharing_error():
    error=PermissionError('File sharing conflict')
    error.winerror=32
    return error


class ReceiptReadTests(TestCase):
    def test_reader_recovers_whole_atomic_receipt_without_provider_retry(self):
        with patch.object(Path,'read_text',side_effect=[sharing_error(),sharing_error(),'{"page":2}']) as opener, patch('tracker.semantic_extraction.time.sleep') as pause:
            self.assertEqual(read('progress.json'),{'page':2})
            self.assertEqual(opener.call_count,3)
            self.assertEqual([c.args[0] for c in pause.call_args_list],[.005,.01])

    def test_permanent_access_error_and_corrupt_json_are_not_hidden(self):
        for error in (PermissionError('Denied'),FileNotFoundError('Missing')):
            with patch.object(Path,'read_text',side_effect=error) as opener, patch('tracker.semantic_extraction.time.sleep') as pause:
                with self.assertRaises(type(error)):read('progress.json')
                opener.assert_called_once();pause.assert_not_called()
        with patch.object(Path,'read_text',return_value='{broken') as opener:
            with self.assertRaises(json.JSONDecodeError):read('progress.json')
            opener.assert_called_once()

    def test_sharing_retry_has_a_finite_limit(self):
        with patch.object(Path,'read_text',side_effect=sharing_error()) as opener, patch('tracker.semantic_extraction.time.sleep') as pause:
            with self.assertRaises(PermissionError):read('progress.json')
            self.assertEqual(opener.call_count,8)
            self.assertLess(sum(c.args[0] for c in pause.call_args_list),1)
