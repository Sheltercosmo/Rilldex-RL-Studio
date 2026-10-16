"""Source-join safeguards; these fixtures provide no semantic reference labels."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from research.reconcile_dialogbank import checked_sources, read_pairs, span_key, table_rows
from tracker.schema import InputError


class ReconciliationTests(unittest.TestCase):
    def test_source_span_join_keeps_actor_and_every_token(self):
        self.assertEqual(span_key("p1", ["w3", "w1"]), span_key("p1", ["w1", "w3"]))
        self.assertNotEqual(span_key("p1", ["w1", "w3"]), span_key("p2", ["w1", "w3"]))
        self.assertNotEqual(span_key("p1", ["w1", "w3"]), span_key("p1", ["w1", "w2", "w3"]))
        for values in ([], ["w1", "w1"]):
            with self.assertRaises(InputError): span_key("p1", values)

    def test_blank_word_is_preserved_and_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"tokens.txt"
            path.write_text("w1: hello\nw2:\nw3: a: b\n",encoding="utf-8")
            self.assertEqual(read_pairs(path), {"w1":"hello","w2":"","w3":"a: b"})
            path.write_text("w1: one\nw1: two\n",encoding="utf-8")
            with self.assertRaises(InputError): read_pairs(path)

    def test_pinned_file_change_cannot_silently_enter_a_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root/"source.txt"; path.write_bytes(b"original")
            manifest = [{"url":"https://example.org/source.txt","sha256":hashlib.sha256(b"original").hexdigest()}]
            (root/"sources.json").write_text(json.dumps(manifest))
            self.assertEqual(checked_sources(root,["sources.json"]),manifest)
            path.write_bytes(b"changed")
            with self.assertRaises(InputError): checked_sources(root,["sources.json"])

    def test_blank_sender_is_not_filled_and_formulas_are_not_used_as_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"reference.xlsx"
            strings = ['Markables','Da-ID','Dialogue acts','Sender','Addressee','other Ps','FS text','fs1','da1','Ta:request','hello']
            shared = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+''.join('<si><t>'+s+'</t></si>' for s in strings)+'</sst>'
            header = '<row r="4">'+''.join(f'<c r="{c}4" t="s"><v>{i}</v></c>' for i,c in enumerate('ABCDEFG'))+'</row>'
            row = '<row r="5">'+''.join(f'<c r="{c}5" t="s"><v>{i}</v></c>' for c,i in [('A',7),('B',8),('C',9),('G',10)])+'</row>'
            def write(content):
                with ZipFile(path,'w') as z:
                    z.writestr('xl/sharedStrings.xml',shared)
                    z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+header+content+'</sheetData></worksheet>')
            write(row)
            result=table_rows(path)
            self.assertIsNone(result[0]['actor'])
            self.assertEqual(result[0]['functions'],['request'])
            write(row.replace('<v>9</v>','<f>1+1</f><v>9</v>'))
            with self.assertRaises(InputError): table_rows(path)


if __name__ == '__main__': unittest.main()
