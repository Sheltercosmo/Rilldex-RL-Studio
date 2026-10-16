import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from tracker import monitoring as m, monitor_comparisons as comparisons, graph_store
from tracker.store import Store
from tracker.schema import InputError, digest
from tracker.adapters import normalize
from tracker.workspace_analysis import Workspace
from tracker.workspace_snapshot import export as export_workspace, restore
from rilldex import chat_document


class WindowComparisonTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.store=Store(self.root/'db.sqlite')
        self.monitor=m.create(self.store,dict(name='Source success',kind='metric',metric='recorded_success',observer='source'))
        self.serial=0

    def add(self,step,success,environment='terminal',**metadata):
        self.serial+=1
        context=dict(experiment='test',environment=environment,training_step=step,training_step_basis='generation',
                     split='train',task_id='task')
        context.update(metadata)
        doc=chat_document([dict(role='user',content='Work '+str(self.serial)),dict(role='assistant',content='Done')],
            metadata=context,success=success)
        run=normalize(doc)[0];self.store.add([run]);return run

    def capture(self,**options):
        return comparisons.save(self.store,self.monitor['id'],baseline=[0,0],current=[1,1],experiment='test',**options)

    def test_changing_environment_mix_is_not_within_cohort_regression(self):
        for step,counts in [(0,(3,1)),(1,(1,3))]:
            for env,count,outcome in [('terminal',counts[0],True),('business',counts[1],False)]:
                for _ in range(count):self.add(step,outcome,env)
        m.sync(self.store);d=self.capture();mix=d['mix']
        self.assertEqual((mix['baseline'],mix['current'],mix['observed_delta']),(.75,.25,-.5))
        self.assertEqual((mix['within_cohort_delta'],mix['composition_component']),(0,-.5))
        self.assertTrue(all(r['delta']==0 for r in d['cohorts']))
        self.assertEqual(sum(len(r['points']['current']) for r in d['cohorts']),4)

    def test_empty_pending_and_zero_opportunity_populations_are_not_zero(self):
        self.add(0,True);m.sync(self.store);self.add(1,False)
        d=self.capture();r=d['cohorts'][0]
        self.assertIsNone(r['current']['value']);self.assertEqual(r['current']['missing'],1)
        self.assertFalse(d['mix']['available'])
        self.assertIsNone(r['points']['current'][0]['value_id'])
        self.assertIsNone(comparisons.summarize([dict(value=None,status='unavailable',unknown_opportunities=2)],'opportunity_ratio')['value'])

    def test_ratio_uses_opportunities_including_unknowns_from_unmeasured_rollouts(self):
        points=[dict(value=1,numerator=1,denominator=1,status='available'),
                dict(value=0,numerator=0,denominator=9,status='available'),
                dict(value=None,status='unavailable',unknown_opportunities=3)]
        d=comparisons.summarize(points,'opportunity_ratio')
        self.assertEqual((d['value'],d['numerator'],d['denominator'],d['missing'],d['unknown_opportunities']),(.1,1,10,1,3))

    def test_different_configuration_or_clock_is_not_pooled(self):
        for step in (0,1):
            self.add(step,True)
            self.add(step,False,environment='other',training_step_basis='learner',split='eval')
        m.sync(self.store);d=self.capture()
        self.assertEqual(len(d['cohorts']),2)
        self.assertFalse(d['mix']['available'])

    def test_saved_comparison_survives_late_arrival_backup_and_restore(self):
        self.add(0,True);self.add(1,False);m.sync(self.store);saved=self.capture()
        self.add(1,True);m.sync(self.store);new=self.capture()
        self.assertEqual(saved['cohorts'][0]['current']['value'],0)
        self.assertEqual(new['cohorts'][0]['current']['value'],.5)
        self.assertEqual(comparisons.read(self.store,saved['id']),saved)
        archive=self.root/'snapshot.zip';export_workspace(self.store,archive)
        target=self.root/'restored.sqlite';restore(archive,target)
        self.assertEqual(comparisons.read(Store(target),saved['id']),saved)

    def test_python_path_uses_same_arithmetic_and_observation_scope(self):
        self.add(0,True);self.add(1,False);m.sync(self.store)
        ws=Workspace(self.store.path,experiment='test',observer='source')
        d=ws.compare_monitor(self.monitor['id'],baseline=[0,0],current=[1,1],save=True)
        self.assertEqual(comparisons.read(self.store,d['id']),d)
        self.assertEqual(ws.monitor_comparison(d['id']),d)
        self.assertEqual(ws.saved_monitor_comparisons()['comparisons'][0]['id'],d['id'])
        self.assertEqual(Workspace(self.store.path,observer='other').saved_monitor_comparisons()['comparisons'],[])
        self.assertEqual(d['cohorts'][0]['delta'],-1)
        with self.assertRaisesRegex(InputError,'observation scope'):
            Workspace(self.store.path,experiment='test',observer='other').compare_monitor(self.monitor['id'],baseline=[0,0],current=[1,1])

    def test_invalid_windows_are_rejected(self):
        for a,b in [([0,1],[1,2]),([True,1],[2,3]),([-1,0],[1,2]),([2,1],[3,4]),([0,0],[1.1,2])]:
            with self.assertRaises(InputError):comparisons.capture(self.store,self.monitor['id'],baseline=a,current=b,experiment='test')
        with self.assertRaisesRegex(InputError,'one experiment'):
            comparisons.capture(self.store,self.monitor['id'],baseline=[0,0],current=[1,1],experiment=None)

    def test_training_joins_stay_in_the_source_window_and_freeze_late_use(self):
        from tracker import training_lineage
        runs=[]
        for step in (0,1,9):
            receipt=self.store.ingest(dict(producer='worker',rollout_id=str(step),revision=0,state='complete',
                document=chat_document([dict(role='assistant',content='Source '+str(step))],success=True),
                metadata=dict(experiment='test',training_step=step,training_step_basis='generation')))
            runs.append(receipt['id'])
        def record(kind,step,data):
            return dict(id=kind+str(step),revision=0,kind=kind,sample=dict(producer='worker',id=str(step)),
                        evidence=dict(basis='test producer receipt'),data=data)
        packet=dict(schema='training-records/2',producer='learner',experiment='test',records=[
            record('sample',step,dict(split='train',step=100+step,step_basis='learner export',
                source=dict(producer='worker',rollout_id=str(step),revision=0))) for step in (0,1,9)])
        training_lineage.receive(self.store,packet);m.sync(self.store)
        saved=self.capture();bound=saved['training_lineage']['windows']
        self.assertEqual(bound['baseline']['joined_source_rollouts'],1)
        self.assertEqual(bound['current']['stages']['optimizer']['unknown_rollouts'],1)
        self.assertEqual([r['run_id'] for r in bound['current']['rollouts']],[runs[1]])
        training_lineage.receive(self.store,{**packet,'records':[record('use',1,
            dict(batch_id='update',learner_step=500,stage='optimizer_step_completed'))]})
        newer=self.capture()
        self.assertEqual(newer['training_lineage']['windows']['current']['stages']['optimizer']['member_rollouts'],1)
        self.assertEqual(comparisons.read(self.store,saved['id']),saved)

    def test_tampered_saved_comparison_is_not_served(self):
        d=self.capture()
        with self.store.connect() as c:c.execute("UPDATE monitor_comparisons SET document=json_set(document,'$.population.selected',99)")
        with self.assertRaisesRegex(InputError,'integrity'):comparisons.read(self.store,d['id'])

    def test_read_snapshot_is_stable_while_writer_commits(self):
        self.add(0,True);m.sync(self.store)
        original=m.current_values;written=False
        def concurrent(saved,monitor,runs,catalog=None):
            nonlocal written
            if not written:
                written=True;self.add(1,False);m.sync(self.store)
            return original(saved,monitor,runs,catalog)
        with patch.object(m,'current_values',side_effect=concurrent):
            d=self.capture()
        self.assertEqual(d['population']['selected'],1)
        self.assertEqual(d['cohorts'][0]['current']['total'],0)
        self.assertEqual(self.capture()['population']['selected'],2)
        with self.store.read_snapshot() as saved:
            with self.assertRaises(sqlite3.OperationalError):saved.connection.execute('DELETE FROM runs')

    def test_new_semantic_annotation_masks_old_receipt_until_materialized(self):
        run=self.add(0,True)
        def annotation(label):
            event=run['events'][-1]
            graph=graph_store.build(run,{'document':dict(source_hash=digest(run),units=[
                dict(id='unit-'+label,activity='inspect',kind='semantic',actor='agent',
                     source=dict(event_id=event['id'],start=0,end=4,text='Done'))],relations=[]),
                'observer':dict(id='reviewed',label='Reviewed')})
            with self.store.connect() as c:graph_store.save(c,graph)
        monitor=m.create(self.store,dict(name='Inspect relationship',kind='graph',observer='reviewed',
            requirement=m.graph_queries.PRESETS['assessment_of_inspection_feedback']))
        annotation('first');m.sync(self.store)
        old=m.values(self.store,monitor['id'],{run['id']})[run['id']]
        annotation('updated')
        point=next(d for d in m.snapshot(self.store)['monitors'] if d['id']==monitor['id'])['series'][0]['points'][0]
        self.assertEqual(point['status'],'pending');self.assertIsNone(point['value_id'])
        case=m.cases(self.store,monitor['id'])['rows'][0]['measurement']
        self.assertEqual(case['previous_value_id'],old['id'])
        m.sync(self.store)
        current=m.cases(self.store,monitor['id'])['rows'][0]['measurement']['id']
        self.assertNotEqual(current,old['id'])
        service=m.Service(self.store);self.addCleanup(service.close)
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and service.last!=m.fingerprint(self.store):time.sleep(.02)
        before=m.fingerprint(self.store)
        # Reproduce a slower worker republishing the older graph's cached receipt.
        with self.store.connect() as c:c.execute('UPDATE monitor_latest SET value_id=? WHERE monitor_id=? AND run_id=?',(old['id'],monitor['id'],run['id']))
        self.assertNotEqual(m.fingerprint(self.store),before)
        service.wake();deadline=time.monotonic()+8
        while time.monotonic()<deadline and m.values(self.store,monitor['id'],{run['id']})[run['id']]['id']!=current:time.sleep(.02)
        self.assertEqual(m.values(self.store,monitor['id'],{run['id']})[run['id']]['id'],current)


if __name__=='__main__':unittest.main()
