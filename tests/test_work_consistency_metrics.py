"""Evidence-qualification controls, not a test of model annotation accuracy."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import analysis_metrics as am, behavior_distributions as bd, graph_store as gs
from tracker import investigation_plans, monitoring, monitor_evidence
from tracker import work_consistency as wc, work_return_references as refs
from tracker import work_scope_audit as audit, work_subjects as ws, work_visits as visits
from tracker.schema import digest, InputError
from tracker.store import Store
from tests.test_work_subjects import fixture, annotation
from tests.test_work_route_context import edge, rehash


def example(names=('A','B','A'), pair=(2,0,'overlapping_work_scope'), links=()):
    run, base, units = fixture(tuple('Authored contribution '+str(i) for i in range(len(names))))
    if pair:
        a,b,kind=pair
        edge(base,units[a]['id'],units[b]['id'],kind,
            pair_choice=audit.TYPES[kind][0],pair_request='authored-request',
            cutoff={k:units[a]['source'][k] for k in ('event_id','end')},
            evidence=[deepcopy(units[b]['source']),deepcopy(units[a]['source'])])
    for a,b,kind in links:
        edge(base,units[a]['id'],units[b]['id'],kind,cutoff=deepcopy(units[a]['source']),basis='Authored control')
    base=rehash(base)
    return run,base,ws.fork(base,annotation(base,units,names)),units


class WorkConsistencyTests(unittest.TestCase):
    def test_disputed_returns_are_unknown_not_negative_and_counts_are_withheld(self):
        _,_,g,_=example();before=deepcopy(g)
        raw=visits.project(g);qualified=visits.project(g,scope_consistency=wc.POLICY)
        self.assertEqual(raw['metrics']['value'],.5)
        self.assertEqual(qualified['metrics'],dict(value=None,numerator=0,denominator=0,opportunities=2,unknown=2))
        self.assertEqual(qualified['coverage']['disputed_work_visits'],2)
        self.assertEqual(qualified['counts'],dict(disputed=2,first_seen=1))
        self.assertEqual(am.measure(qualified,am.catalog()['work_return_visits'])['value'],None)
        self.assertEqual(g,before);self.assertEqual(visits.project(g),raw)
        self.assertNotEqual(raw['id'],qualified['id'])
        self.assertEqual(qualified,visits.project(g,scope_consistency=wc.POLICY))

    def test_unaffected_return_survives_but_absence_claims_need_full_history(self):
        _,_,g,_=example(('A','A','B','C','B'),(1,0,'overlapping_work_scope'))
        out=visits.project(g,scope_consistency=wc.POLICY)
        self.assertEqual(out['metrics'],dict(value=1.,numerator=1,denominator=1,opportunities=3,unknown=2))
        self.assertNotIn('work_conflicts',out['switches'][-1])
        self.assertEqual(out['records'][-1]['category'],'returned')

    def test_split_same_work_is_also_disputed(self):
        _,_,g,_=example(('A','B'),(1,0,'same_action_target'))
        out=visits.project(g,scope_consistency=wc.POLICY)
        self.assertEqual(out['counts'],dict(disputed=2));self.assertIsNone(out['metrics']['value'])

    def test_missing_pair_coverage_and_consistency_are_not_accuracy_claims(self):
        for pair,state in [(None,'no_comparable_pair_evidence'),((2,0,'same_action_target'),'no_conflicts_in_checked_pairs')]:
            _,_,g,_=example(pair=pair);out=visits.project(g,scope_consistency=wc.POLICY)
            self.assertEqual(out['work_consistency']['state'],state)
            self.assertEqual(out['metrics'],visits.project(g)['metrics'])
            self.assertIn('does not establish independent accuracy',out['limits'])

    def test_incomparable_scope_and_tampered_pair_are_not_used(self):
        _,_,g,_=example();doc=g['semantic_context']['work_subjects']['document']
        doc['profile']={**doc['profile'],'id':'whole-task','version':'1'}
        self.assertEqual(visits.project(g,scope_consistency=wc.POLICY)['work_consistency']['state'],'scope_not_comparable')
        _,_,g,_=example()
        next(e for e in g['edges'] if e['type']=='overlapping_work_scope')['properties']['evidence'][0]['text']='changed'
        out=visits.project(g,scope_consistency=wc.POLICY)
        self.assertEqual(out['coverage']['work_scope_conflicts'],0)

    def test_late_conflict_is_separate_from_switch_entry_evidence(self):
        _,_,g,units=example(('A','B','C','A'),(3,0,'overlapping_work_scope'))
        out=visits.project(g,scope_consistency=wc.POLICY);case=out['switches'][0]
        entry=visits.entry_evidence(g,out,case)
        self.assertNotIn(units[-1]['id'],entry['node_ids'])
        self.assertEqual(case['work_conflicts'][0]['source_unit_id'],units[-1]['id'])
        self.assertEqual(entry['cutoff']['event_id'],units[1]['source']['event_id'])

    def test_disputed_reference_target_outside_return_window_is_retained(self):
        _,_,g,_=example(('B','B','A','C','A'),(1,0,'overlapping_work_scope'),((4,0,'uses_evidence'),))
        q={**refs.DEFAULT_QUERY,'referent_scope':'all_prior_work','relation_types':['uses_evidence']}
        out=refs.evaluate(g,q,scope_consistency=wc.POLICY)
        self.assertIsNone(out['value']);self.assertEqual(len(out['records']),1)
        self.assertEqual(out['records'][0]['status'],'disputed_work_identity')
        self.assertTrue(out['records'][0]['references'])
        self.assertEqual(out['coverage']['disputed_return_references'],1)
        self.assertEqual(out['coverage']['returns_without_established_reference'],0)
        self.assertEqual(refs.evaluate(g,q)['value'],1)

    def test_versions_choose_exact_legacy_or_new_definition(self):
        for key in ('work_return_visits','work_switch_return_fraction_parallel','work_return_references_parallel'):
            legacy=am.catalog(legacy=True)[key]
            raw={'measure':key,'version':legacy['version']}
            if legacy.get('requires_query'):raw['query']=refs.DEFAULT_QUERY
            self.assertNotIn('scope_consistency',am.definition(am.validate(raw)))
            raw.pop('version')
            self.assertEqual(am.definition(am.validate(raw))['scope_consistency'],wc.POLICY)
            raw['version']='unavailable'
            with self.assertRaises(InputError):am.validate(raw)
        _,_,g,_=example()
        with self.assertRaises(InputError):visits.project(g,scope_consistency='typo')
        with self.assertRaises(InputError):am.measure(visits.project(g),am.catalog()['work_return_visits'])

    def test_saved_monitors_receipts_distribution_and_cache_reconcile(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'test.sqlite');run,base,g,_=example()
            store.add([run])
            with store.connect() as c:gs.save(c,base);gs.save(c,g)
            monitors=[]
            for key,legacy in [('work_switch_return_fraction',True),('work_switch_return_fraction',False),('work_return_visits',False)]:
                selector={'measure':key}
                if legacy:selector['version']=am.catalog(legacy=True)[key]['version']
                monitors.append(monitoring.create(store,dict(name=key+str(legacy),kind='analysis',observer=g['observer'],analysis=selector)))
            result=monitoring.sync(store);self.assertEqual(result['errors'],0)
            values=[monitoring.values(store,m['id'],{run['id']})[run['id']] for m in monitors]
            self.assertEqual([v['value'] for v in values],[.5,None,None])
            for i,value in enumerate(values):
                receipt=monitor_evidence.read(store,value['id'])
                self.assertEqual(receipt['explanation']['value'],value['value'])
                if i:self.assertTrue(any(c.get('work_conflicts') for c in receipt['explanation']['analysis_cases']))
            old=deepcopy(values[0]);monitoring.sync(store)
            self.assertEqual(monitoring.values(store,monitors[0]['id'],{run['id']})[run['id']],old)
            self.assertEqual(monitoring.chart(monitors[1],monitoring.population(store),{run['id']:values[1]})['coverage']['disputed_work_rollouts'],1)
            distribution=bd.snapshot(store,lens='work_visits',observer=g['observer'])
            self.assertEqual(distribution['scope_consistency'],wc.POLICY)
            self.assertEqual(distribution['distribution']['counts']['disputed'],2)
            self.assertTrue(all('graph='+g['id'] in c['map_url'] for c in distribution['cases']))
            plans=[investigation_plans.read_plan(store,v['analysis']['plan_id']) for v in values]
            self.assertNotEqual(plans[0]['id'],plans[1]['id'])

    def test_retained_public_retrieval_graph_qualifies_without_source_rewrite(self):
        path=Path(__file__).resolve().parents[1]/'research/contribution-work-mapped-2026-10-12/retrieval/graph.json'
        before=path.read_bytes();g=json.loads(before)
        out=visits.project(g,scope_consistency=wc.POLICY)
        self.assertEqual(out['coverage']['work_scope_conflicts'],2)
        self.assertGreater(out['coverage']['disputed_work_visits'],0)
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
