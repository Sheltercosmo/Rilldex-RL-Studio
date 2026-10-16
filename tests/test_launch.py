import io
import json
import os
import socket
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker.cli import main
from tracker.launch import read
from tracker.store import Store
from tracker.connections import definitions
from tracker.schema import InputError


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.profile=self.root/'job.rilldex.json'
        self.value={'schema':'rilldex-launch/1','database':'state/workspace.sqlite','port':0,
            'source':{'root':'outputs','producer':'job/worker','mode':'exports','metadata':{'experiment':'job'}}}
        self.save();self.db=self.root/'state/workspace.sqlite'

    def save(self):self.profile.write_text(json.dumps(self.value),encoding='utf-8-sig')

    def test_previous_brand_launch_files_keep_the_same_paths_and_identity(self):
        current = read(self.profile)
        self.value['schema'] = 'jev-launch/1'
        self.save()
        legacy = read(self.profile)
        self.assertEqual(current.pop('schema'), 'rilldex-launch/1')
        self.assertEqual(legacy.pop('schema'), 'jev-launch/1')
        self.assertEqual(current, legacy)

    def run_cli(self,*args):
        output=io.StringIO()
        with redirect_stdout(output):main(['launch',str(self.profile),*args])
        return output.getvalue()

    def output(self,partial=False):
        root=self.root/'outputs';root.mkdir(exist_ok=True)
        row=json.dumps({'input':'Question','output':'Answer','step':0,'score':1})
        (root/'records.jsonl').write_text(row+('' if partial else '\n'),encoding='utf-8')

    def test_paths_remain_file_relative_in_another_working_directory(self):
        self.output();elsewhere=self.root/'other';elsewhere.mkdir()
        original=os.getcwd()
        try:
            os.chdir(elsewhere);self.run_cli('--once');self.run_cli('--once')
        finally:os.chdir(original)
        self.assertEqual(len(Store(self.db).list()),1)
        self.assertFalse((elsewhere/'state').exists())

    def test_check_and_pretraining_creation_are_separate(self):
        self.value['create_output']=True;self.save()
        report=json.loads(self.run_cli('--check'))
        self.assertTrue(report['ready']);self.assertTrue(report['waiting_for_output'])
        self.assertFalse(self.db.exists());self.assertFalse((self.root/'outputs').exists())
        with patch('tracker.server.serve') as serve:self.run_cli()
        self.assertTrue((self.root/'outputs').is_dir());self.assertTrue(self.db.exists())
        self.assertEqual(serve.call_args.kwargs['port'],0)

    def test_batch_then_live_then_restart_share_identity(self):
        self.output();self.run_cli('--once')
        with patch('tracker.server.serve') as serve:
            self.run_cli();self.run_cli('--port','0')
        self.assertEqual(serve.call_count,2);self.assertEqual(len(definitions(Store(self.db))),1)
        self.assertEqual(len(Store(self.db).list()),1)

    def test_headless_check_works_while_the_configured_ui_port_is_busy(self):
        self.output()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            self.value['port']=listener.getsockname()[1];self.save()
            self.assertTrue(json.loads(self.run_cli('--check'))['ready'])
        self.assertFalse(self.db.exists())

    def test_pretraining_creation_does_not_hide_a_missing_mount_after_capture(self):
        self.value['create_output']=True;self.save();self.output();self.run_cli('--once')
        original=self.root/'outputs';moved=self.root/'temporarily-unmounted'
        self.assertEqual(original.resolve().parent,self.root.resolve())
        self.assertEqual(moved.resolve().parent,self.root.resolve())
        original.rename(moved)
        for mode in ('--check','--once'):
            with self.assertRaises(SystemExit):self.run_cli(mode)
            self.assertFalse(original.exists())
        self.assertEqual(len(Store(self.db).list()),1)

    def test_partial_line_never_reports_a_complete_batch(self):
        self.output(partial=True)
        with self.assertRaises(SystemExit) as caught:self.run_cli('--once')
        self.assertEqual(caught.exception.code,1);self.assertEqual(len(Store(self.db).list()),0)
        with (self.root/'outputs/records.jsonl').open('a') as f:f.write('\n')
        self.run_cli('--once');self.run_cli('--once')
        self.assertEqual(len(Store(self.db).list()),1)

    def test_snapshot_completion_is_explicit_and_preserved(self):
        self.value['source'].update(mode='snapshots',snapshot_state='complete');self.save()
        (self.root/'outputs').mkdir()
        (self.root/'outputs/a.json').write_text(json.dumps({'trajectory_format':'generation/1','prompt':'Q','completion':'A'}))
        self.run_cli('--once')
        self.assertEqual(Store(self.db).latest_revision('job/worker','a.json')['state'],'complete')

    def test_invalid_config_and_conflicting_flags_fail_without_workspace_creation(self):
        for update in [{'schema':'bad'},{'command':'anything'},{'port':True},{'create_output':'yes'}]:
            self.profile.write_text(json.dumps({**self.value,**update}))
            with self.assertRaises(InputError):read(self.profile)
        self.save()
        for args in [('--open','--once'),('--open','--check')]:
            with self.assertRaises(SystemExit):self.run_cli(*args)
        self.assertFalse(self.db.exists())

    def test_cloud_uri_and_profile_size_boundaries(self):
        self.value['source']['root']='s3://bucket/job';self.save()
        self.assertEqual(read(self.profile)['source']['root'],'s3://bucket/job')
        self.value['source']['root']='s3://bucket/job#secret';self.save()
        with self.assertRaises(InputError):read(self.profile)
        self.profile.write_text(' '* (128*1024+1))
        with self.assertRaises(InputError):read(self.profile)

    def test_setup_saved_launch_is_exclusive_and_uses_explicit_root_scope(self):
        self.profile.unlink()
        with redirect_stdout(io.StringIO()):main(['setup','--mode','exports','--stage','before','--save-launch',str(self.profile)])
        result=read(self.profile)
        self.assertEqual(json.loads(self.profile.read_text())['database'],'.tracker/tracker.sqlite')
        self.assertEqual(result['source']['root'],str((self.root/'outputs').resolve()))
        self.assertTrue(result['create_output'])
        prior=self.profile.read_bytes()
        with self.assertRaises(SystemExit),redirect_stdout(io.StringIO()):main(['setup','--save-launch',str(self.profile)])
        self.assertEqual(self.profile.read_bytes(),prior)


if __name__=='__main__':unittest.main()
