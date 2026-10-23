"""Frozen live development decisions and direct-role software contracts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import plan_relations as plans, plan_scope_pages as pages, plan_scope_roles as direct
from tracker.schema import InputError, digest
from tracker.semantic_extraction import Pipeline, read, write, load_extraction
from tests.test_plan_relations import fixture, Provider
from tests.test_plan_scope_pages import transport


class DirectPlanTests(unittest.TestCase):
    def test_live_public_and_control_decisions_replay_without_calls(self):
        base=Path(__file__).parent/'fixtures'
        saved=read(base/'plan_direct_roles.json');public=read(base/saved['public_fixture'])
        pairs=[]
        with tempfile.TemporaryDirectory() as root:
            for key,record in saved['decisions'].items():write(Path(root)/'decisions'/f'{key}.json',record)
            engine=Pipeline(root,None,lambda _:self.fail('Frozen semantic replay must be offline'))
            for case in saved['cases']:
                run,x=(public['run'],public['extraction']) if case['kind']=='public_development' else (case['run'],case['extraction'])
                action=next(u for u in x['units'] if u['kind']=='action' and
                            (u['source']['event_id']==case['event'] if 'event' in case else u['id']==case['action_id']))
                pool,_=pages.candidates(run,x,action);req=direct.request(run,x,action,pool)
                answers,key=engine.decide(req)
                for candidate in pool:
                    choice=answers[candidate['id']]['value']
                    expected=case['expected'][candidate['step']['id']]
                    self.assertNotEqual(choice,direct.UNRESOLVED,(case['name'],candidate['step']['id']))
                    self.assertEqual(list(direct.ROLE_SETS.get(choice,())),expected,(case['name'],candidate['step']['id']))
                    row=next(r for r in saved['report']['rows'] if r['case']==case['name'] and r['step']==candidate['step']['id'])
                    self.assertEqual((key,choice),(row['request'],row['choice']))
                    pairs.append(row)
            self.assertEqual(len(pairs),30)
            self.assertEqual(sum(p['kind']=='public_development' for p in pairs),18)
            self.assertEqual(engine.calls,0)
        # Earlier regressions remain retained rather than relabeled as success.
        self.assertTrue(any(not r['matches'] for r in saved['ablations']['renamed_public']['rows']))
        self.assertTrue(any(not r['matches'] for r in saved['ablations']['empty_container_wording']['rows']))

    def test_direct_graph_is_auditable_and_legacy_map_stays_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            run=fixture();engine=Pipeline(root,Provider(Path(root)/'candidates'),transport);x=engine.run(run)
            old,_=plans.execute(run,x,engine,version=plans.PAGED_VERSION)
            old_map=load_extraction(run,root,plan_relation_version=plans.PAGED_VERSION)
            result,audit=plans.execute(run,x,engine,version=plans.DIRECT_VERSION)
            self.assertTrue(audit['argmax_replayed'])
            self.assertEqual(result['coverage']['linked_pairs'],4)
            self.assertEqual(result['coverage']['indirect_pairs'],0)
            new_map=load_extraction(run,root,plan_relation_version=plans.DIRECT_VERSION)
            self.assertEqual(new_map['document']['provenance']['relation_harness'],direct.VERSION)
            self.assertEqual([r['type'] for r in result['relations']],[r['type'] for r in old['relations']])
            self.assertEqual(load_extraction(run,root,plan_relation_version=plans.PAGED_VERSION),old_map)
            engine.transport=lambda _:self.fail('Repeat must reuse decisions')
            self.assertEqual(plans.execute(run,x,engine,version=plans.DIRECT_VERSION)[0],result)
            invalid=deepcopy(result);invalid['relations'][0]['type']='attempts_plan_step'
            with self.assertRaisesRegex(InputError,'differ'):plans.audit(run,x,invalid,root)

    def test_indirect_links_and_missing_evidence_remain_distinct_from_direct_work(self):
        with tempfile.TemporaryDirectory() as root:
            run=fixture();engine=Pipeline(root,Provider(Path(root)/'candidates'),transport);x=engine.run(run)
            def decide(req):
                return {k:dict(value='upstream_work_only' if k=='s0' else direct.UNRESOLVED)
                        for k in req['questions']},digest(req)
            result=pages.build(run,x,decide,version=direct.VERSION)
            self.assertEqual(result['relations'],[])
            self.assertEqual(result['coverage']['indirect_pairs'],4)
            self.assertEqual(result['coverage']['unresolved_pairs'],4)
            self.assertEqual(result['coverage']['pending_pairs'],0)
            self.assertTrue(all(r['status']=='unresolved' for r in result['actions'] if r['candidate_count']))
            self.assertEqual(result['actions'][0]['status'],'no_prior_selected_plan')
            with self.assertRaisesRegex(InputError,'Unknown paged'):
                pages.build(run,x,decide,version='unknown')

    def test_compound_roles_keep_multiple_edges_and_raw_argmax(self):
        with tempfile.TemporaryDirectory() as root:
            run=fixture();engine=Pipeline(root,Provider(Path(root)/'candidates'),transport);x=engine.run(run)
            def choose(req):
                def answer(q,label):
                    return dict(type='choice',choice=direct.UNRESOLVED,confidence=0,
                        probabilities={c:0.3 if c==label else 0.7/(len(q['criteria'])-1) for c in q['criteria']})
                return dict(model=req['model'],answers={k:answer(q,'performs_or_updates_step+inspects_step_result' if k=='s0' else 'sets_up_execution') for k,q in req['questions'].items()})
            engine.transport=choose
            result,_=plans.execute(run,x,engine,version=direct.VERSION)
            for row in result['actions']:
                if not row['candidate_count']:continue
                self.assertEqual(row['pairs'][0]['roles'],['attempts','checks'])
                self.assertEqual(row['pairs'][1]['roles'],['prepares'])
            self.assertEqual(len(result['relations']),12)
            self.assertNotIn('completed',str(result['relations']))


if __name__=='__main__':unittest.main()
