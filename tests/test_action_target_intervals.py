"""Target/7 source boundaries, resume behavior and declaration completeness."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tracker import action_scope_pages as pages, action_target_intervals as intervals, action_targets as targets
from tracker.schema import digest, dumps
from tracker.semantic_budget import BudgetReached
from tracker.semantic_extraction import Pipeline, load_extraction, read, write
from tests.test_action_scope_pages import fixture, transport as legacy_transport
from tests.test_plan_relations import Provider
from scripts.evaluate_generated_target_interval_production import declared_controls


def transport(request):
    if request['state']['stage']!='action_targets':return legacy_transport(request)
    return dict(model=request['model'],answers={k:dict(type='choice',probabilities={c:float(c=='same_work_target')
        for c in q['criteria']}) for k,q in request['questions'].items()})


class TargetIntervalTests(unittest.TestCase):
    def extracted(self,folder,count=5):
        run=fixture(count);engine=Pipeline(folder,Provider(Path(folder)/'candidates'),transport)
        return run,engine,engine.run(run)

    def test_resume_after_each_pair_and_offline_audit_keep_prior_version_separate(self):
        with TemporaryDirectory() as folder:
            run,engine,extraction=self.extracted(folder);calls=[];progress=Path(folder)/'progress.json'
            def stop(request):
                if len(calls)==4:raise BudgetReached({'limit':'jev_requests'})
                self.assertEqual(len(request['questions']),1)
                calls.append(digest(request));return transport(request)
            engine.transport=stop
            with self.assertRaises(BudgetReached):
                targets.execute(run,extraction,engine,version=targets.INTERVAL_VERSION,progress=lambda value:write(progress,value))
            partial=read(progress);current=next(r for r in partial['actions'] if r['status']=='inspecting')
            self.assertEqual(len(current['pairs']),1)
            self.assertNotIn(current['action_unit_id'],[r['from'] for r in partial['relations']])
            self.assertEqual(partial['coverage']['pending_pairs'],6)
            def resume(request):
                self.assertNotIn(digest(request),calls);calls.append(digest(request));return transport(request)
            engine.transport=resume
            result,audit=targets.execute(run,extraction,engine,version=targets.INTERVAL_VERSION)
            self.assertTrue(audit['argmax_replayed'])
            self.assertEqual(result['coverage']['compared_pairs'],10)
            self.assertEqual(len(calls),10)
            self.assertEqual(result['coverage']['pending_pairs'],0)
            self.assertEqual(len(result['relations']),4)
            self.assertNotEqual(targets.path_for(folder,extraction,targets.PAGED_VERSION),targets.path_for(folder,extraction,targets.INTERVAL_VERSION))
            view=load_extraction(run,folder,action_target_version=targets.INTERVAL_VERSION)
            self.assertTrue(view['document']['work_paths']['dispatch_coverage']['each_action_once'])
            self.assertEqual(len(view['document']['work_paths']['paths']),1)
            engine.transport=lambda _:self.fail('Completed decisions should replay')
            self.assertEqual(targets.execute(run,extraction,engine,version=targets.INTERVAL_VERSION)[0],result)

    def test_interleaved_other_context_is_absent_even_when_trajectory_is_reused(self):
        with TemporaryDirectory() as folder:
            run,_,extraction=self.extracted(folder,3)
            action_events=[e for e in run['events'] if e['kind']=='action']
            middle=action_events[1]
            middle['context_id']='other-context'
            for event in run['events']:
                if event.get('source_call_id')==middle.get('call_id') and event['kind']=='feedback':event['context_id']='other-context'
            extraction['source_hash']=digest(run)
            action=extraction['units'][-1];pool,excluded=pages.candidate_scope(run,extraction,action)
            self.assertEqual(len(pool),1);self.assertEqual(excluded[0]['reason'],'different_recorded_context')
            document=intervals.local_document(run,extraction)
            request=intervals.request(run,document,action,pool[0])
            self.assertNotIn(middle['text'],dumps(request['state']))
            self.assertNotIn(middle['id'],[r['event_id'] for r in request['state']['source_ranges']])

    def test_recorded_contracts_are_exact_bounded_and_missing_definitions_stay_missing(self):
        controls=list(declared_controls())
        for case in controls:
            source=case['source'];extraction=case['extraction'];prior,current=extraction['units']
            pool=dict(id='a0',**targets.local(prior));document=intervals.local_document(source,extraction)
            request=intervals.request(source,document,current,pool)
            if case['case_id']=='undeclared_operations':
                self.assertNotIn('recorded_endpoint_contracts',request['state'])
                self.assertNotIn('tool_catalog',request['state'])
            else:
                rows=request['state']['recorded_endpoint_contracts']
                self.assertEqual(len(rows),2)
                events={e['id']:e for e in source['events']}
                for row in rows:
                    self.assertEqual(row['definitions']['tool_contract']['definition_text'],dumps(events[row['event_id']]['tool_contract']['definition']))
                self.assertEqual(request['state']['missingness']['required_truncated_event_ids'],[])
        case=deepcopy(controls[0]);source=case['source'];extraction=case['extraction']
        for event in source['events']:
            if event.get('tool_contract'):event['tool_contract']['definition']['function']['description']='x'*9000
        extraction['source_hash']=digest(source)
        prior,current=extraction['units'];pool=dict(id='a0',**targets.local(prior));document=intervals.local_document(source,extraction)
        request=intervals.request(source,document,current,pool)
        self.assertTrue(request['state']['missingness']['required_truncated_event_ids'])
        self.assertEqual(len(request['state']['recorded_endpoint_contracts'][0]['definitions']['tool_contract']['definition_text']),8000)
        result=pages.build(source,extraction,lambda _:self.fail('Required truncated declaration is unmeasured'),version=targets.INTERVAL_VERSION)
        self.assertEqual(result['status'],'needs_evidence')
        self.assertEqual(result['coverage']['pending_pairs'],1)
        self.assertEqual(result['relations'],[])

    def test_byte_overflow_preserves_unmeasured_pairs_without_negative_links(self):
        with TemporaryDirectory() as folder:
            run,_,extraction=self.extracted(folder,3)
            with patch.object(pages,'MAX_BYTES',1):
                result=pages.build(run,extraction,lambda _:self.fail('Packet must remain whole'),version=targets.INTERVAL_VERSION)
            self.assertEqual(result['coverage']['oversized_pairs'],3)
            self.assertEqual(result['coverage']['pending_pairs'],3)
            self.assertEqual(result['relations'],[])

    def test_unrelated_catalog_omissions_do_not_block_complete_endpoint_definitions(self):
        case=deepcopy(next(declared_controls()));run=case['source'];extraction=case['extraction']
        run['raw']['tools'].extend(dict(type='function',function=dict(name='unused_'+str(i),description='Unrelated tool. '*200,
            parameters=dict(type='object'))) for i in range(20))
        extraction['source_hash']=digest(run)
        prior,current=extraction['units'];document=intervals.local_document(run,extraction)
        request=intervals.request(run,document,current,dict(id='a0',**targets.local(prior)))
        missing=request['state']['missingness']
        self.assertEqual(missing['required_truncated_event_ids'],[])
        self.assertGreater(missing['optional_omitted_definition_count'],0)
        self.assertTrue(all(r['definitions']['tool_contract']['source_characters']<8000
                            for r in request['state']['recorded_endpoint_contracts']))
        result=pages.build(run,extraction,lambda req:({'a0':{'value':'same_work_target'}},digest(req)),version=targets.INTERVAL_VERSION)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['coverage']['compared_pairs'],1)
        self.assertEqual(result['coverage']['pending_pairs'],0)
