"""Versioned access measures and their saved monitoring evidence path."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tracker import diagnostic_search as search, diagnostic_direct as direct
from tracker import monitoring, monitor_evidence, reward_detectors
from tracker.diagnostic_access import restriction_evidence
from tracker.adapters import normalize
from tracker.store import Store
from tracker.schema import dumps, digest, InputError
from test_tracker import harbor
from test_diagnostic_monitors import source


def selection(req):
    candidates=req['state']['candidate_fragment_ids']
    action=next((k for k in candidates if req['state']['source_fragments'][k].get('kind')=='action'),None)
    chosen={name:(action if name=='evaluation_material_access' and action else
                  'unresolved' if name=='restricted_evaluation_access' and action else 'none') for name in req['questions']}
    return {'model':req['model'],'answers':{name:{'type':'choice','probabilities':{key:float(key==chosen[name]) for key in q['criteria']}}
        for name,q in req['questions'].items()}}


class AccessTests(unittest.TestCase):
    def test_new_definitions_and_options_do_not_change_historical_contracts(self):
        s=source(trace=dumps([{'actor':'user','kind':'instruction','text':'Follow the task.'},
                             {'actor':'agent','kind':'action','text':'read grading code'}]))
        old=next(direct.requests(s,search.LINKED_VERSION));new=next(direct.requests(s,search.ACCESS_VERSION))
        self.assertIn('development_tests',old['questions']['evaluation_material_access']['criteria'])
        self.assertNotIn('development_tests',new['questions']['evaluation_material_access']['criteria'])
        self.assertIn('explicit_permission',new['questions']['restricted_evaluation_access']['criteria'])
        self.assertNotIn('restricted_evaluation_access',old['questions'])
        self.assertEqual(old['state']['source_fragments'],new['state']['source_fragments'])

    def test_unknown_policy_is_not_zero_and_never_suppresses_observed_access(self):
        s=source(trace=dumps([{'actor':'agent','kind':'action','text':'read grading code'}]))
        calls=[]
        def decide(req):
            calls.append(req);wire=selection(req)
            return {k:{'value':max(v['probabilities'],key=v['probabilities'].get)} for k,v in wire['answers'].items()},digest(req)
        result=search.build(s,decide,version=search.ACCESS_VERSION)
        self.assertEqual(len(calls),1)
        self.assertNotIn('restricted_evaluation_access',calls[0]['questions'])
        self.assertEqual(result['metrics']['evaluation_material_access']['value'],1)
        self.assertIsNone(result['metrics']['restricted_evaluation_access']['value'])
        self.assertEqual(search.summarize([result])['supported_cases']['restricted_evaluation_access'],0)

    def test_new_and_old_captures_render_readable_exact_evidence(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');run=normalize(harbor(),'harbor')[0];store.add([run])
            for version in (search.TASK_CONTEXT_VERSION,search.LINKED_VERSION,search.ACCESS_VERSION):
                source=search.source_from_run(run,version);folder=root/version.split('/')[-1]
                result=search.execute(source,folder,selection,version=version)
                saved=search.register(store,run,source,result,folder)
                activated=reward_detectors.activate(store,{'checks':['evaluation_material_access'],'observer':saved['observer']})
                monitor_id=activated['added'][0];monitoring.sync(store)
                value=monitoring.cases(store,monitor_id)['rows'][0]['measurement']
                proof=monitor_evidence.read(store,value['id'])
                self.assertTrue(proof['explanation']['diagnostic_excerpts'],version)
                self.assertEqual(proof['explanation']['definition'],result['protocol']['detectors']['evaluation_material_access'][1])
                self.assertEqual(proof['monitor']['name'],result['protocol']['detectors']['evaluation_material_access'][0])
                chart=next(r for r in monitoring.snapshot(store)['monitors'] if r['id']==monitor_id)
                self.assertEqual(chart['description'],proof['explanation']['definition'])
            catalog=reward_detectors.catalog(store)
            old=next(o for o in catalog['observers'] if o['protocol_version']==search.LINKED_VERSION)
            with self.assertRaises(InputError):reward_detectors.activate(store,{'checks':['restricted_evaluation_access'],'observer':old['id']})
            added=reward_detectors.activate(store,{'checks':['restricted_evaluation_access'],'observer':saved['observer']})
            monitoring.sync(store)
            value=monitoring.cases(store,added['added'][0])['rows'][0]['measurement']
            self.assertIsNone(value['value'])

    def test_only_prior_same_scope_native_instructions_become_rule_options(self):
        s=source(trace=dumps([
            {'id':'q','actor':'environment','kind':'feedback','trajectory_id':'A','text':'Do not read tests.'},
            {'id':'u','actor':'user','kind':'instruction','trajectory_id':'B','text':'Do not read tests.'},
            {'id':'a','actor':'agent','kind':'action','trajectory_id':'A','text':'Read tests'},
            {'id':'late','actor':'user','kind':'instruction','trajectory_id':'A','text':'Do not read tests.'}]))
        fragments=[f for f in search.index(s,search.ACCESS_VERSION) if f.get('event_id')=='a']
        self.assertFalse(restriction_evidence(s,fragments)['restriction_pairs'])

    def test_published_conflict_cites_both_action_and_applicable_instruction(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');run=normalize(harbor(),'harbor')[0];store.add([run])
            source=search.source_from_run(run,search.ACCESS_VERSION)
            def positive(req):
                result=selection(req)
                if req['state'].get('restriction_pairs'):
                    chosen=next(iter(req['state']['restriction_pairs']))
                    result['answers']['restricted_evaluation_access']['probabilities']={k:float(k==chosen) for k in req['questions']['restricted_evaluation_access']['criteria']}
                return result
            result=search.execute(source,root/'run',positive,version=search.ACCESS_VERSION)
            observer=search.register(store,run,source,result,root/'run')['observer']
            monitor=reward_detectors.activate(store,{'checks':['restricted_evaluation_access'],'observer':observer})['added'][0]
            monitoring.sync(store);value=monitoring.cases(store,monitor)['rows'][0]['measurement']
            proof=monitor_evidence.read(store,value['id'])
            refs=proof['explanation']['diagnostic']['evidence_roles']
            self.assertEqual(set(refs),{'action','instruction'})
            for ref in refs.values():self.assertTrue(proof['explanation']['diagnostic_excerpts'][ref['id']])


if __name__=='__main__':unittest.main()
