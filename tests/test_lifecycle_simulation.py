import json
from pathlib import Path
import tempfile
import unittest

from scripts.rl_lifecycle_simulation import EXPERIMENT, dashboard_ready, document, facts
from tracker import monitoring, training_health, training_lineage
from tracker.export_watch import ExportWatcher
from tracker.store import Store


class LifecycleReadinessTests(unittest.TestCase):
    def test_measured_partial_tail_does_not_satisfy_final_batch_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / 'workspace.sqlite')
            outputs = root / 'outputs'
            outputs.mkdir()
            path = outputs / 'worker.jsonl'
            ids = {monitoring.create(store, dict(name=measure, kind='analysis', observer='source',
                   analysis=dict(measure=measure)))['id']
                   for measure in ('next_check_success', 'next_check_success_changed')}
            watcher = ExportWatcher(store, outputs, producer='files', metadata=dict(experiment=EXPERIMENT))
            for index in range(4):
                training_lineage.receive(store, dict(schema='training-records/2', producer='files',
                    experiment=EXPERIMENT, records=facts(1, index, 'files', 'business-workflow')))
                for revision in (0, 1):
                    envelope = dict(rollout_id=f'batch-1/sample-{index}', revision=revision,
                        state='in_progress' if revision == 0 else 'complete',
                        document=document(1, index, 'business-workflow', partial=revision == 0))
                    with path.open('ab') as stream:
                        stream.write(json.dumps(envelope).encode())
                        if (index, revision) != (3, 1):
                            stream.write(b'\n')
            self.assertEqual(watcher.poll()['waiting'], 1)
            monitoring.sync(store)
            result = monitoring.snapshot(store, experiment=EXPERIMENT)
            self.assertEqual(result['population'], 4)
            self.assertTrue(all(m['coverage']['statuses'].get('pending', 0) == 0 for m in result['monitors']))
            health = training_health.snapshot(store, experiment=EXPERIMENT)
            self.assertEqual(sum(c['missing_source'] for c in health['cohorts']), 1)
            self.assertFalse(dashboard_ready(result, ids, 4))

            with path.open('ab') as stream:
                stream.write(b'\n')
            self.assertEqual(watcher.poll()['ingested'], 1)
            # Source completion alone does not replace pending monitor work.
            self.assertFalse(dashboard_ready(monitoring.snapshot(store, experiment=EXPERIMENT), ids, 4))
            monitoring.sync(store)
            self.assertTrue(dashboard_ready(monitoring.snapshot(store, experiment=EXPERIMENT), ids, 4))
            health = training_health.snapshot(store, experiment=EXPERIMENT)
            self.assertEqual(sum(c['missing_source'] for c in health['cohorts']), 0)


if __name__ == '__main__':
    unittest.main()
