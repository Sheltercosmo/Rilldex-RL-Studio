import json
from pathlib import Path
import tempfile
import unittest

from research import scoped_reading_trial as trial
from tracker.schema import InputError


class ScopedTrialTests(unittest.TestCase):
    def prepared(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        path=Path(temporary.name)/'trial';trial.prepare(path)
        return path,json.loads((path/'manifest.json').read_text(encoding='utf-8'))

    def outputs(self,path,manifest):
        frozen=json.loads((path/'frozen-reference.json').read_text(encoding='utf-8'))['units']
        for packet in manifest['packets']:
            rows=[]
            for key in packet['request_hashes']:
                unit=frozen[key]
                rows.append(dict(request_hash=key,producer='authored-fixture',reading_protocol='contribution-readings/2',
                    readings=[dict(activity=unit['development_activity'],text='Authored test proposal.',
                        evidence=[dict(event_id='r',quote=unit['request']['source']['text'])])]))
            trial.save_new(path/packet['output'],dict(schema='scoped-reading-proposals/1',responses=rows))

    def test_exact_prefix_scopes_and_bound_contracts(self):
        path,manifest=self.prepared()
        self.assertEqual((len(manifest['packets']),manifest['max_subagent_turns']),(4,4))
        self.assertEqual(sum(len(p['request_hashes']) for p in manifest['packets']),6)
        for packet in manifest['packets']:
            self.assertTrue(all(e['excess_characters']==0 for e in packet['context_exposure']))
            text=(path/packet['file']).read_text(encoding='utf-8')
            self.assertNotIn('development_activity',text)
            for row in json.loads(text)['requests']:
                req=row['request'];self.assertEqual(req['reading_protocol'],'contribution-readings/2')
                self.assertEqual(req['source_form'],dict(kind='message',actor='agent',meaning='Recorded source form; it does not establish semantic purpose, effect or success.'))

    def test_replay_counts_candidates_not_selections(self):
        path,manifest=self.prepared();self.outputs(path,manifest);report=trial.audit(path)
        self.assertEqual(report['summary'],dict(subjects=6,expected_available=6,exclusive_expected=6))
        self.assertTrue(all(r['selected_activity'] is None for r in report['rows']))
        self.assertIsNone(report['usage']['billed_tokens'])

    def test_missing_response_and_changed_packet_are_rejected(self):
        path,manifest=self.prepared();self.outputs(path,manifest)
        output=path/manifest['packets'][0]['output'];data=json.loads(output.read_text(encoding='utf-8'))
        data['responses'].pop();output.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(InputError,'Missing'):trial.audit(path)
        packet=path/manifest['packets'][0]['file'];packet.write_bytes(packet.read_bytes()+b'\n')
        with self.assertRaisesRegex(InputError,'packet changed'):trial.audit(path)

    def test_fabricated_quote_is_rejected(self):
        path,manifest=self.prepared();self.outputs(path,manifest)
        output=path/manifest['packets'][0]['output'];data=json.loads(output.read_text(encoding='utf-8'))
        data['responses'][0]['readings'][0]['evidence'][0]['quote']='SOURCE DOES NOT CONTAIN THIS QUOTE'
        output.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(InputError):trial.audit(path)


if __name__=='__main__':unittest.main()
