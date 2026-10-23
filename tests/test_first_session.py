from pathlib import Path
import tempfile
import unittest

from tracker.first_session import example, readiness, EXPERIMENT
from tracker.store import Store
from tracker.connections import default_producer, preview, validate
from tracker import monitoring, execution_timeline
from tracker.portable import generation_document
from tracker.adapters import normalize


class FirstSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'workspace.sqlite')

    def test_definitions_are_not_data_and_example_replay_has_exact_source_links(self):
        monitoring.seed(self.store)
        self.assertTrue(readiness(self.store)['empty'])
        a=example(self.store);b=example(self.store)
        self.assertEqual(a,b)
        state=readiness(self.store,experiment=EXPERIMENT)
        self.assertFalse(state['empty']);self.assertTrue(state['example'])
        self.assertEqual({x['id']:x['count'] for x in state['features']},dict(source=1,training=1,semantic=0,telemetry=1,execution=3))
        timeline=execution_timeline.snapshot(self.store,experiment=EXPERIMENT,clock='example/shared-seconds')
        self.assertEqual(len(timeline['executions']),3)
        self.assertTrue(all(x['run_id']==a['run_id'] for x in timeline['executions']))
        self.assertEqual(len(timeline['logs']),1)
        source=self.store.get(a['run_id'],raw=True)['run']
        self.assertTrue(source['metadata']['synthetic'])
        self.assertTrue(any('4 tests passed' in e.get('text','') for e in source['events']))

    def test_unrelated_telemetry_and_maps_do_not_make_import_analysis_ready(self):
        example(self.store)
        run=normalize(generation_document('question','answer'))[0];self.store.add([run])
        data=readiness(self.store,run_ids=[run['id']])
        self.assertEqual({x['id']:x['count'] for x in data['features']},dict(source=1,training=0,semantic=0,telemetry=0,execution=0))
        self.assertFalse(readiness(self.store,experiment='not-yet-recorded')['empty'])

    def test_directory_identity_is_stable_editable_and_preview_matches_connection(self):
        directory=self.root/'outputs';directory.mkdir()
        body=dict(root=str(directory),mode='exports',metadata={'experiment':'test'})
        automatic=default_producer(body)
        self.assertEqual(automatic,default_producer({**body,'producer':''}))
        self.assertEqual(default_producer({**body,'producer':'my-job'})['producer'],'my-job')
        preview(self.store,body);config,_=validate(self.store,body)
        self.assertEqual(config['producer'],automatic['producer'])
        self.assertEqual(default_producer({**body,'root':str(directory/'.')})['producer'],config['producer'])


if __name__=='__main__':unittest.main()
