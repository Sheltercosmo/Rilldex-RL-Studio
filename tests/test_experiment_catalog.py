from pathlib import Path
import tempfile
import unittest
from tracker.store import Store
from tracker.portable import generation_document
from tracker.trainer_telemetry import TrainerTelemetry
from tracker.experiment_catalog import catalog
from tracker.first_session import example, EXPERIMENT
from tracker.schema import InputError


class ExperimentCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite')

    def logger(self,name,environment='software',objective='grpo'):
        return TrainerTelemetry(self.store,experiment=name,framework='trl-grpo',framework_version='fixture',
            objective=objective,producer=name,session='one',environment=environment)

    def test_empty_and_separate_record_counts(self):
        self.assertEqual(catalog(self.store)['total'],0)
        example(self.store);example(self.store)
        row=catalog(self.store)['rows'][0]
        self.assertEqual(row['experiment'],EXPERIMENT)
        self.assertEqual((row['rollouts'],row['logs'],row['executions']),(1,1,3))
        self.assertEqual(row['trainer_contexts'][0]['objective'],'illustration')

    def test_revisions_are_one_rollout_and_unassigned_stays_separate(self):
        for i in range(3):
            self.store.ingest(dict(producer='p',rollout_id='r',revision=i,state='in_progress' if i<2 else 'complete',
                document=generation_document('q','a'*i),metadata={'experiment':'live','environment':'software'}))
        self.store.ingest(dict(producer='p',rollout_id='unassigned',revision=0,state='complete',document=generation_document('q','b')))
        data=catalog(self.store);self.assertEqual(data['rows'][0]['rollouts'],1);self.assertEqual(data['unassigned_rollouts'],1)
        self.assertEqual(catalog(self.store,environment='airline')['total'],0)

    def test_scalar_only_runs_and_multiple_objectives_are_visible(self):
        self.logger('job').log({'reward':1},step=0)
        self.logger('job',objective='gspo').log({'reward':2},step=1)
        self.logger('other',environment='airline').log({'reward':0},step=0)
        data=catalog(self.store,environment='software');self.assertEqual(data['total'],1)
        row=data['rows'][0];self.assertEqual(row['rollouts'],0);self.assertEqual(row['logs'],2)
        self.assertEqual({r['objective'] for r in row['trainer_contexts']},{'grpo','gspo'})
        self.assertNotIn('status',row)

    def test_search_pagination_unicode_and_literal_wildcards(self):
        for name in ['alpha','beta','alpha_100%','实验']:
            self.logger(name).log({'reward':1},step=0)
        self.assertEqual(catalog(self.store,q='%')['total'],1)
        self.assertEqual(catalog(self.store,q='ALPHA')['total'],2)
        self.assertEqual(catalog(self.store,q='实验')['total'],1)
        first=catalog(self.store,limit=2);second=catalog(self.store,limit=2,offset=2)
        self.assertEqual(first['total'],4)
        self.assertEqual(len({r['experiment'] for r in first['rows']+second['rows']}),4)
        for kwargs in [dict(limit=0),dict(limit=True),dict(offset=-1),dict(q='x'*201)]:
            with self.assertRaises(InputError):catalog(self.store,**kwargs)


if __name__=='__main__':unittest.main()
