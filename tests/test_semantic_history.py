from pathlib import Path
import shutil
import tempfile
import unittest
from tracker import semantic_history,action_targets,feedback_assessments
from tracker.schema import InputError
from tracker.semantic_extraction import Pipeline,read,write,load_extraction
from tests.test_feedback_assessments import fixture,Provider,transport as local_transport


def transport(req):
    stage=req['state']['stage']
    if stage not in {'action_target_correspondence','action_target_pair_relation'}:return local_transport(req)
    value='a0' if stage=='action_target_correspondence' else 'same_work_target'
    return {'model':req['model'],'answers':{'choice':{'type':'choice','probabilities':{k:int(k==value) for k in req['questions']['choice']['criteria']}}}}


class HistoryRebuildTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.base=self.root/'base';self.prior=self.root/'prior';self.output=self.root/'history'
        self.run=fixture();self.extraction=Pipeline(self.base,Provider(self.base/'candidates'),transport).run(self.run)
        write(self.base/'runs'/f'{self.run["id"]}.json',self.run)
        shutil.copytree(self.base,self.prior)
        engine=Pipeline(self.prior,None,transport)
        action_targets.execute(self.run,self.extraction,engine,version=action_targets.SCOPE_VERSION)
        feedback_assessments.execute(self.run,self.extraction,engine)

    def test_exact_rebuild_zero_transport_complete_map_and_retained_parent(self):
        semantic_history.initialize(self.output,self.base,self.run['id'],[self.prior])
        receipt=semantic_history.execute(self.output,lambda _:self.fail('All dependency requests are unchanged'),max_calls=0)
        self.assertEqual(receipt['status'],'complete');self.assertEqual(receipt['budget_used']['jev_requests'],0)
        self.assertGreater(receipt['reused_this_execution'],0)
        audit=semantic_history.audit(self.output)
        self.assertEqual(audit['work_history']['recurring_assignments'],1)
        self.assertGreater(audit['assessments']['selected_relations'],0)
        self.assertFalse((self.base/'action_targets').exists())
        replay=semantic_history.execute(self.output,lambda _:self.fail('Saved decisions replay'))
        self.assertEqual(replay['reused_this_execution'],0)
        self.assertTrue(load_extraction(self.run,self.output)['document']['work_history']['available'])

    def test_missing_decision_stops_before_transport_and_cannot_publish_partial_history(self):
        semantic_history.initialize(self.output,self.base,self.run['id'],[])
        receipt=semantic_history.execute(self.output,lambda _:self.fail('Zero call budget'))
        self.assertEqual(receipt['status'],'budget_reached')
        with self.assertRaisesRegex(InputError,'History stages are incomplete'):
            load_extraction(self.run,self.output)

    def test_configuration_and_separate_output_are_enforced(self):
        with self.assertRaisesRegex(InputError,'separate output'):
            semantic_history.initialize(self.base/'child',self.base,self.run['id'])
        semantic_history.initialize(self.output,self.base,self.run['id'],[self.prior])
        with self.assertRaisesRegex(InputError,'configuration changed'):
            semantic_history.initialize(self.output,self.base,self.run['id'],[])
        changed=read(self.output/'results'/f'{self.run["id"]}.json');changed['note']='changed'
        write(self.output/'results'/f'{self.run["id"]}.json',changed)
        with self.assertRaisesRegex(InputError,'extraction changed'):
            semantic_history.execute(self.output,transport)

    def test_unsupported_frozen_feedback_protocol_stops_before_any_stage(self):
        semantic_history.initialize(self.output,self.base,self.run['id'],[self.prior])
        config=read(self.output/'history-rebuild.json')
        config['feedback_protocol']['dependency_scope']='unsupported-protocol/2'
        write(self.output/'history-rebuild.json',config)
        with self.assertRaisesRegex(InputError,'feedback protocol'):
            semantic_history.execute(self.output,lambda _:self.fail('Protocol validation precedes inference'),max_calls=50)
        self.assertFalse((self.output/'action_targets').exists())
        self.assertFalse((self.output/'attempts').exists())

    def test_explicit_direct_set_protocol_is_frozen_loaded_and_audited(self):
        semantic_history.initialize(self.output,self.base,self.run['id'],[self.prior],reference_rule=feedback_assessments.DIRECT_SET_RULE)
        # Old target decisions are reusable; the new reference request is not.
        receipt=semantic_history.execute(self.output,transport,max_calls=10)
        self.assertEqual(receipt['status'],'complete')
        self.assertGreater(receipt['budget_used']['jev_requests'],0)
        view=load_extraction(self.run,self.output)
        self.assertEqual(view['document']['provenance']['assessment_reference_rule'],feedback_assessments.DIRECT_SET_RULE)
        self.assertEqual(view['validation']['feedback_assessments']['selected_relations'],2)
        semantic_history.audit(self.output)
        with self.assertRaisesRegex(InputError,'configuration changed'):
            semantic_history.initialize(self.output,self.base,self.run['id'],[self.prior])

    def test_documented_register_command_finds_history_run_without_workspace_file(self):
        import argparse
        import contextlib
        import io
        import json
        from tracker import semantic_cli,semantic_catalog
        from tracker.store import Store
        semantic_history.initialize(self.output,self.base,self.run['id'],[self.prior])
        semantic_history.execute(self.output,lambda _:self.fail('Cache only'))
        parser=argparse.ArgumentParser();semantic_cli.configure(parser.add_subparsers(dest='command'))
        args=parser.parse_args(['semantic','register',str(self.output),'--label','Rebuilt history'])
        store=Store(self.root/'registered.sqlite');store.add([self.run]);captured=io.StringIO()
        with contextlib.redirect_stdout(captured):semantic_cli.execute(args,store)
        registered=json.loads(captured.getvalue())
        self.assertEqual(registered['run_id'],self.run['id'])
        self.assertTrue(semantic_catalog.load(self.run,registered['observer'],store)['available'])

    def test_retrieval_protocol_maps_candidates_without_asserting_search_edges(self):
        from tracker.feedback_retrieval import HYBRID_VERSION
        from tracker import graph_store
        semantic_history.initialize(self.output,self.base,self.run['id'],[self.prior],
            reference_rule=feedback_assessments.DIRECT_SET_RULE,linkage_version=feedback_assessments.SOURCE_LINKAGE,retrieval_version=HYBRID_VERSION)
        receipt=semantic_history.execute(self.output,transport,max_calls=10)
        self.assertEqual(receipt['status'],'complete')
        view=load_extraction(self.run,self.output)
        self.assertEqual(view['document']['provenance']['assessment_retrieval'],HYBRID_VERSION)
        candidates=[u for u in view['document']['units'] if u.get('feedback_reference_search')]
        self.assertEqual(len(candidates),3)
        for unit in candidates:
            review=unit['feedback_reference_search']
            self.assertEqual(review['selection_status'],'linked' if review['selected'] else 'no_prior_selected_feedback')
            self.assertLessEqual(len(review['selected']),5)
        semantic_history.audit(self.output)
        # The read path preserves candidate metadata as properties; retrieval creates no relation.
        graph=graph_store.build(self.run,{**view,'observer':{'id':'test-retrieval','label':'Test retrieval'}})
        self.assertEqual(sum(bool(n['properties'].get('feedback_reference_search')) for n in graph['nodes']),3)
        self.assertEqual(sum(e['type']=='assesses' for e in graph['edges']),2)
        bad=read(self.output/'history-rebuild.json');bad['feedback_protocol']['retrieval_version']='future-version'
        write(self.output/'history-rebuild.json',bad)
        with self.assertRaisesRegex(InputError,'feedback protocol'):semantic_history.execute(self.output,transport)
