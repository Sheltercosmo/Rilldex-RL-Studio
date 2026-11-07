import sqlite3
import unittest
from unittest.mock import patch

from receipt_replay import recorded_sqlite_metadata


class ReceiptReplayTests(unittest.TestCase):
    def test_only_metadata_is_frozen_and_restored(self):
        with sqlite3.connect(':memory:') as connection:
            actual = connection.execute('select sqlite_version()').fetchone()[0]
            with patch('sqlite3.sqlite_version', 'other-runtime'):
                with recorded_sqlite_metadata({'retrieval': {'sqlite_version': 'recorded-runtime'}}):
                    self.assertEqual(sqlite3.sqlite_version, 'recorded-runtime')
                    self.assertEqual(connection.execute('select sqlite_version()').fetchone()[0], actual)
                self.assertEqual(sqlite3.sqlite_version, 'other-runtime')

    def test_mixed_or_missing_versions_require_explicit_scope(self):
        for evidence in ({}, [{'sqlite_version': 'one'}, {'sqlite_version': 'two'}]):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                recorded_sqlite_metadata(evidence)
