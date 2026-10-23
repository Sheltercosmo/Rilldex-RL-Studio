"""Approach observation contracts; authored choices do not measure model accuracy."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

from rilldex import models,candidate
from tracker import method_comparison as methods,semantic_workspace as workspace,semantic_watch as worker
from tracker.jev import DEFAULT_MODEL
from tracker.schema import digest,InputError
from tracker.semantic_extraction import Pipeline,read,write
from tracker.semantic_budget import BudgetReached
from tracker.semantic_catalog import load
from tracker.store import Store
from research.method_comparison_trial import fixture as method_fixture,CASES
from tests.test_method_comparison import native_response
from tests.test_pilot_execution_reports import fixture,transport
from tests import test_installed_models as installed


class NativeMethodTests(TestCase):
    def native(self):
        run,doc=method_fixture(CASES[0])
        actions=[u for u in doc['units'] if u['kind']=='action']
        events={e['id']:e for e in run['events']}
        for i,u in enumerate(actions):
            event=events[u['source']['event_id']]
            event.update(tool='query_records',arguments={'query':'retry '+str(i)},arguments_available=True)
            event.pop('raw_arguments',None)
        doc['source_hash']=digest(run)
        return run,doc,actions

    def test_native_fields_and_prefix_are_preserved_without_changing_old_requests(self):
        run,doc,actions=self.native()
        old=methods.pair_request(run,doc,*[u['id'] for u in actions],methods.DISPATCH_VERSION)
        req=methods.pair_request(run,doc,*[u['id'] for u in actions],methods.NATIVE_VERSION)
        self.assertNotIn('native_dispatches',old['state'])
        self.assertEqual([r['fields']['arguments'] for r in req['state']['native_dispatches']],
                         [{'query':'retry 0'},{'query':'retry 1'}])
        self.assertNotIn('WITHHELD_FUTURE_RESULT',str(req))
        self.assertEqual(req['state']['stage'],'method_comparison')
        self.assertEqual(set(req['questions']),{'work_instance'})

    def test_partial_action_does_not_inherit_whole_native_payload(self):
        run,doc,actions=self.native();ref=actions[-1]['source']
        ref['end']-=1;ref['text']=ref['text'][:-1]
        req=methods.pair_request(run,doc,*[u['id'] for u in actions],methods.NATIVE_VERSION)
        self.assertIsNone(req['state']['native_dispatches'][-1]['fields'])
        self.assertIn('partial action',req['state']['native_dispatches'][-1]['scope'])

    def test_stop_between_comparability_and_procedure_reuses_first_decision(self):
        run,doc,_=self.native();seen=[];progress=[]
        with TemporaryDirectory() as root:
            def decide(req):
                if seen:raise BudgetReached({'limit':'jev_requests'})
                seen.append(digest(req));return native_response(req)
            engine=Pipeline(root,None,decide)
            with self.assertRaises(BudgetReached):
                methods.execute(run,doc,engine,methods.NATIVE_VERSION,progress.append)
            self.assertEqual(progress[-1]['coverage'],dict(eligible_pairs=1,inspected_pairs=0,pending_pairs=1,unavailable_pairs=0))
            self.assertEqual(progress[-1]['observations'][0]['work_instance'],'same_work_instance')
            self.assertEqual(progress[-1]['observations'][0]['status'],'pending')
            def finish(req):
                self.assertNotIn('work_instance',req['questions']);return native_response(req,procedure='reconfigured_procedure')
            engine=Pipeline(root,None,finish)
            result,audit=methods.execute(run,doc,engine,methods.NATIVE_VERSION,progress.append)
            self.assertTrue(audit['argmax_replayed'])
            self.assertEqual(result['counts']['comparisons'],{'reconfigured_procedure':1})
            self.assertEqual([r['status'] for r in progress][-2:],['validating','complete'])
            self.assertEqual(progress[-1]['coverage']['pending_pairs'],0)
            self.assertEqual(methods.load(run,doc,root)['observations'][0]['comparison'],'reconfigured_procedure')

    def test_large_native_payload_and_group_disagreement_remain_explicit(self):
        run,doc,actions=self.native();events={e['id']:e for e in run['events']}
        events[actions[-1]['source']['event_id']]['arguments']['query']='x'*methods.MAX_CHARS
        doc['source_hash']=digest(run);progress=[]
        result=methods.build(run,doc,lambda _:self.fail('No call for an oversized request'),methods.NATIVE_VERSION,progress.append)
        self.assertEqual(result['counts']['not_inspected_pairs'],1)
        self.assertEqual(progress[-1]['coverage']['unavailable_pairs'],1)
        self.assertEqual(progress[-1]['coverage']['inspected_pairs'],0)
        run,doc,_=self.native()
        def disagree(req):
            self.assertEqual(set(req['questions']),{'work_instance'})
            return {'work_instance':{'value':'different_work'}},digest(req)
        result=methods.build(run,doc,disagree,methods.NATIVE_VERSION)
        self.assertEqual(result['observations'][0]['comparison'],'different_work')
        self.assertEqual(result['observations'][0]['stated_basis'],'not_inspected')

    def test_no_history_keeps_legacy_receipts_unchanged(self):
        run,doc,_=self.native();doc.pop('work_history')
        old=methods.build(run,doc,lambda _:self.fail('No comparisons'))
        self.assertNotIn('counts',old)
        current=methods.build(run,doc,lambda _:self.fail('No comparisons'),methods.NATIVE_VERSION)
        self.assertEqual(current['counts']['eligible_pairs'],0)


class PilotApproachTests(TestCase):
    setUp=installed.InstalledModelTests.setUp

    def old_pilot(self):
        run=fixture();run['metadata']['experiment']='approach-controls'
        store=Store(self.root/'approaches.sqlite');store.add([run]);directory=self.root/'pilot'
        config=candidate.settings();options=worker.behavior_options();options.pop('method_comparison_version')
        write(directory/'model.json',dict(adapter=candidate.VERSION,endpoint=config['endpoint'],model=config['model'],
                                         decision_model=DEFAULT_MODEL,**options))
        result=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=transport)
        return store,run,directory,result

    def test_upgrade_pause_resume_publish_worker_and_monitor_without_reproposal(self):
        store,run,directory,original=self.old_pilot()
        self.assertEqual(original['layers']['method_comparison']['status'],'not_requested')
        before=read(directory/'extraction/results'/f"{run['id']}.json")
        old_observer=parse_qs(urlsplit(original['map_url']).query)['observer'][0]
        old=load(run,old_observer,store);used=original['provider_usage']['providers']['jev']['attempts'];calls=len(self.calls)
        seen=[]
        def only_methods(req):
            self.assertEqual(req['state']['stage'],'method_comparison')
            seen.append(set(req['questions']));return transport(req)
        partial=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=used+1,input_bytes=5000000,
                             transport=only_methods,inspect_approaches=True)
        self.assertEqual(partial['status'],'budget_reached')
        self.assertFalse(partial['approach_comparisons_available'])
        self.assertEqual(partial['layers']['method_comparison']['coverage']['pending_pairs'],1)
        from tracker.model_pilot import ModelPilotService
        service=ModelPilotService(store);service.current=read(directory/'pilot-result.json')
        self.assertEqual(service.status()['pilot']['method_comparison']['coverage']['pending_pairs'],1)
        final=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=used+2,input_bytes=5000000,transport=only_methods)
        self.assertEqual(seen,[{'work_instance'},{'comparison','stated_basis'}])
        self.assertEqual(final['status'],'complete_local_extraction')
        self.assertTrue(final['approach_comparisons_available'])
        self.assertIn('level=work',final['work_map_url'])
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(read(directory/'extraction/results'/f"{run['id']}.json"),before)
        self.assertEqual(workspace.audit(directory/'extraction')['method_comparison']['selected_pairs'],1)
        observer=parse_qs(urlsplit(final['map_url']).query)['observer'][0]
        mapped=load(run,observer,store)
        self.assertEqual(mapped['document']['method_comparison']['observations'][0]['comparison'],'same_procedure')
        self.assertEqual(load(run,old_observer,store),old)
        followed=models.watch(store,self.root/'watch',experiment='approach-controls',from_pilot=directory,
            transport=lambda _:self.fail('Exact pilot requests must be reused'))
        self.assertEqual(followed['used'],worker.ZERO);self.assertEqual(followed['current_published'],1)
        from tracker import monitoring
        monitor=next(m for m in monitoring.definitions(store) if m.get('analysis',{}).get('measure')=='procedure_change_fraction')
        value=monitoring.values(store,monitor['id'],[run['id']])[run['id']]
        self.assertEqual((value['value'],value['denominator'],value['unknown']),(0,1,0))
        self.assertEqual(len(self.calls),calls)

    def test_context_limit_publishes_unknown_instead_of_a_negative_finding(self):
        store,run,directory,original=self.old_pilot();calls=len(self.calls)
        with patch.object(methods,'MAX_CHARS',1):
            final=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,
                transport=lambda _:self.fail('Oversized comparison must not spend'),inspect_approaches=True)
            self.assertEqual(final['status'],'complete_local_extraction')
            self.assertEqual(final['layers']['method_comparison']['coverage']['unavailable_pairs'],1)
            observer=parse_qs(urlsplit(final['map_url']).query)['observer'][0]
            mapped=load(run,observer,store)
            self.assertEqual(mapped['document']['method_comparison']['counts']['not_inspected_pairs'],1)
        self.assertEqual(len(self.calls),calls)

    def test_worker_requires_saved_method_result_and_configuration_dependencies(self):
        store,run,directory,_=self.old_pilot()
        final=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,
                           transport=transport,inspect_approaches=True)
        from tracker.semantic_extraction import load_extraction
        root=directory/'extraction';options=worker.behavior_options()
        doc=load_extraction(run,root,action_target_version=options['action_target_version'],plan_relation_version=options['plan_relation_version'])['document']
        path=root/'results'/f'{digest(doc)}.json';path.rename(path.with_suffix('.saved'))
        with self.assertRaisesRegex(InputError,'comparison result is missing'):
            worker.materialize('test',dict(workspace_options=options,label='Test'),run,root)
        with self.assertRaisesRegex(InputError,'work-target links'):
            workspace.initialize(self.root/'invalid',run,method_comparison_version=methods.NATIVE_VERSION)
