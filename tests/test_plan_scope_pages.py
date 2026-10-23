"""Plan correspondence paging and graph contracts; authored decisions, not accuracy."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import plan_scope_pages as pages, plan_relations as plans
from tracker.schema import InputError, digest
from tracker.semantic_budget import BudgetReached
from tracker.semantic_extraction import Pipeline, load_extraction, read, write
from tests.test_plan_relations import fixture, Provider, transport as local_transport


def transport(req):
    if req['state']['stage']!='plan_stage_roles':return local_transport(req)
    subject=req['state']['subject']['text']
    def role(stage):
        if stage['step']['id']=='draft':
            return 'prepares' if subject.startswith('Create') else 'attempts' if subject.startswith('Write') else 'no_supported_role'
        return 'attempts' if subject.startswith('Convert') else 'checks' if subject.startswith('List') else 'no_supported_role'
    selected={p['id']:role(p) for p in req['state']['plan_stage_candidates']}
    if req['state']['relation_harness']==plans.DIRECT_VERSION:
        from tracker.plan_scope_roles import NAMES
        selected={k:NAMES.get(v,'another_step_or_unrelated') for k,v in selected.items()}
    return {'model':req['model'],'answers':{key:{'type':'choice','choice':'unresolved','confidence':0,
        'probabilities':{c:float(c==selected[key]) for c in q['criteria']}}
        for key,q in req['questions'].items()}}


class PagedPlanTests(unittest.TestCase):
    def extracted(self,root):
        run=fixture();engine=Pipeline(root,Provider(Path(root)/'candidates'),transport)
        return run,engine,engine.run(run)

    def test_roles_raw_argmax_cutoff_and_stable_local_map(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,x=self.extracted(root)
            before=load_extraction(run,root)
            result,audit=plans.execute(run,x,engine,version=plans.PAGED_VERSION)
            self.assertTrue(audit['argmax_replayed'])
            self.assertEqual(result['coverage']['compared_pairs'],8)
            self.assertEqual([e['type'] for e in result['relations']],
                ['prepares_plan_step','attempts_plan_step','attempts_plan_step','checks_plan_step'])
            self.assertEqual(load_extraction(run,root),before)
            mapped=load_extraction(run,root,plan_relation_version=plans.PAGED_VERSION)
            self.assertEqual(len([r for r in mapped['document']['relations'] if r.get('plan_step_id')]),4)
            for row in result['actions']:
                for page in row['pages']:
                    req=read(Path(root)/'decisions'/f"{page['request']}.json")['request']
                    cutoff=next(e['index'] for e in run['events'] if e['id']==req['state']['subject']['event_id'])
                    indices={e['id']:e['index'] for e in run['events']}
                    self.assertTrue(all(indices[e['id']]<=cutoff for e in req['state']['prefix']))
                    self.assertNotIn('FUTURE FEEDBACK',str(req))
            invalid=deepcopy(result);invalid['relations'][0]['type']='attempts_plan_step'
            with self.assertRaisesRegex(InputError,'differ'):plans.audit(run,x,invalid,root)

    def test_more_than_24_stages_resume_mid_action_and_replay_without_calls(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,x=self.extracted(root)
            plan=next(u for u in x['units'] if u['activity']=='plan')
            base=plan['plan_structure']['steps'][0]
            plan['plan_structure']['steps']=[{**base,'id':f'step-{i}'} for i in range(40)]
            # Modified local fixture is deliberately not claimed as audited extraction.
            called=[];saved=Path(root)/'progress.json'
            def stop(req):
                if len(called)==1:raise BudgetReached({'limit':'jev_requests'})
                called.append(digest(req));return transport(req)
            engine.transport=stop
            with self.assertRaises(BudgetReached):
                pages.build(run,x,engine.decide,progress=lambda r:write(saved,r))
            partial=read(saved)
            self.assertEqual(partial['coverage']['compared_pairs'],16)
            self.assertEqual(partial['coverage']['pending_pairs'],144)
            self.assertEqual(partial['status'],'running')
            def resume(req):
                self.assertNotIn(digest(req),called)
                called.append(digest(req));return transport(req)
            engine.transport=resume
            result=pages.build(run,x,engine.decide)
            self.assertEqual(result['coverage']['compared_pairs'],160)
            self.assertEqual(result['coverage']['pending_pairs'],0)
            self.assertEqual(len(called),12)
            engine.transport=lambda _:self.fail('Resume must reuse exact choices')
            self.assertEqual(pages.build(run,x,engine.decide),result)

    def test_multiple_stages_and_role_combinations_survive_without_completion(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,x=self.extracted(root)
            def decide(req):
                return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':
                    {c:float(c==('attempts+checks' if k=='s0' else 'prepares')) for c in q['criteria']}}
                    for k,q in req['questions'].items()}}
            engine.transport=decide
            result,_=plans.execute(run,x,engine,version=plans.PAGED_VERSION)
            row=result['actions'][-1]
            self.assertEqual(len(row['pairs']),2)
            edges=[e for e in result['relations'] if e['from']==row['action_unit_id']]
            self.assertEqual({(e['plan_step_id'],e['type']) for e in edges},
                {('draft','attempts_plan_step'),('draft','checks_plan_step'),('convert','prepares_plan_step')})
            self.assertNotIn('completed',str(result['relations']))
            from tracker.plan_execution import build as project
            projected=project(run,load_extraction(run,root,plan_relation_version=plans.PAGED_VERSION)['document'])['plans'][0]
            self.assertEqual(projected['counts']['bound_actions'],4)
            self.assertEqual(projected['counts']['multiple_stage_actions'],4)
            self.assertEqual(projected['stages'][0]['role_counts'],dict(prepares=0,attempts=4,checks=4))
            self.assertTrue(all(s['completion']=='not_established' for s in projected['stages']))

    def test_context_unknown_order_and_oversized_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            run,_,x=self.extracted(root)
            action=x['units'][-1];current=next(e for e in run['events'] if e['id']==action['source']['event_id'])
            current['context_id']='separate-session'
            pool,excluded=pages.candidates(run,x,action)
            self.assertEqual(pool,[])
            self.assertEqual({r['reason'] for r in excluded},{'different_recorded_context'})
            del current['context_id'];current['order_known']=False
            self.assertEqual({r['reason'] for r in pages.candidates(run,x,action)[1]},{'source_order_unestablished'})
            del current['order_known']
            with patch.object(pages,'MAX_BYTES',1):
                result=pages.build(run,x,lambda _:self.fail('Evidence must not be trimmed to fit'))
            self.assertEqual(result['coverage']['pending_pairs'],8)
            self.assertEqual(result['coverage']['oversized_pairs'],8)
            self.assertEqual(result['relations'],[])
            self.assertEqual(result['status'],'needs_evidence')

    def test_public_decisions_replay_and_known_false_link_remains_visible(self):
        retained=read(Path(__file__).parent/'fixtures/plan_stage_public.json')
        run,x=retained['run'],retained['extraction']
        with tempfile.TemporaryDirectory() as root:
            for key,saved in retained['decisions'].items():write(Path(root)/'decisions'/f'{key}.json',saved)
            engine=Pipeline(root,Provider(Path(root)/'candidates'),lambda _:self.fail('Must reuse public decisions offline'))
            actual=[]
            for action in x['units']:
                expected=[r for r in retained['report']['pairs'] if r['action']==action['id']]
                if not expected:continue
                pool,_=pages.candidates(run,x,action)
                answers,key=engine.decide(pages.request(run,x,action,pool))
                for row in expected:
                    self.assertEqual(answers[row['question']]['value'],row['choice'])
                    self.assertEqual(key,row['request'])
                    actual.append(row)
            errors=[r for r in actual if not r['matches']]
            # This is a retained model error, not a reference silently relabeled
            # to agree with the model. Software replay passing is not accuracy.
            self.assertEqual([(r['event'],r['step'],r['roles'],r['expected']) for r in errors],
                             [('e66','convert',['prepares'],[])])
            self.assertEqual(len(actual),12)


if __name__=='__main__':unittest.main()
