import ast
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from tracker.deployment_setup import plan
from tracker.schema import InputError


class SetupTests(unittest.TestCase):
    def test_local_stages_use_same_identity_for_replay_and_follow(self):
        values=dict(root='/jobs/a b',producer='run/worker-0',experiment='run')
        for stage in ('before','during','after'):
            p=plan({**values,'stage':stage})
            captures=[s for s in p['steps'] if '--producer' in s['code']]
            for s in captures:
                args=shlex.split(s['code'])
                self.assertEqual(args[args.index('--producer')+1],'run/worker-0')
                self.assertIn('/jobs/a b',args)
            self.assertEqual(any('--once' in s['code'] for s in p['steps']),stage=='after')
            self.assertEqual(p['connection']['root'],'/jobs/a b')

    def test_remote_ports_match_and_no_local_open_on_host(self):
        p=plan({'case':'remote','host':'person@gpu-host','port':8899})
        self.assertIn('8899:127.0.0.1:8899',p['steps'][-1]['code'])
        self.assertNotIn('--open',p['steps'][1]['code'])
        self.assertIsNone(p['connection'])

    def test_docker_is_loopback_persistent_read_only_and_requires_host_absolute_path(self):
        for root in ('/jobs/run','C:/jobs/a b'):
            p=plan({'case':'docker','root':root})
            cmd=shlex.split(p['steps'][1]['code'])
            self.assertIn('127.0.0.1:8765:8765',cmd)
            self.assertIn('type=volume,source=rilldex-data,target=/data',cmd)
            self.assertIn('type=bind,source='+root+',target=/outputs,readonly',cmd)
        for root in ('./outputs','/jobs/a,b'):
            with self.assertRaises(InputError):plan({'case':'docker','root':root})

    def test_cloud_sdk_and_notebook_python(self):
        for root,sdk in [('s3://bucket/a','s3fs'),('gs://bucket/a','gcsfs')]:
            self.assertIn(sdk,plan({'case':'cloud','root':root})['steps'][0]['code'])
        p=plan({'case':'notebook','root':"/tmp/a'日本",'producer':'x/0'})
        ast.parse(p['steps'][0]['code']);ast.parse(p['steps'][1]['code'])
        with self.assertRaises(InputError):plan({'case':'cloud','root':'s3://secret@bucket/a'})

    def test_offline_avoids_sender_and_preserves_pending_warning(self):
        p=plan({'case':'offline'})
        ast.parse(p['steps'][0]['code'])
        self.assertNotIn('.start()\n',p['steps'][0]['code'])
        self.assertIn('pending queue limits',p['resume'])

    def test_remote_host_shell_is_independent_of_workstation(self):
        p=plan({'case':'remote','shell':'powershell','collector_shell':'posix'})
        self.assertTrue(p['steps'][0]['code'].startswith('python3 '))
        self.assertTrue(p['steps'][-1]['code'].startswith("& 'ssh'"))
        self.assertIn('ExitOnForwardFailure=yes',p['steps'][-1]['code'])
        self.assertTrue(p['launch_command'].startswith('python3 '))

    def test_snapshot_state_and_launch_file_match_all_routes(self):
        for case in ('local','remote','cloud','docker','notebook'):
            options={'case':case,'mode':'snapshots','snapshot_state':'complete'}
            if case=='docker':options['root']='/jobs/output'
            p=plan(options)
            self.assertTrue(any('complete' in s['code'] for s in p['steps']))
            if p['launch_file']:self.assertEqual(p['launch_file']['source']['snapshot_state'],'complete')
        # A stopped training job can still have unfinished rollouts.
        self.assertEqual(plan({'stage':'after','mode':'snapshots'})['launch_file']['source']['snapshot_state'],'in_progress')

    def test_cloud_setup_reuses_actual_uri_rules_and_auto_port_is_local_only(self):
        for root in ('s3://bucket/job#fragment','gs://bucket/../job'):
            with self.assertRaises(InputError):plan({'case':'cloud','root':root})
        self.assertIsNone(plan({'port':0})['browser_url'])
        with self.assertRaises(InputError):plan({'case':'remote','port':0})

    def test_shell_quoting_and_invalid_inputs(self):
        dangerous="/jobs/a' $(echo nope) `id`"
        args=shlex.split(plan({'root':dangerous})['steps'][0]['code'])
        self.assertIn(dangerous,args)
        ps=plan({'shell':'powershell','root':dangerous})['steps'][0]['code']
        self.assertTrue(ps.startswith("& 'python'"))
        self.assertIn("a'' $(echo nope) `id`",ps)
        for options in ({'host':'-oProxyCommand=bad','case':'remote'},{'root':'x\ny'},{'port':True},{'stage':'maybe'}):
            with self.assertRaises(InputError):plan(options)

    def test_generated_posix_cli_check_replay_and_setup_need_no_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'outputs';root.mkdir();db=Path(tmp)/'workspace.sqlite'
            p=plan({'root':str(root),'database':str(db),'stage':'after','mode':'exports','experiment':'control'})
            for s in p['steps'][:2]:
                args=shlex.split(s['code']);args[0]=sys.executable
                r=subprocess.run(args,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run([sys.executable,'-m','rilldex','setup','--case','offline'],capture_output=True,text=True)
            self.assertEqual(json.loads(r.stdout)['case'],'offline')


if __name__=='__main__':unittest.main()
