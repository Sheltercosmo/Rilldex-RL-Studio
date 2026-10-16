"""Grouping mechanics plus retained partial real evidence; no accuracy claim."""
from copy import deepcopy
import unittest
import tempfile
from pathlib import Path
import json

from tracker import scope_membership as membership, work_subjects as ws, contribution_scope_pairs as pairs
from tracker import contribution_scope_graph as scope, graph_store, unit_reviews, work_navigation
from tracker.schema import InputError, digest
from tracker.store import Store
from test_contribution_work import source
from test_contribution_scope_graph import fixture as real_fixture
from test_unit_reviews import document as review_document


def fixture(choices=None, count=3):
    run, base, units = source(tuple('Work question '+str(i)+'.' for i in range(count)))
    choices = choices if choices is not None else {(1,0):'different_work_same_subject',
        (2,0):'same_work_target', (2,1):'different_work_same_subject'}
    receipts = []
    for i, current in enumerate(units):
        prior_ids = [j for j in range(i) if (i,j) in choices]
        if not prior_ids: continue
        priors = [units[j] for j in prior_ids]
        req = pairs.request(run, current, priors, version=pairs.TARGET_VERSION)
        response = dict(model=req['model'], answers={})
        for n, j in enumerate(prior_ids):
            qid='p'+str(n); selected=choices[(i,j)]
            response['answers'][qid]=dict(type='choice', choice='unresolved', confidence=0,
                probabilities={k: .75 if k==selected else .05 for k in req['questions'][qid]['criteria']})
        receipts.append(dict(current=current, priors=priors, request=req, response=response))
    return run, scope.fork(run, base, receipts), units


