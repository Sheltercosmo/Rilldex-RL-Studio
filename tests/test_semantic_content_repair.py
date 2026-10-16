from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import semantic_content_repair as repair,work_target_refinement as refine
from tracker.schema import InputError,digest
from tracker.semantic_extraction import FileCandidates,Pipeline,read,write,generation_request,audit_result,load_extraction
from tests.test_semantic_extraction import fixture,response,proposals
from tests.test_work_target_refinement import choose


class ContentRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);base=self.root/'base';self.parent=self.root/'refined';self.out=self.root/'repair';self.run=fixture()
        engine=Pipeline(base,FileCandidates(base/'candidates'),response)
        pending=engine.run(self.run);unit=pending['units'][0]
        req=generation_request(self.run,unit['source'],'orient')
        write(base/'candidates/responses'/f'{digest(req)}.json',proposals(req))
        original=engine.run(self.run);write(base/'runs'/f'{self.run["id"]}.json',self.run)
        refine.initialize(self.parent,base,self.run['id']);refine.execute(self.parent,choose('c0'))
        self.old=read(self.parent/'results'/f'{self.run["id"]}.json');self.uid=self.old['units'][0]['id']
        repair.initialize(self.out,self.parent,self.run['id'],[self.uid])

    def supply(self):
        row=repair.prepare(self.out)['requests'][0];req=read(row['request_path'])
        proposed=proposals(req)
        proposed['candidates'][0]['fields']['work_target']['text']='Add the decorator to the reproduction class.'
        write(self.out/'repair-candidates/responses'/f'{row["request_hash"]}.json',proposed)
        return row,req

    def test_refined_parent_can_be_repaired_without_changing_base_and_replays(self):
        self.supply();result=repair.execute(self.out,choose('c1'),max_calls=1)
        self.assertEqual(result['status'],'complete_local_extraction')
        selected=read(self.out/'results'/f'{self.run["id"]}.json');unit=selected['units'][0]
        self.assertNotIn('target_refinement',unit);self.assertIn('content_repair',unit)
        self.assertEqual(unit['activity_request'],self.old['units'][0]['activity_request'])
        self.assertEqual(unit['source'],self.old['units'][0]['source'])
        self.assertEqual(unit['content']['work_target']['text'],'Add the decorator to the reproduction class.')
        self.assertEqual(read(self.parent/'results'/f'{self.run["id"]}.json'),self.old)
        self.assertTrue(repair.audit(self.out)['validation']['argmax_replayed'])
        self.assertTrue(load_extraction(self.run,self.out)['available'])
        again=repair.execute(self.out,lambda _:self.fail('Must replay'),max_calls=0)
        self.assertEqual(again['budget_used']['jev_requests'],0)

    def test_missing_proposal_budget_and_rejection_preserve_explicit_gaps(self):
        waiting=repair.execute(self.out,lambda _:self.fail('No proposal, no model call'))
        self.assertEqual(waiting['status'],'needs_work');self.assertEqual(len(waiting['pending']),1)
        self.assertEqual(repair.audit(self.out)['status'],'needs_work')
        self.supply();stopped=repair.execute(self.out,lambda _:self.fail('Budget before transport'))
        self.assertIn('budget_stop',stopped)
        result=repair.execute(self.out,choose('no_suitable_candidate'),max_calls=1)
        self.assertEqual(result['status'],'needs_work')
        self.assertFalse((self.out/'results'/f'{self.run["id"]}.json').exists())
        self.assertEqual(repair.audit(self.out)['status'],'needs_work')

    def test_changed_candidate_source_or_declaration_is_rejected(self):
        row,req=self.supply();repair.execute(self.out,choose('c1'),max_calls=1)
        original=read(self.out/'results'/f'{self.run["id"]}.json')
        bad=deepcopy(original);bad.pop('content_repair_run')
        with self.assertRaises(InputError):audit_result(self.run,bad,self.out)
        path=self.out/'repair-candidates/responses'/f'{row["request_hash"]}.json'
        proposal=read(path);proposal['candidates'][0]['fields']['summary']['text']='Different summary'
        write(path,proposal)
        with self.assertRaisesRegex(InputError,'differs'):audit_result(self.run,original,self.out)

    def test_wrong_scope_and_more_than_two_candidates_fail_before_selection(self):
        with self.assertRaises(InputError):repair.initialize(self.root/'invalid',self.parent,self.run['id'],['unknown'])
        row,req=self.supply();proposal=read(self.out/'repair-candidates/responses'/f'{row["request_hash"]}.json')
        unit=self.old['units'][0];proposal['candidates']*=3
        with self.assertRaisesRegex(InputError,'two'):repair.selection_request(self.run,unit,proposal,None)

    def test_generation_does_not_show_previous_bad_contents_or_future_source(self):
        row=repair.prepare(self.out)['requests'][0];req=read(row['request_path'])
        self.assertNotIn('original_selected_bundle',str(req))
        self.assertNotIn('FUTURE result',str(req))
        self.assertIn('contribution_content_rule',req)
        self.assertEqual(req['activity'],'orient')

    def test_repaired_workspace_registers_and_preserves_history_dependencies(self):
        import argparse
        import contextlib
        import io
        import json
        from tracker import semantic_cli,semantic_catalog,semantic_collection,semantic_history
        from tracker.store import Store
        self.supply();repair.execute(self.out,choose('c1'),max_calls=1)
        view=load_extraction(self.run,self.out)
        protocol=semantic_collection.protocol(view,self.out)
        self.assertEqual(protocol['scope']['content_repair']['unit_ids'],[self.uid])
        history=self.root/'history'
        semantic_history.initialize(history,self.out,self.run['id'])
        copied=semantic_history.load(history)[2]
        self.assertEqual(copied,view['raw_extraction'])
        self.assertTrue(repair.audit(history)['validation']['argmax_replayed'])
        parser=argparse.ArgumentParser();semantic_cli.configure(parser.add_subparsers(dest='command'))
        args=parser.parse_args(['semantic','register',str(self.out),'--label','Repaired contents'])
        store=Store(self.root/'registered.sqlite');store.add([self.run]);captured=io.StringIO()
        with contextlib.redirect_stdout(captured):semantic_cli.execute(args,store)
        registered=json.loads(captured.getvalue())
        self.assertEqual(registered['run_id'],self.run['id'])
        self.assertTrue(semantic_catalog.load(self.run,registered['observer'],store)['available'])


if __name__=='__main__':unittest.main()
