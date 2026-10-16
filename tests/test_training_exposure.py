"""Exact provenance, not behavioral credit. Includes retained native capture replay."""
import copy
from collections import Counter
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import urlopen

from rilldex import Workspace
from tracker import training_exposure as exposure, training_lineage as lineage
from tracker import investigation_followups as follow, failure_investigations as investigations
from tracker.schema import InputError, digest, dumps
import test_training_lineage as v1
import test_training_samples as v2
import test_generation_cohort_transport as transport
import test_investigation_followups as workflows
import test_failure_investigations as failures


class ExposureTests(unittest.TestCase):
    setUp = transport.GenerationCohortTransportTests.setUp
    start_server = transport.GenerationCohortTransportTests.start_server
    stop_server = staticmethod(transport.GenerationCohortTransportTests.stop_server)
    source = v1.TrainingLineageTests.source
    packet = v1.TrainingLineageTests.packet
    add = v1.TrainingLineageTests.add
    run_fixture = failures.FailureInvestigationTests.run_fixture
    base = workflows.FollowupTests.base
    plan = workflows.FollowupTests.plan
    finding = workflows.FollowupTests.finding

    def read(self, run, **kwargs):
        return exposure.snapshot(self.store, run_id=run['id'], **kwargs)

    def add2(self, *records, experiment='exp', producer='learner-export'):
        return lineage.receive(self.store, dict(schema='training-records/2', producer=producer,
                                               experiment=experiment, records=list(records)))

    def declare2(self, name, source='a', **extra):
        return v2.record('sample', name, source=dict(producer='worker',rollout_id=source,revision=0), **extra)

    def test_exact_revision_latest_decision_and_stage_grains(self):
        old=self.source('a');new=self.source('a','new reply',revision=1)
        self.add(v1.record('sample'),v1.record('selection',revision=2,decision='admitted'),
                 v1.record('selection',revision=0),v1.record('use',loss_tokens=0),
                 v1.record('use',identifier='backward-again',loss_tokens=7,learner_step=2),
                 v1.record('use',identifier='optimizer',stage='optimizer_step_completed',loss_tokens=7))
        result=self.read(old);row=result['samples'][0];cohort=result['cohorts'][0]
        self.assertEqual(row['filters'][0]['state'],'admitted')
        self.assertEqual(row['backward_mask_counts'],{'zero':1,'positive':1})
        self.assertEqual((cohort['bound_samples'],cohort['samples_with_backward'],cohort['samples_with_optimizer']),(1,1,1))
        self.assertEqual((cohort['backward_receipts'],cohort['optimizer_receipts']),(2,1))
        self.assertEqual(self.read(new)['samples'],[])
        with self.assertRaisesRegex(InputError,'exact reviewed'):self.read(new,source_hash=result['source_hash'])

    def test_named_filters_conflicting_batches_and_no_inferred_training_use(self):
        source=self.source('a');self.add(v1.record('sample'),v1.record('score',value=1),v1.record('selection'))
        self.add(v1.record('selection',identifier='other',decision='admitted',filter='quality'),
                 v1.record('selection',identifier='batch2',decision='admitted',batch_id='b2'))
        row=self.read(source)['samples'][0]
        self.assertEqual({r['filter']:r['state'] for r in row['filters']},{'length':'varies_by_batch','quality':'admitted'})
        self.assertEqual(row['use_counts'],{})
        self.add(v1.record('selection',identifier='conflict',decision='admitted'))
        self.assertEqual(self.read(source)['samples'][0]['filters'][0]['state'],'conflicting')

    def test_unpinned_or_orphan_or_text_matching_samples_never_join(self):
        source=self.source('a');self.source('b')
        no_pin=v1.record('sample');no_pin['evidence'].pop('source_revision')
        self.add(no_pin,v1.record('use'),v1.record('sample','b'),v1.record('use','b'))
        self.add2(v2.record('sample','no-map'),v2.record('use','no-map'))
        result=self.read(source)
        self.assertEqual(result['counts']['bound_samples'],0)
        self.assertEqual(result['samples'],[])

    def test_source_span_and_conflicting_declaration_checks(self):
        source=self.source('a','early answer');self.source('b','later answer')
        run=self.store.get(source['id'],raw=True)['run'];event=next(e for e in run['events'] if e['text']=='early answer')
        good=self.declare2('early');good['data']['source']['spans']=[dict(event_id=event['id'],source_pointer=event['source_pointer'],start=0,end=5,text='early')]
        bad=copy.deepcopy(good);bad['sample']['id']='bad';bad['id']='sample/bad';bad['data']['source']['spans'][0]['text']='wrong'
        self.add2(good,bad,self.declare2('conflict'))
        second=self.declare2('conflict','b');second['id']='second-declaration';self.add2(second)
        result=self.read(source);states={r['sample_id']:r['binding'] for r in result['samples']}
        self.assertEqual(states,dict(early='exact_source_spans',bad='invalid_source_spans',conflict='conflicting_declarations'))
        self.assertEqual(result['counts']['bound_samples'],1)
        self.assertNotIn('"text": "early"',json.dumps(result))
        self.assertIn('text_digest',json.dumps(result))

    def test_experiment_conflicts_and_splits_do_not_share_stage_denominators(self):
        source=self.source('a')
        self.add(v1.record('sample'),v1.record('use'))
        self.add2(self.declare2('train'),v2.record('use','train'),self.declare2('eval',split='evaluation'))
        self.add2(self.declare2('wrong'),experiment='other')
        result=self.read(source)
        self.assertEqual(len(result['cohorts']),3)
        self.assertEqual(result['completeness']['excluded_bindings'],{'experiment_conflict':1})
        self.assertEqual(next(c for c in result['cohorts'] if c['split']=='evaluation')['samples_with_backward'],0)
        self.assertEqual(self.read(source,experiment='exp')['counts']['returned_samples'],3)

    def test_bounded_read_never_reports_partial_sample_as_unused(self):
        source=self.source('a');self.add2(self.declare2('a'),v2.record('use','a'),self.declare2('b'))
        with patch.object(exposure,'MAX_RECORDS',1):
            result=self.read(source)
        self.assertFalse(result['completeness']['complete'])
        self.assertEqual(result['samples'][0]['binding'],'record_limit')
        self.assertNotIn('use_counts',result['samples'][0])
        with patch.object(exposure,'MAX_SAMPLES',1):result=self.read(source)
        self.assertTrue(result['completeness']['sample_limit_reached'])
        with patch.object(exposure,'MAX_RECORD_CHARS',10):result=self.read(source)
        self.assertEqual(result['counts']['bound_samples'],0)
        self.assertIn('record_size_limit',result['completeness']['excluded_bindings'])

    def test_unrelated_changes_stable_late_use_invalidates_attach_and_frozen_result_survives(self):
        source=self.source('a');self.add(v1.record('sample'));before=self.read(source)
        root=self.plan(self.base());saved=self.finding(root,evidence=[exposure.reference(before)])
        self.source('b');self.add(v1.record('sample','b'),v1.record('use','b'))
        self.assertEqual(before,self.read(source))
        self.add(v1.record('use'))
        with self.assertRaisesRegex(InputError,'changed'):follow.evidence(self.store,[exposure.reference(before)])
        self.assertEqual(investigations.read(self.store,saved['id']),saved)
        frozen=saved['follow_up']['checks'][0]['results'][0]['evidence'][0]['snapshot']
        self.assertEqual(frozen,before)
        self.assertIn(before['snapshot_id'],dumps(follow.bundle(self.store,saved['id'])))
        forged=exposure.reference(self.read(source));forged['snapshot']={}
        with self.assertRaises(InputError):follow.evidence(self.store,[forged])

    def test_sdk_http_scope_and_projection_parity(self):
        source=self.source('a');self.add(v1.record('sample'),v1.record('use'))
        w=Workspace(self.db)
        direct=self.read(source)
        self.assertEqual(w.training_exposure(source['id']),direct)
        with self.assertRaisesRegex(InputError,'scope'):Workspace(self.db,experiment='other').training_exposure(source['id'])
        endpoint=self.start_server()
        with urlopen(endpoint+'/api/training-exposure?'+urlencode(dict(run_id=source['id'],source_hash=direct['source_hash']))) as response:
            self.assertEqual(json.load(response),direct)

    def test_one_read_snapshot_does_not_mix_a_late_writer_into_the_result(self):
        source=self.source('a');self.add(v1.record('sample'));original=exposure._candidates
        inserted=False
        def deliver_after_candidate_read(*args):
            nonlocal inserted
            rows=original(*args)
            if not inserted:
                inserted=True;self.add(v1.record('use'))
            return rows
        with patch.object(exposure,'_candidates',side_effect=deliver_after_candidate_read):
            before=self.read(source)
        self.assertEqual(before['samples'][0]['use_counts'],{})
        self.assertEqual(self.read(source)['samples'][0]['use_counts'],{'backward_completed':1})

    def test_tensor_projection_and_targeted_query_indexes(self):
        source=self.source('a');self.add2(self.declare2('a'))
        with self.store.connect() as c:
            # Storage-level stress control; the source mapping is unchanged.
            raw=json.loads(c.execute('SELECT document FROM training_sample_records').fetchone()[0])
            raw['data']['token_context']={'large_test_payload':'x'*100000}
            c.execute('UPDATE training_sample_records SET document=?',(dumps(raw),))
            statements=[];c.set_trace_callback(statements.append)
            exposure._candidates(c,'training_sample_records','sample_id',True,source['id'],None)
            plan=' '.join(str(tuple(r)) for r in c.execute('EXPLAIN QUERY PLAN '+statements[-1]))
        result=self.read(source);r=result['samples'][0]['records'][0]
        self.assertNotIn('token_context',r['data'])
        self.assertEqual(r['omitted_data_fields'],['token_context'])
        self.assertIn('independent_source_declaration',plan)
        self.assertIn('revision_run',plan)

    def test_retained_native_optimizer_capture_matches_existing_projection(self):
        path=Path(__file__).resolve().parents[1]/'research/optimizer-use-2026-10-11/clock-verified/payloads.jsonl'
        sources=[]
        for line in path.read_text(encoding='utf-8').splitlines():
            payload=json.loads(line)
            if 'training_records' in payload:lineage.receive(self.store,payload['training_records'])
            else:sources.append(self.store.ingest(payload))
        existing=lineage.snapshot(self.store)
        stages=Counter()
        for source in sources:
            got=self.read(source)
            expected=[r for r in existing['samples'] if r['run_id']==source['id']]
            self.assertEqual(got['counts']['bound_samples'],len(expected))
            for row in got['samples']:
                old=next(r for r in expected if r['producer']==row['producer'] and r['rollout_id']==row['sample_id'])
                self.assertEqual(row['use_counts'],old['use_counts'])
            for c in got['cohorts']:
                for key in ('bound_samples','backward_receipts','optimizer_receipts'):stages[key]+=c[key]
                if c['split']=='evaluation':self.assertEqual(c['backward_receipts']+c['optimizer_receipts'],0)
        self.assertEqual(dict(stages),dict(bound_samples=16,backward_receipts=24,optimizer_receipts=24))
