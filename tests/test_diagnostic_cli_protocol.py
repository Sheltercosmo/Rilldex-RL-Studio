import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import diagnostic_cli,diagnostic_worker_cli,diagnostic_worker as worker
from tracker.semantic_extraction import write
from tracker.schema import InputError


class DiagnosticCLIProtocolTests(unittest.TestCase):
    def test_new_cli_paths_select_current_search(self):
        parser=argparse.ArgumentParser();commands=parser.add_subparsers()
        diagnostic_cli.configure(commands);diagnostic_worker_cli.configure(commands)
        with TemporaryDirectory() as folder:
            args=parser.parse_args(['monitors',folder,'--run-id','r'])
            self.assertEqual(worker.selected_implementation(folder,args.protocol),'search')
            args=parser.parse_args(['monitor-rollouts','plan',folder,'--all-latest'])
            self.assertEqual(worker.selected_implementation(folder,args.protocol,worker=True),'search')

    def test_saved_single_rollout_families_survive_default_change(self):
        for family in ('search','requirements','chains','source'):
            with self.subTest(family=family),TemporaryDirectory() as folder:
                schema=worker.implementation(family).protocol()['schema']
                write(Path(folder)/'result.json',{'protocol':{'schema':schema}})
                self.assertEqual(worker.selected_implementation(folder),family)
                self.assertEqual(worker.selected_implementation(folder,'search'),'search')

    def test_partial_workspace_protocol_precedes_result(self):
        with TemporaryDirectory() as folder:
            write(Path(folder)/'protocol.json',{'schema':'requirement-diagnostics/5'})
            self.assertEqual(worker.selected_implementation(folder),'requirements')
            write(Path(folder)/'protocol.json',{'schema':'unrecognized/1'})
            with self.assertRaises(InputError):worker.selected_implementation(folder)

    def test_worker_resumes_selected_family(self):
        with TemporaryDirectory() as folder:
            write(Path(folder)/'worker.json',{'implementation':'chains'})
            self.assertEqual(worker.selected_implementation(folder,worker=True),'chains')
            self.assertEqual(worker.selected_implementation(folder,'requirements',worker=True),'requirements')
