import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tracker.connections import validate
from tracker.deployment_setup import plan
from tracker.portable import generation_document
from tracker.schema import InputError
from tracker.source_discovery import discover
from tracker.store import Store
from test_cloud_watch import ObjectStore
import test_export_watch
from test_tracker import harbor


class SourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name);self.root=self.base/'output';self.root.mkdir()

    def write(self,name,value):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value),encoding='utf-8');return p

    def config(self,route,**extra):
        return {'root':str(self.root),'producer':'control/w0','mode':route['mode'],
                'metadata':{'experiment':'control'}, **({'pattern':route['pattern']} if route['pattern'] else {}),**extra}

    def test_five_export_formats_discover_then_follow_append_and_restart(self):
        path=self.root/'worker.jsonl'
        rows=test_export_watch.ExportWatchTests.rows(self)
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        report=discover(str(self.root));self.assertEqual(report['recommended_route'],'exports')
        self.assertEqual(report['routes'][0]['records_decoded'],2)
        self.assertEqual(list(self.root.iterdir()),[path])
        store=Store(self.base/'review.sqlite');config=self.config(report['routes'][0])
        watcher=validate(store,config)[1];self.assertEqual(watcher.poll()['ingested'],5)
        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(rows[0])+'\n')
        self.assertEqual(validate(Store(store.path),config)[1].poll()['ingested'],1)
        self.assertEqual(validate(store,config)[1].poll()['ingested'],0)

    def test_snapshot_filter_excludes_observed_config_and_follows_new_filename(self):
        self.write('config.json',{'learning_rate':0.01})
        for i in (1,2):self.write(f'rollout-{i}.json',generation_document('Q','A'))
        r=discover(str(self.root));route=r['routes'][0]
        self.assertEqual((route['mode'],route['pattern']),('snapshots','rollout-*.json'))
        store=Store(self.base/'review.sqlite');config=self.config(route)
        self.assertEqual(validate(store,config)[1].poll()['ingested'],2)
        self.write('rollout-3.json',generation_document('Q','B'))
        result=validate(store,config)[1].poll()
        self.assertEqual((result['ingested'],result['deferred']),(1,0))
        setup=plan({'mode':route['mode'],'pattern':route['pattern']})
        self.assertIn('--pattern',setup['steps'][1]['code'])
        self.assertEqual(setup['connection']['pattern'],'rollout-*.json')

    def test_native_keeps_late_verifier_and_does_not_treat_sidecar_as_snapshot(self):
        self.write('trial/agent/trajectory.json',harbor())
        self.write('trial/config.json',{'task':{'path':'tasks/parser'}})
        r=discover(str(self.root));self.assertEqual(r['recommended_route'],'native')
        store=Store(self.base/'review.sqlite');config=self.config(r['routes'][0])
        self.assertEqual(validate(store,config)[1].poll()['ingested'],1)
        self.write('trial/result.json',{'finished_at':'2026-10-14T12:00:00Z','verifier_result':{'rewards':{'reward':1}}})
        self.assertEqual(validate(store,config)[1].poll()['ingested'],1)
        self.assertEqual(store.list()[0]['ingestion']['revision'],1)

    def test_empty_partial_unknown_and_malformed_later_row_are_not_declared_ready(self):
        self.assertEqual(discover(str(self.root))['status'],'empty')
        path=self.root/'rows.jsonl';path.write_text('{"input":',encoding='utf-8')
        self.assertIsNone(discover(str(self.root))['recommended_route'])
        row={'input':'Q','output':'A','step':2}
        path.write_text(json.dumps(row)+'\n{"metric":1}\n',encoding='utf-8')
        r=discover(str(self.root));self.assertEqual(r['routes'],[])
        self.assertTrue(any(s['status']=='unresolved' for s in r['samples']))

    def test_mixed_layout_does_not_automatically_combine_duplicate_sources(self):
        doc=generation_document('Q','A');self.write('rollout.json',doc)
        (self.root/'rows.jsonl').write_text(json.dumps(doc)+'\n')
        r=discover(str(self.root))
        self.assertEqual(r['status'],'mixed');self.assertIsNone(r['recommended_route'])
        self.assertEqual({r['mode'] for r in r['routes']},{'snapshots','exports'})

    def test_envelope_producer_preserved_and_shared_file_producers_need_review(self):
        def env(producer):return {'producer':producer,'rollout_id':'a','revision':0,'state':'complete',
                                 'document':generation_document('Q','A'),'metadata':{'experiment':'recorded'}}
        path=self.root/'worker.jsonl';path.write_text(json.dumps(env('original/w0'))+'\n')
        r=discover(str(self.root));route=r['routes'][0]
        self.assertEqual(route['producers'],['original/w0'])
        self.assertEqual(route['experiments'],['recorded'])
        with path.open('a') as f:f.write(json.dumps(env('original/w1'))+'\n')
        r=discover(str(self.root));self.assertFalse(r['routes'][0]['applicable'])
        self.assertIsNone(r['recommended_route'])

    def test_limits_remain_visible_and_discovery_does_not_create_database(self):
        for i in range(20):self.write(f'rollout-{i}.json',generation_document('Q','A'))
        r=discover(str(self.root))
        self.assertEqual(r['sampled_files'],6);self.assertTrue(r['incomplete'])
        self.assertEqual(r['routes'][0]['records_decoded'],6)
        target=self.base/'must-not-exist.sqlite'
        result=subprocess.run([sys.executable,'-m','rilldex','--db',str(target),'discover',str(self.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(target.exists())
        with patch('tracker.source_discovery.MAX_ENTRIES',2):
            r=discover(str(self.root));self.assertTrue(r['listing_limited']);self.assertIsNone(r['recommended_route'])

    def test_byte_limit_and_remote_failure_are_not_empty_ready_sources(self):
        self.write('a.json',generation_document('Q','A'))
        with patch('tracker.source_discovery.MAX_BYTES',10):
            r=discover(str(self.root));self.assertTrue(r['incomplete']);self.assertIsNone(r['recommended_route'])
        with self.assertRaises(InputError):discover(str(self.base/'missing'))
        fs=ObjectStore();fs.offline=True
        with patch('tracker.cloud_watch.filesystem',return_value=fs),self.assertRaises(InputError):discover('s3://bucket/job')

    def test_cloud_discovery_reads_jsonl_without_downloading_weights(self):
        fs=ObjectStore();fs.put('bucket/job/worker.jsonl',json.dumps({'input':'Q','output':'A','step':0}).encode()+b'\n')
        fs.put('bucket/job/model.bin',b'not a trace')
        with patch('tracker.cloud_watch.filesystem',return_value=fs):r=discover('s3://bucket/job')
        self.assertEqual(r['root'],'s3://bucket/job')
        self.assertEqual(r['cloud']['copied'],1);self.assertEqual(r['recommended_route'],'exports')

    def test_unseparated_json_filenames_require_a_filter(self):
        self.write('a/output.json',generation_document('Q','A'));self.write('b/output.json',{'batch':2})
        r=discover(str(self.root));self.assertTrue(r['routes'][0]['needs_filter'])
        self.assertFalse(r['routes'][0]['applicable'])

    def test_exact_filename_and_unsupported_extension_do_not_suggest_an_empty_reader(self):
        self.write('output.json',generation_document('Q','A'));self.write('settings.json',{'batch':2})
        r=discover(str(self.root));self.assertEqual(r['routes'][0]['pattern'],'output.json')
        store=Store(self.base/'review.sqlite')
        self.assertEqual(validate(store,self.config(r['routes'][0]))[1].poll()['ingested'],1)
        upper=self.base/'upper';upper.mkdir()
        (upper/'OUTPUT.JSON').write_text(json.dumps(generation_document('Q','A')))
        self.assertIsNone(discover(str(upper))['recommended_route'])

    def test_native_extension_does_not_accept_json_envelope_as_native_trace(self):
        self.write('sample.traj',{'producer':'w','rollout_id':'a','revision':0,'state':'complete','document':harbor()})
        self.assertEqual(discover(str(self.root))['routes'],[])


if __name__=='__main__':unittest.main()
