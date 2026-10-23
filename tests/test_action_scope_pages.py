"""Long-run, resume and evidence-boundary checks; authored model decisions."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import action_scope_pages as pages, action_targets as targets
from tracker.adapters import normalize
from tracker.schema import digest
from tracker.semantic_budget import BudgetReached
from tracker.semantic_extraction import Pipeline, load_extraction, read, write
from tests.test_plan_relations import Provider, transport as base_transport


def fixture(count=64):
    return normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':i,'user_message':None,'agent':{'thought':None,'action':f'Inspect item {i}'},
         'environment':f'Observation {i}'} for i in range(count)]})[0]


def transport(req):
    if req['state']['stage']!='action_target_scope_pairs':return base_transport(req)
    return {'model':req['model'],'answers':{
        key:{'type':'choice','probabilities':{c:float(c=='same_work_target') for c in q['criteria']}}
        for key,q in req['questions'].items()}}


class PagedScopeTests(unittest.TestCase):
    def extracted(self, root, count=64):
        run=fixture(count);engine=Pipeline(root,Provider(Path(root)/'candidates'),transport)
        return run, engine, engine.run(run)

    def test_64_actions_all_pairs_resume_mid_page_and_last_match_survives(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,extraction=self.extracted(root)
            saved=Path(root)/'progress.json';calls=[]
            def stop(req):
                if len(calls)==17:raise BudgetReached({'limit':'jev_requests'})
                calls.append(digest(req));return transport(req)
            engine.transport=stop
            with self.assertRaises(BudgetReached):
                targets.execute(run,extraction,engine,version=targets.PAGED_VERSION,
                    progress=lambda value:write(saved,value))
            partial=read(saved)
            self.assertGreater(partial['coverage']['pending_pairs'],0)
            current=next(r for r in partial['actions'] if r['status']=='inspecting')
            self.assertGreater(len(current['pairs']),0)
            self.assertNotIn(current['action_unit_id'],[e['from'] for e in partial['relations']])
            self.assertFalse(targets.path_for(root,extraction,targets.PAGED_VERSION).exists())
            def resume(req):
                self.assertNotIn(digest(req),calls)
                calls.append(digest(req));return transport(req)
            engine.transport=resume
            result,audit=targets.execute(run,extraction,engine,version=targets.PAGED_VERSION)
            self.assertTrue(audit['argmax_replayed'])
            self.assertEqual(result['coverage']['compared_pairs'],64*63//2)
            self.assertEqual(result['coverage']['pending_pairs'],0)
            self.assertEqual(len(calls),sum((n+15)//16 for n in range(1,64)))
            units=extraction['units']
            self.assertEqual([(e['from'],e['to']) for e in result['relations']],
                             [(a['id'],b['id']) for b,a in zip(units,units[1:])])
            self.assertEqual([r['edge_emitted'] for r in result['actions'][-1]['pairs']].count(True),1)
            view=load_extraction(run,root,action_target_version=targets.PAGED_VERSION)
            self.assertTrue(view['document']['work_paths']['dispatch_coverage']['each_action_once'])
            self.assertEqual(len(view['document']['work_paths']['paths']),1)
            engine.transport=lambda _:self.fail('Completed resume must reuse decisions')
            again,_=targets.execute(run,extraction,engine,version=targets.PAGED_VERSION)
            self.assertEqual(again,result)

    def test_sessions_parallel_siblings_and_unknown_order_do_not_join(self):
        with tempfile.TemporaryDirectory() as root:
            run,_,extraction=self.extracted(root,5)
            actions=[e for e in run['events'] if e['kind']=='action']
            actions[0]['context_id']='other-session'
            actions[1]['order_known']=False
            actions[2]['parent_id']='batch'
            actions[3].update(parent_id='batch',source_message_index=42)
            actions[4]['source_message_index']=42
            pool,excluded=pages.candidate_scope(run,extraction,extraction['units'][-1])
            self.assertEqual(pool,[])
            reasons=[p['reason'] for p in excluded]
            self.assertEqual(reasons.count('different_recorded_context'),1)
            self.assertEqual(reasons.count('source_order_unestablished'),1)
            self.assertEqual(reasons.count('same_recorded_dispatch_batch'),2)

    def test_byte_paging_preserves_exact_evidence_and_reports_oversized_pair(self):
        with tempfile.TemporaryDirectory() as root:
            run,_,extraction=self.extracted(root,5);action=extraction['units'][-1]
            pool,_=pages.candidate_scope(run,extraction,action)
            from tracker.schema import dumps
            # Force splitting by bytes without changing the evidence itself.
            with patch.object(pages,'MAX_BYTES',20_000):
                single=pages.request(run,action,pool[:1])
            cap=len(dumps(single).encode('utf-8'))+100
            with patch.object(pages,'MAX_BYTES',cap):
                chunks=list(pages.pages(run,action,pool))
                self.assertGreater(len(chunks),1)
                self.assertEqual([p['unit_id'] for chunk,_ in chunks for p in chunk],[p['unit_id'] for p in pool])
                for chunk,req in chunks:
                    self.assertIsNotNone(req)
                    packet=str(req['state']['prefix'])
                    for prior in [*chunk,targets.local(action)]:self.assertIn(prior['source']['text'],packet)
            with patch.object(pages,'MAX_BYTES',1):
                result=pages.build(run,extraction,lambda _:self.fail('Must not send incomplete evidence'))
            self.assertEqual(result['status'],'needs_evidence')
            self.assertEqual(result['coverage']['oversized_pairs'],10)
            self.assertEqual(result['coverage']['pending_pairs'],10)
            self.assertEqual(result['relations'],[])

    def test_overlap_and_unresolved_choices_on_different_pages_remain_distinct(self):
        with tempfile.TemporaryDirectory() as root:
            run,_,extraction=self.extracted(root,19)
            def decide(req):
                return {k:{'value':'partial_work_overlap' if k in {'a0','a16'} else 'unresolved'}
                        for k in req['questions']},digest(req)
            result=pages.build(run,extraction,decide)
            last=result['actions'][-1]
            self.assertEqual(last['status'],'unresolved')
            self.assertIsNone(last['identity_prior_unit_id'])
            self.assertEqual(len(last['pages']),2)
            edges=[r for r in result['relations'] if r['from']==last['action_unit_id']]
            self.assertEqual(len(edges),2)
            self.assertEqual({r['type'] for r in edges},{'overlapping_work_scope'})

    def test_multiple_matching_parallel_predecessors_do_not_get_arbitrary_anchor(self):
        with tempfile.TemporaryDirectory() as root:
            run,_,extraction=self.extracted(root,3)
            actions=[e for e in run['events'] if e['kind']=='action']
            actions[0]['parent_id']=actions[1]['parent_id']='parallel'
            result=pages.build(run,extraction,lambda req:({k:{'value':'same_work_target'} for k in req['questions']},digest(req)))
            last=result['actions'][-1]
            self.assertEqual(last['identity_selection'],'unordered_matching_predecessors')
            self.assertEqual(last['status'],'unresolved')
            self.assertIsNone(last['identity_prior_unit_id'])
            self.assertEqual(len(last['pairs']),2)
            self.assertEqual(result['relations'],[])

    def test_retained_public_retrieval_decisions_replay_into_three_separate_paths(self):
        fixture=read(Path(__file__).parent/'fixtures/paged_work_public.json')
        with tempfile.TemporaryDirectory() as root:
            for key,saved in fixture['decisions'].items():write(Path(root)/'decisions'/f'{key}.json',saved)
            run=fixture['run'];extraction=fixture['extraction']
            write(Path(root)/'results'/f"{run['id']}.json",extraction)
            engine=Pipeline(root,Provider(Path(root)/'candidates'),lambda _:self.fail('Public decisions must replay offline'))
            result,_=targets.execute(run,extraction,engine,version=targets.PAGED_VERSION)
            self.assertEqual(result,fixture['result'])
            self.assertEqual([{k:e[k] for k in ('from','to','type')} for e in result['relations']],fixture['expected']['relations'])
            view=load_extraction(run,root,action_target_version=targets.PAGED_VERSION)
            self.assertEqual(len(view['document']['work_paths']['paths']),3)
            self.assertEqual(result['coverage']['same_batch_excluded_pairs'],1)


if __name__=='__main__':unittest.main()
