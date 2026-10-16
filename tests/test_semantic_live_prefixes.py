"""Streaming lifecycle controls, not a measurement of model annotation accuracy."""
import copy
import json
import unittest

from tracker import active_captures, monitoring, semantic_catalog, semantic_watch as watch
from tracker.schema import digest
from tracker.semantic_extraction import read
from tests import test_semantic_watch as controls
from tests.test_semantic_extraction import response


class SemanticLivePrefixTests(unittest.TestCase):
    setUp=controls.SemanticWatchTests.setUp
    init=controls.SemanticWatchTests.init
    run_worker=controls.SemanticWatchTests.run_worker

    def ingest(self, size, *, revision=None, state='in_progress', producer='agent', name='growing', edit=None):
        doc=controls.document(name)
        doc['steps']=[{'step_id':i+1,'source':'agent',
                       'message':f'The reproduction for component {i} lacks the decorator. We need to add it to replicate the issue.'}
                      for i in range(size)]
        if edit:doc['steps'][edit[0]]['message']=edit[1]
        latest=self.store.latest_revision(producer,name)
        if revision is None:revision=latest['revision']+1 if latest else 0
        return self.store.ingest({'producer':producer,'rollout_id':name,'revision':revision,
            'state':state,'document':doc,'metadata':{'experiment':'trial'}})['id']

    def test_default_does_not_observe_in_progress(self):
        self.init();self.ingest(1)
        result=self.run_worker(lambda _:self.fail('Default must wait for completion'))
        self.assertEqual(result['waiting_for_completion'],1)
        self.assertEqual(result['used'],watch.ZERO)

    def test_append_reuses_exact_requests_and_keeps_partial_out_of_completed_metrics(self):
        observer=self.init(live_prefixes=True)['observer']
        monitor=monitoring.create(self.store,{'name':'Planning share','kind':'metric','observer':observer,'metric':'agent_plan_unit_share'})
        first=self.ingest(1);one=self.run_worker()
        before=read(self.work/'runs'/first/'results'/f'{first}.json')
        self.assertEqual(one['used']['jev_requests'],3)
        self.assertFalse(one['jobs'][0]['details']['source_complete_at_publication'])
        second=self.ingest(2);two=self.run_worker()
        self.assertEqual(two['used']['jev_requests'],6)
        self.assertEqual(two['used']['candidate_requests'],6)
        receipt=read(self.work/'runs'/second/'last-execution.json')
        self.assertEqual(receipt['exact_reused_decisions'],3)
        self.assertEqual(before,read(self.work/'runs'/first/'results'/f'{first}.json'))
        self.assertEqual(watch.status(self.store,self.work)['current_published'],1)
        current=active_captures.snapshot(self.store)['rows'][0]['semantic_observations']
        self.assertEqual(current['total'],1)
        self.assertEqual(current['rows'][0]['unit_count'],2)
        self.assertEqual(current['rows'][0]['observer'],observer)
        with self.store.read_snapshot() as saved:
            live=monitoring._snapshot(saved)
        monitoring.sync(self.store)
        with self.store.connect() as c:
            rows=[json.loads(r[0]) for r in c.execute('SELECT document FROM monitor_values WHERE monitor_id=?',(monitor['id'],))]
        self.assertTrue(rows)
        self.assertTrue(all(r['status']=='incomplete' and r['value'] is None for r in rows))
        self.assertEqual(live['active_captures']['total'],1)
        self.assertEqual(self.ingest(2,state='complete'),second)
        done=self.run_worker(lambda _:self.fail('Identical completion needs no new provider call'))
        self.assertEqual(done['used'],two['used'])
        monitoring.sync(self.store)
        with self.store.read_snapshot() as saved:
            final=monitoring._snapshot(saved)
        self.assertEqual(final['population'],1)
        self.assertEqual(final['active_captures']['total'],0)
        self.assertEqual(final['monitors'][0]['coverage']['available'],1)
        self.assertTrue(semantic_catalog.load(self.store.get(second,raw=True)['run'],observer,self.store)['available'])

    def test_source_edit_invalidates_changed_requests_without_rewriting_prior_archive(self):
        self.init(live_prefixes=True)
        first=self.ingest(1);self.run_worker()
        old=read(self.work/'runs'/first/'results'/f'{first}.json')
        second=self.ingest(1,edit=(0,'The reproduction lacks a required input. We need to add it.'))
        result=self.run_worker()
        self.assertEqual(result['used']['jev_requests'],6)
        self.assertEqual(read(self.work/'runs'/second/'last-execution.json')['exact_reused_decisions'],0)
        self.assertEqual(read(self.work/'runs'/first/'results'/f'{first}.json'),old)

    def test_other_logical_rollout_and_producer_do_not_supply_prior_workspaces(self):
        observer=self.init(live_prefixes=True)['observer']
        first=self.ingest(1);self.run_worker()
        other=self.ingest(2,producer='different')
        self.assertEqual(watch._prior_workspaces(self.store,observer,other,self.work),[])
        sibling=self.ingest(2,name='another')
        self.assertEqual(watch._prior_workspaces(self.store,observer,sibling,self.work),[])
        later=self.ingest(3)
        self.assertEqual(watch._prior_workspaces(self.store,observer,later,self.work),[self.work/'runs'/first])

    def test_new_prefix_arriving_during_inference_does_not_publish_stale_graph(self):
        self.init(live_prefixes=True);first=self.ingest(1);new=[]
        def transport(req):
            if not new:new.append(self.ingest(2))
            return response(req)
        stale=self.run_worker(transport)
        self.assertEqual(stale['current_published'],0)
        self.assertEqual(stale['job_counts'],{'superseded':1})
        latest=self.run_worker()
        self.assertEqual(latest['used']['jev_requests'],6)
        self.assertEqual(latest['current_published'],1)

    def test_growth_cannot_implicitly_retry_failed_prefix(self):
        self.init(live_prefixes=True);first=self.ingest(1)
        failed=self.run_worker(lambda _:(_ for _ in ()).throw(RuntimeError('provider unavailable')))
        second=self.ingest(2)
        blocked=self.run_worker(lambda _:self.fail('A new prefix is not consent to retry'))
        self.assertEqual(blocked['used'],failed['used'])
        self.assertTrue(blocked['paused_for_review'])
        latest=next(j for j in blocked['jobs'] if j['run_id']==second)
        self.assertEqual(latest['status'],'failed')
        self.assertEqual(latest['details']['inherited_from_run'],first)
        done=self.run_worker(retry_runs=[second])
        self.assertEqual(done['current_published'],1)
        third=self.ingest(3)
        more=self.run_worker()
        self.assertEqual(more['current_published'],1)
        self.assertFalse(more['paused_for_review'])

    def test_growth_preserves_budget_block_until_explicit_retry(self):
        self.init(live_prefixes=True,allowance={**self.cap,'jev_requests':1});self.ingest(1)
        stopped=self.run_worker();second=self.ingest(2)
        watch.set_allowance(self.store,self.work,self.cap)
        blocked=self.run_worker(lambda _:self.fail('Raising a ceiling does not retry a blocked prefix'))
        self.assertEqual(blocked['used'],stopped['used'])
        self.assertTrue(blocked['paused_for_review'])
        done=self.run_worker(retry_runs=[second])
        self.assertEqual(done['used']['jev_requests'],6)

    def test_late_prefix_does_not_replace_current_evidence(self):
        self.init(live_prefixes=True);self.ingest(1);current=self.ingest(2);first=self.run_worker()
        self.ingest(1,revision=0)
        repeat=self.run_worker(lambda _:self.fail('Out-of-order receipt does not trigger older analysis'))
        self.assertEqual(repeat['used'],first['used'])
        self.assertEqual(repeat['current_published'],1)
        self.assertEqual(active_captures.snapshot(self.store)['rows'][0]['run_id'],current)

    def test_64_step_control_grows_without_quadratic_provider_recalculation(self):
        self.init(live_prefixes=True,allowance={'jev_requests':192,'candidate_requests':192,'input_bytes':20_000_000})
        for size in range(8,65,8):
            current=self.ingest(size)
            result=self.run_worker()
            self.assertEqual(result['current_published'],1,result['jobs'][-1])
            self.assertEqual(result['used']['jev_requests'],size*3)
            self.assertEqual(result['used']['candidate_requests'],size*3)
            graph=read(self.work/'runs'/current/'results'/f'{current}.json')
            self.assertEqual(len(graph['units']),size)
            self.assertEqual(graph['source_hash'],digest(self.store.get(current,raw=True)['run']))
        self.ingest(64,state='complete')
        done=self.run_worker(lambda _:self.fail('Finishing a source cannot repeat inference'))
        self.assertEqual(done['used'],result['used'])
        self.assertEqual(done['current_growing_prefixes'],0)


if __name__=='__main__':unittest.main()