class ScopeMembershipTests(unittest.TestCase):
    def test_complete_pair_evidence_supports_existing_macro_return(self):
        run, graph, units = fixture(); original=deepcopy(graph)
        doc=membership.document(run,graph); derived=ws.fork(graph,doc)
        self.assertEqual(graph,original); graph_store.validate(derived)
        result=doc['derivation']['result']
        self.assertEqual(result['counts']['bound'],3)
        self.assertEqual(result['counts']['missing_pairs'],0)
        self.assertEqual(len(doc['subjects']),2)
        self.assertEqual(doc['bindings'][0]['subject_id'],doc['bindings'][2]['subject_id'])
        self.assertEqual(work_navigation.project(derived)['counts']['returned'],1)
        self.assertEqual([n for n in graph['nodes'] if n['kind']=='unit'],[n for n in derived['nodes'] if n['kind']=='unit'])

    def test_missing_comparison_is_not_a_negative_or_a_transitive_link(self):
        run,graph,_=fixture({(1,0):'same_work_target',(2,1):'same_work_target'})
        result=membership.derive(run,graph)
        self.assertEqual([r['status'] for r in result['bindings']],['bound','bound','unresolved'])
        self.assertEqual(result['records'][2]['missing_prior_unit_ids'],['unit-0'])
        self.assertEqual(ws.project(ws.fork(graph,membership.document(run,graph)))['counts']['returned'],0)

    def test_partial_overlap_and_different_instances_keep_scopes_separate(self):
        run,graph,_=fixture({(1,0):'partial_work_overlap',(2,0):'different_instance',(2,1):'unrelated'})
        result=membership.derive(run,graph)
        self.assertEqual(result['counts']['bound'],3)
        self.assertEqual(result['counts']['groups'],3)

    def test_nontransitive_identity_cannot_force_a_merge(self):
        for choices,reason in [
            ({(1,0):'same_work_target',(2,0):'same_work_target',(2,1):'partial_work_overlap'},'identity_conflicts_with_group_member'),
            ({(1,0):'different_instance',(2,0):'same_work_target',(2,1):'same_work_target'},'identity_bridges_distinct_groups')]:
            run,graph,_=fixture(choices); result=membership.derive(run,graph)
            self.assertEqual(result['records'][2]['reason'],reason)
            self.assertEqual(result['bindings'][2]['status'],'unresolved')
            self.assertEqual(result['counts']['conflicting_units'],1)

    def test_unknown_pair_stays_unknown_and_is_not_reproposed(self):
        run,graph,_=fixture({(1,0):'unresolved',(2,0):'different_instance',(2,1):'different_instance'})
        result=membership.derive(run,graph)
        self.assertEqual(result['records'][1]['reason'],'unresolved_pair_evidence')
        self.assertEqual(result['records'][2]['status'],'bound')
        self.assertEqual(membership.pending_requests(run,graph)['requests'],[])

    def test_future_evidence_does_not_repair_earlier_membership(self):
        run,graph,_=fixture({(2,0):'same_work_target',(2,1):'same_work_target'})
        result=membership.derive(run,graph)
        self.assertEqual(result['records'][1]['reason'],'missing_pair_evidence')
        self.assertEqual(result['records'][2]['reason'],'earlier_membership_unresolved')

    def test_changed_source_receipt_units_and_derived_bindings_are_rejected(self):
        run,graph,_=fixture(); doc=membership.document(run,graph)
        for mode in ('binding','target','source','probability','units','ledger'):
            g=deepcopy(graph); d=deepcopy(doc)
            if mode=='binding':d['bindings'][2]['subject_id']=d['subjects'][1]['id']
            if mode=='target':d['subjects'][0]['label']='Changed question'
            if mode=='source':d['derivation']['run']['metadata']['task_id']='Changed task'
            if mode=='probability':
                p=g['semantic_context']['contribution_scope']['receipts'][0]['response']['answers']['p0']['probabilities']
                p['same_work_target'],p['different_work_same_subject']=p['different_work_same_subject'],p['same_work_target']
            if mode=='units':next(n for n in g['nodes'] if n['kind']=='unit')['properties']['content']['work_target']['text']='Changed'
            if mode=='ledger':d['derivation']['result']['counts']['bound']=999
            # Content-address these deliberate changed inputs; semantic replay must still reject.
            g['id']='graph-'+digest({k:v for k,v in g.items() if k!='id'});d['base_graph_id']=g['id']
            with self.subTest(mode=mode),self.assertRaises(InputError):ws.fork(g,d)

    def test_named_review_overrides_binding_without_rewriting_receipts(self):
        run,graph,_=fixture(); original=ws.fork(graph,membership.document(run,graph))
        d=ws.template(original)['document']; receipt=deepcopy(d['derivation'])
        d['bindings'][2].update(status='unresolved',subject_id=None,note='Identity needs review.',
            provenance=dict(kind='review',author='Test reviewer',protocol='work-subject-review/1'))
        reviewed=ws.fork(original,d)
        self.assertEqual(reviewed['semantic_context']['work_subjects']['document']['derivation'],receipt)
        self.assertEqual(ws.project(reviewed)['counts']['returned'],0)

    def test_unit_repair_invalidates_automatic_grouping(self):
        run,graph,units=fixture(); derived=ws.fork(graph,membership.document(run,graph))
        repaired=unit_reviews.fork(run,derived,review_document(run,derived,units[0]['id'],text='Different immediate target.'))
        doc=repaired['semantic_context']['work_subjects']['document']
        self.assertNotIn('derivation',doc)
        self.assertEqual(doc['bindings'],[])
        self.assertIn('automatic_work_membership',repaired['semantic_context']['unit_reviews']['impact']['invalidated_layers'])

    def test_old_activity_conflating_protocol_cannot_supply_new_groups(self):
        run,graph,_=fixture(); graph['semantic_context']['contribution_scope']['protocol']=pairs.VERSION
        with self.assertRaises(InputError):membership.derive(run,graph)

    def test_real_partial_graph_exposes_exact_missing_coverage_and_reuses_every_pair(self):
        run,base,receipts=real_fixture(); graph=scope.fork(run,base,receipts)
        before=deepcopy(graph); result=membership.derive(run,graph)
        self.assertEqual(result['counts'],dict(bound=2,unresolved=3,units=5,groups=2,observed_pairs=4,
            eligible_pairs=9,missing_pairs=5,unresolved_pairs=0,conflicting_units=0))
        pending=membership.pending_requests(run,graph)
        self.assertEqual(len(pending['requests']),3)
        self.assertEqual(sum(len(r['priors']) for r in pending['requests']),5)
        known={(r['current_unit_id'],r['prior_unit_id']) for o in graph['semantic_context']['contribution_scope']['observations'] for r in o['pairs']}
        for r in pending['requests']:
            self.assertFalse(any((r['current']['id'],p['id']) in known for p in r['priors']))
        self.assertEqual(pending['provider_calls'],0);self.assertEqual(graph,before)
        derived=ws.fork(graph,membership.document(run,graph));graph_store.validate(derived)
        self.assertEqual(work_navigation.project(derived)['counts']['returned'],0)
        old=work_navigation.project(derived)
        route=work_navigation.project(derived,target_relations=pairs.TARGET_VERSION)
        self.assertEqual(route['counts'],old['counts'])
        self.assertNotEqual(route['id'],old['id'])
        related=[r for r in route['links'] if r.get('family')=='target']
        self.assertEqual(len(related),4)
        self.assertEqual(sum(r['relation_type']=='same_work_target' for r in related),1)
        self.assertTrue(all(r['edge_ids'] and r['node_ids'] for r in related))
        self.assertFalse(any(r.get('family')=='target' for r in old['links']))

    def test_published_derivation_is_idempotent_and_preserves_base_graph(self):
        run,graph,_=fixture()
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'tracker.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,graph)
            first=membership.receive(store,dict(base_graph_id=graph['id']))
            self.assertEqual(membership.receive(store,dict(base_graph_id=graph['id'])),first)
            self.assertEqual(first['new_model_calls'],0)
            self.assertEqual(graph_store.read(store,graph['id'])['id'],graph['id'])
            published=graph_store.read(store,first['graph_id']);ws.project(published)
            with self.assertRaises(InputError):membership.receive(store,dict(base_graph_id=first['graph_id']))

    def test_first_target_cannot_use_future_evidence(self):
        run,graph,units=fixture({(2,1):'different_instance'})
        first=next(n['properties'] for n in graph['nodes'] if n['id']==units[0]['id'])
        first['content']['work_target']['evidence']=[deepcopy(units[2]['source'])]
        with self.assertRaises(InputError):membership.derive(run,graph)

    def test_completed_real_pilot_replays_all_pairs_and_keeps_parallel_order_unknown(self):
        folder=Path(__file__).resolve().parents[1]/'research/pair-work-grouping-2026-10-12/completion-pilot'
        graph=json.loads((folder/'graph.json').read_text(encoding='utf-8'))
        graph_store.validate(graph)
        doc=graph['semantic_context']['work_subjects']['document']
        result=membership.validate(graph,doc)
        self.assertEqual(result['counts']['bound'],5)
        self.assertEqual(result['counts']['groups'],4)
        self.assertEqual(result['counts']['observed_pairs'],9)
        self.assertEqual(membership.pending_requests(doc['derivation']['run'],graph)['requests'],[])
        route=work_navigation.project(graph,target_relations=pairs.TARGET_VERSION)
        self.assertEqual(route['counts']['returned'],0)
        self.assertEqual(route['counts']['interrupted'],1)
        self.assertEqual(route['context']['relations'],9)
        self.assertEqual(sum(not v['order_known'] for v in route['visits']),2)


if __name__=='__main__':unittest.main()
