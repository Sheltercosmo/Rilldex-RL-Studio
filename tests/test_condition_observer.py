from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import contextlib
import io
from tracker import condition_grounding as cg
from tracker.condition_observer import execute,main
from tracker.schema import InputError
from tracker.semantic_extraction import read,write
from research.condition_dispatch_trial import fixture,CASES


class ConditionObserverTests(TestCase):
    @staticmethod
    def send(req):
        stage=req['state']['stage'].removeprefix('condition_grounding_')
        values={'choice':'direct' if stage=='operation' else 'within_scope'} if stage!='evidence' else {'support':'none','contradiction':'none'}
        return {'model':req['model'],'usage':{'input_tokens':20,'output_tokens':2},
                'answers':{k:{'type':'choice','probabilities':{v:1 if v==values[k] else 0 for v in q['criteria']}}
                           for k,q in req['questions'].items()}}

    def test_default_execution_is_cache_only_and_records_pending_work(self):
        run,doc=fixture(CASES[0]);pair=cg.candidates(run,doc)[-1]
        with TemporaryDirectory() as directory:
            result,receipt=execute(run,doc,directory,pair_ids=[pair['id']],send=lambda r:self.fail('No paid calls authorized'))
            self.assertIsNone(result);self.assertEqual(receipt['status'],'needs_budget')
            self.assertEqual(receipt['new_http_attempts'],0)
            self.assertTrue((Path(directory)/'pending_requests'/f'{receipt["pending_request"]}.json').exists())
            self.assertFalse((Path(directory)/'result.json').exists())

    def test_resume_reuses_completed_stages_and_enforces_total_budget(self):
        run,doc=fixture(CASES[0]);pair=cg.candidates(run,doc)[-1]
        with TemporaryDirectory() as directory:
            result,first=execute(run,doc,directory,pair_ids=[pair['id']],maximum=1,send=self.send)
            self.assertIsNone(result);self.assertEqual(first['new_http_attempts'],1)
            result,second=execute(run,doc,directory,pair_ids=[pair['id']],maximum=3,send=self.send)
            self.assertEqual(second['status'],'complete');self.assertEqual(second['new_http_attempts'],2)
            self.assertTrue(second['validation']['raw_argmax_replayed'])
            replay,third=execute(run,doc,directory,pair_ids=[pair['id']],send=lambda r:self.fail('Cache replay called network'))
            self.assertEqual(replay,result);self.assertEqual(third['new_http_attempts'],0)
            self.assertEqual(len(list((Path(directory)/'attempts').glob('*.json'))),3)

    def test_source_selection_and_protocol_cannot_change_in_place(self):
        run,doc=fixture(CASES[0]);pairs=cg.candidates(run,doc)
        with TemporaryDirectory() as directory:
            execute(run,doc,directory,pair_ids=[pairs[-1]['id']])
            for kwargs in [{'pair_ids':[pairs[0]['id']]},{'pair_ids':[pairs[-1]['id']],'protocol':cg.VERSION}]:
                with self.assertRaisesRegex(InputError,'bound to different'):execute(run,doc,directory,**kwargs)
            run2,doc2=fixture(CASES[1])
            with self.assertRaisesRegex(InputError,'bound to different'):execute(run2,doc2,directory)

    def test_unknown_attempt_is_reported_without_retry(self):
        run,doc=fixture(CASES[0]);pair=cg.candidates(run,doc)[-1]
        with TemporaryDirectory() as directory:
            write(Path(directory)/'attempts'/'00001.json',{'status':'outcome_unknown'})
            result,receipt=execute(run,doc,directory,pair_ids=[pair['id']],maximum=3,send=lambda r:self.fail('Unknown attempt retried'))
            self.assertIsNone(result);self.assertEqual(receipt['status'],'needs_attempt_review')
            self.assertEqual(receipt['new_http_attempts'],0)

    def test_cli_pair_listing_does_not_create_a_workspace_or_infer(self):
        run,doc=fixture(CASES[0])
        with TemporaryDirectory() as directory:
            path=Path(directory)/'source.json';write(path,{'run':run,'document':doc});output=io.StringIO()
            with patch('sys.argv',['condition_observer','--input',str(path),'--list-pairs']),contextlib.redirect_stdout(output):main()
            self.assertEqual(len(output.getvalue().strip().splitlines()),2)
            self.assertEqual(list(Path(directory).iterdir()),[path])

    def test_cli_zero_budget_exits_incomplete_instead_of_printing_a_verdict(self):
        run,doc=fixture(CASES[0])
        with TemporaryDirectory() as directory:
            path=Path(directory)/'source.json';workspace=Path(directory)/'observer';write(path,{'run':run,'document':doc})
            with patch('sys.argv',['condition_observer','--input',str(path),'--workspace',str(workspace)]),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as error:main()
            self.assertEqual(error.exception.code,2)
            self.assertEqual(read(workspace/'execution-status.json')['status'],'needs_budget')
