import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker import retained_rl_signals as signals, value_observations as vo
from tracker import training_health, training_lineage, slime_debug
from tracker.adapters import normalize
from tracker.capture import Outbox
from tracker.store import Store
from tracker.schema import InputError
from test_slime_debug import fixture, prepare


def sources(r=None,t=None):
    if r is None:r,t=fixture()
    prepared=prepare(r,t)
    return prepared,[normalize(s['document'],s['format'],s['metadata'])[0] for s in prepared['snapshots']]


class RetainedSignalTests(unittest.TestCase):
    def test_pinned_source_fields_preserve_native_masks_and_no_use_claim(self):
        _,docs=sources();before=copy.deepcopy(docs)
        one=signals.extract(docs[0],details=True)
        self.assertEqual(one['positions'],[0,1]);self.assertEqual(one['mask'],[1,0])
        self.assertEqual(one['fields']['advantages']['count'],1)
        self.assertEqual(one['fields']['advantages']['positive'],1)
        self.assertEqual(one['value_return']['mean_squared_error'],1.)
        self.assertEqual(one['settings_status'],'not_recorded')
        self.assertNotIn('learner_step',one);self.assertNotIn('stage',one)
        self.assertNotIn('value_version',one)
        self.assertEqual(docs,before)

    def test_summary_does_not_materialize_full_arrays(self):
        _,docs=sources();summary=signals.extract(docs[0])
        self.assertNotIn('native_fields',summary)
        self.assertNotIn('positions',summary)
        self.assertNotIn('mask',summary)

    def test_wrong_source_identity_or_token_context_cannot_measure_another_sample(self):
        prepared,docs=sources();sample=next(r for r in prepared['packets'][0]['records'] if r['kind']=='sample')
        result=signals.for_sample(docs[0],sample['sample']['id'],sample['data'])
        self.assertEqual(result['status'],'captured')
        self.assertEqual(signals.for_sample(docs[0],'wrong',sample['data'])['status'],'sample_identity_mismatch')
        changed=copy.deepcopy(sample['data']);changed['token_context']['training']['input_ids'][0]=9
        self.assertEqual(signals.for_sample(docs[0],sample['sample']['id'],changed)['status'],'sample_token_context_mismatch')
        docs[0]['metadata']['sample_id']='wrong'
        self.assertEqual(signals.extract(docs[0])['status'],'invalid_native_evidence')

    def test_bad_native_shape_is_unavailable_not_a_dashboard_error(self):
        _,docs=sources()
        for key,value in [('values',[1.]),('loss_masks',[True,1]),('response_lengths',99),('rollout_position',8)]:
            with self.subTest(key=key):
                doc=copy.deepcopy(docs[0]);doc['raw']['training_sample'][key]=value
                self.assertEqual(signals.extract(doc)['status'],'invalid_native_evidence')

    def test_other_adapters_unknown_pin_and_missing_rows_are_not_guessed(self):
        self.assertIsNone(signals.extract({'id':'other','raw':['native list']}))
        _,docs=sources();docs[0]['raw']['upstream_commit']='unknown'
        self.assertEqual(signals.extract(docs[0])['status'],'unsupported_revision')
        docs[1]['raw']['training_sample']=None
        self.assertEqual(signals.extract(docs[1])['status'],'no_training_row')

    def test_advantages_do_not_require_a_critic_or_value_pair(self):
        _,docs=sources();row=docs[0]['raw']['training_sample'];del row['values'];del row['returns']
        v=signals.extract(docs[0]);self.assertEqual(set(v['fields']),{'advantages'})
        self.assertIsNone(v['value_return'])
        r=signals.summarize([v]);self.assertEqual(r['fields']['advantages']['count'],1)
        self.assertIsNone(r['value_return']['mean_squared_error'])

    def test_pooling_reconciles_positions_instead_of_averaging_sample_variance(self):
        _,docs=sources();a=docs[0]['raw']['training_sample'];b=docs[1]['raw']['training_sample']
        a.update(values=[0.,900.],returns=[0.,-900.],advantages=[0.,500.])
        b.update(values=[2.,3.],returns=[1.,3.],advantages=[3.,6.])
        r=signals.summarize([signals.extract(d) for d in docs])
        self.assertEqual(r['fields']['advantages']['mean'],3)
        self.assertEqual(r['fields']['advantages']['variance'],6)
        self.assertEqual(r['fields']['advantages']['zero'],1)
        expected=vo.paired_moments([[(0.,0.)],[(2.,1.),(3.,3.)]])
        for key in ['mean_squared_error','mean_error','explained_variance','within_sample_variation_fraction']:
            self.assertAlmostEqual(r['value_return'][key],expected[key],msg=key)

    def test_masked_and_missing_fields_do_not_become_measured_zero(self):
        _,docs=sources();docs[0]['raw']['training_sample']['loss_masks']=[0,0]
        for k in signals.FIELDS:docs[1]['raw']['training_sample'].pop(k)
        r=signals.summarize([signals.extract(d) for d in docs])
        self.assertEqual(r['states'],{'captured':1,'no_signal_fields':1})
        self.assertEqual(r['fields']['advantages']['count'],0)
        self.assertIsNone(r['fields']['advantages']['mean'])
        self.assertIsNone(r['value_return']['explained_variance'])

    def test_nonfinite_statistics_do_not_break_json(self):
        _,docs=sources()
        for d in docs:
            d['raw']['training_sample'].update(values=[1e308,-1e308],returns=[-1e308,1e308],advantages=[1e308,-1e308])
        r=signals.summarize([signals.extract(d) for d in docs])
        json.dumps(r,allow_nan=False)
        self.assertIsNone(r['value_return']['mean_squared_error'])


class RetainedRoundtripTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'store.sqlite')
        self.box=Outbox(Path(tmp.name)/'outbox.sqlite',producer='slime-worker')
        self.addCleanup(self.box.close)

    def packets(self,r,t,session='branch-a'):
        prepared=slime_debug.prepare(r,t,producer='slime-worker',experiment='rl-job',session=session,tokenizer_id='test-tokens/1')
        slime_debug.enqueue(self.box,prepared)
        with self.box.connect() as c:return [json.loads(row[0]) for row in c.execute('SELECT payload FROM queue ORDER BY rowid')]

    def deliver(self,packets):
        for p in packets:
            if 'training_records' in p:training_lineage.receive(self.store,p['training_records'])
            else:self.store.ingest(p)

    def test_real_outbox_shapes_make_existing_imports_useful_without_receipts(self):
        r,t=fixture();packets=self.packets(r,t);self.deliver(packets)
        first=training_health.snapshot(self.store);c=first['cohorts'][0]
        self.assertEqual(c['dashboard']['default']['mode'],'retained')
        self.assertEqual(c['uses'],[])
        s=c['retained_rl_signals']['series'][0];self.assertEqual(s['eligible_positions'],3)
        self.assertEqual(s['points'][0]['step'],3)
        self.assertEqual(len(s['points'][0]['records']),2)
        self.assertEqual([r['retained_rl_signal']['native_position'] for r in s['points'][0]['records']],[0,1])
        record=s['points'][0]['records'][0]
        detail=signals.inspect_source(self.store,record['run_id'])
        self.assertEqual(detail['sample_id'],record['id'])
        self.assertEqual(detail['native_fields']['values'],[0.,0.])
        self.deliver(packets);self.assertEqual(first,training_health.snapshot(self.store))
        population=training_lineage.snapshot(self.store)
        self.assertTrue(all(s['use_state']=='unknown' for s in population['samples']))
        self.assertEqual(population['cohorts'][0]['counts']['optimizer'],0)

    def test_partial_arrival_does_not_invent_native_arrays(self):
        r,t=fixture();packets=self.packets(r,t)
        self.deliver([p for p in packets if 'training_records' in p])
        self.assertEqual(training_health.snapshot(self.store)['cohorts'][0]['retained_rl_signals']['series'],[])
        self.deliver(packets)
        self.assertEqual(training_health.snapshot(self.store)['cohorts'][0]['retained_rl_signals']['series'][0]['eligible_positions'],3)

    def test_sessions_do_not_share_rollout_batch_clocks(self):
        r,t=fixture();self.deliver(self.packets(r,t))
        self.deliver(self.packets(r,t,'resumed-branch'))
        series=training_health.snapshot(self.store)['cohorts'][0]['retained_rl_signals']['series']
        self.assertEqual(len(series),2)
        self.assertEqual([s['samples'] for s in series],[2,2])

    def test_multi_batch_signal_gap_is_retained(self):
        r,t=fixture();self.deliver(self.packets(r,t))
        r['rollout_id']=4;t['rollout_id']=4
        for row in t['samples']:row['loss_masks']=[0,0]
        self.deliver(self.packets(r,t))
        s=training_health.snapshot(self.store)['cohorts'][0]['retained_rl_signals']['series'][0]
        self.assertEqual([p['step'] for p in s['points']],[3,4])
        self.assertIsNone(s['points'][1]['fields']['advantages']['mean'])

    def test_wrong_source_endpoint_fails_without_a_fabricated_example(self):
        with self.assertRaises(InputError):signals.inspect_source(self.store,'unknown')


if __name__=='__main__':unittest.main()
