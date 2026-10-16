import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from rilldex import Workspace
from tracker import graph_store, monitoring, failure_investigations
from tracker.adapters import normalize
from tracker.analytics import Analysis
from tracker.schema import digest
from tracker.store import Store
from test_tracker import harbor


class CurrentMonitorQueriesTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'workspace.sqlite';self.store=Store(self.path)
        self.run=normalize(harbor(),'harbor',dict(experiment='train',task_id='task',training_step=0))[0]
        self.store.add([self.run]);self.graph('first')
        self.workspace=Workspace(self.path,experiment='train',observer='review')
        self.monitor=self.workspace.monitor('Flag',version='1',description='Controlled flag',unit='fraction',aggregation='incidence')
        self.monitor.run(lambda ctx:{'value':1})

    def graph(self,label):
        e=next(e for e in self.run['events'] if e['actor']=='agent')
        g=graph_store.build(self.run,{'observer':{'id':'review','label':'Review'},'document':{
            'source_hash':digest(self.run),'units':[dict(id='u-'+label,kind='semantic',actor='agent',activity='orient',
                source=dict(event_id=e['id'],start=0,end=len(e['text']),text=e['text']))],'relations':[]}})
        with self.store.connect() as c:graph_store.save(c,g)
        return g

    def test_investigation_excludes_stale_graph_measurement_like_dashboard(self):
        before=failure_investigations.snapshot(self.store,run=self.run['id'],observer='review')
        metric=lambda s:next(m for m in s['metrics'] if m['id']=='monitor:'+self.monitor.id)
        self.assertEqual(metric(before)['focus']['mean'],1)
        self.graph('second')
        dashboard=monitoring.cases(self.store,self.monitor.id)['rows'][0]['measurement']
        self.assertIsNone(dashboard['value'])
        stale=metric(failure_investigations.snapshot(self.store,run=self.run['id'],observer='review'))
        self.assertEqual(stale['focus']['n'],0)
        self.assertEqual(stale['focus']['missing'],1)
        self.assertIsNone(stale['focus']['mean'])

    def test_native_current_queries_exclude_stale_but_preserve_history(self):
        saved=self.workspace.table('monitor_values').rows
        self.assertEqual(saved[0]['is_current'],1)
        self.graph('second')
        raw=Analysis(self.path).query('SELECT value,is_latest,is_current FROM rl_monitor_values')['rows']
        self.assertEqual(raw,[{'value':1,'is_latest':1,'is_current':0}])
        self.assertEqual(self.workspace.table('monitor_values').rows,[])
        self.assertEqual(self.workspace.sql('SELECT value FROM monitor_values').rows,[])
        history=Workspace(self.path,history=True).table('monitor_values').rows
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['value'],1)
        self.monitor.run(lambda ctx:{'value':0})
        measured=self.workspace.table('monitor_values').rows
        self.assertEqual([(r['value'],r['is_current']) for r in measured],[(0,1)])

    def test_pinned_reader_does_not_mix_later_graph_writes(self):
        with Analysis(self.path).snapshot() as saved:
            before=saved.c.total_changes
            self.graph('later-writer')
            rows=saved.table('monitor_values')['rows']
            self.assertEqual([(r['value'],r['is_current']) for r in rows],[(1,1)])
            self.assertEqual(saved.c.total_changes,before)
        self.assertEqual(self.workspace.table('monitor_values').rows,[])

    def test_current_values_pins_receipts_and_inputs_during_writer_arrival(self):
        original=monitoring.values
        def arrive(*args,**kwargs):
            rows=original(*args,**kwargs)
            self.graph('concurrent-writer')
            return rows
        definition=next(m for m in monitoring.definitions(self.store) if m['id']==self.monitor.id)
        runs=monitoring.population(self.store)
        with patch.object(monitoring,'values',side_effect=arrive):
            rows=monitoring.current_values(self.store,definition,runs)
        self.assertEqual(rows[self.run['id']]['value'],1)
        self.assertIsNone(monitoring.current_values(self.store,definition,runs)[self.run['id']]['value'])

    def test_investigation_keeps_one_graph_choice_when_worker_publishes_mid_read(self):
        original=monitoring.current_values
        old=next(g['id'] for g in graph_store.catalog(self.store)['graphs'] if g['observer']=='review')
        def arrive(*args,**kwargs):
            self.graph('during-investigation')
            self.monitor.run(lambda ctx:{'value':0})
            return original(*args,**kwargs)
        with patch.object(monitoring,'current_values',side_effect=arrive):
            result=failure_investigations.snapshot(self.store,run=self.run['id'],observer='review')
        metric=next(m for m in result['metrics'] if m['id']=='monitor:'+self.monitor.id)
        self.assertEqual(metric['focus']['mean'],1)
        self.assertEqual(metric['values'][self.run['id']]['graph_id'],old)
        sequence=next(n for n in result['process']['plan']['definition']['nodes'] if n['op']=='sequence')
        self.assertEqual(sequence['params']['graph_id'],old)
        self.assertEqual(self.workspace.table('monitor_values').rows[0]['value'],0)

    def test_paused_definition_retains_current_receipt_without_claiming_active(self):
        monitoring.enabled(self.store,self.monitor.id,False)
        rows=self.workspace.table('monitor_values').rows
        self.assertEqual(rows[0]['is_current'],1)
        self.assertFalse(self.workspace.table('monitor_definitions').rows[0]['enabled'])

    def test_late_old_publication_is_not_current_and_reconciles_without_callback(self):
        old=self.workspace.table('monitor_values').rows[0]['value_id']
        self.graph('second');self.monitor.run(lambda ctx:{'value':0})
        current=self.workspace.table('monitor_values').rows[0]['value_id']
        with self.store.connect() as c:
            c.execute('UPDATE monitor_latest SET value_id=? WHERE monitor_id=?',(old,self.monitor.id))
        self.assertEqual(self.workspace.table('monitor_values').rows,[])
        raw=Analysis(self.path).query('SELECT value_id,is_latest,is_current FROM rl_monitor_values')['rows']
        self.assertEqual({r['value_id']:(r['is_latest'],r['is_current']) for r in raw},{old:(1,0),current:(0,0)})
        result=self.monitor.run(lambda ctx:self.fail('An unchanged input was recomputed'))
        self.assertEqual(result['skipped'],1)
        self.assertEqual(self.workspace.table('monitor_values').rows[0]['value_id'],current)

    def test_current_source_metric_receipt_tracks_metric_input_updates(self):
        from tracker.rollout_metrics import source_record,save
        monitor=monitoring.create(self.store,dict(name='Actions',kind='metric',observer='source',metric='actions'))
        monitoring.sync(self.store,monitor_ids={monitor['id']})
        before=Analysis(self.path).table('monitor_values')['rows']
        self.assertTrue(any(r['monitor_id']==monitor['id'] for r in before))
        revised=source_record(self.run);revised['metrics']['actions']['value']=17
        with self.store.connect() as c:save(c,revised)
        after=Analysis(self.path).query('SELECT is_current FROM rl_monitor_values WHERE monitor_id=?',[monitor['id']])['rows']
        self.assertEqual(after,[{'is_current':0}])
        monitoring.sync(self.store,monitor_ids={monitor['id']})
        measured=Workspace(self.path).table('monitor_values',monitor_id=monitor['id']).rows
        self.assertEqual([(r['value'],r['is_current']) for r in measured],[(17,1)])

    def test_portable_flags_are_frozen_and_older_datasets_do_not_assert_currentness(self):
        frozen=self.path.parent/'dataset.sqlite'
        Analysis(self.path).database(frozen)
        self.graph('after-export')
        self.assertEqual(Analysis(self.path).table('monitor_values')['rows'],[])
        self.assertEqual(Analysis(frozen).table('monitor_values')['rows'][0]['is_current'],1)
        # Simulate a portable dataset from before freshness flags existed.
        with closing(sqlite3.connect(frozen)) as c:
            c.execute('ALTER TABLE rl_monitor_values DROP COLUMN is_current')
            c.commit()
        self.assertEqual(Analysis(frozen).table('monitor_values')['rows'],[])
        old=Analysis(frozen).table('monitor_values',history=True)
        self.assertEqual(old['rows'][0]['value'],1)
        self.assertIsNone(old['rows'][0]['is_current'])
        self.assertEqual(old['source_coverage']['freshness'],'unavailable')

    def test_superseded_source_is_not_current_even_with_latest_published_index(self):
        packet={'producer':'worker','rollout_id':'a','revision':0,'state':'complete','format':'harbor',
                'document':harbor(),'metadata':{'experiment':'stream','training_step':1}}
        old=self.store.ingest(packet)['id']
        monitor=Workspace(self.path,experiment='stream',observer='source').monitor('Streaming flag',version='1',description='Source revision control')
        monitor.run(lambda ctx:{'value':1})
        packet['revision']=1;packet['document']['steps'][-1]['message']='A newer revision'
        new=self.store.ingest(packet)['id']
        rows=Analysis(self.path).query('SELECT run_id,is_latest,is_current FROM rl_monitor_values WHERE monitor_id=?',[monitor.id])['rows']
        self.assertEqual(rows,[{'run_id':old,'is_latest':1,'is_current':0}])
        monitor.run(lambda ctx:{'value':0})
        rows=Workspace(self.path).table('monitor_values',monitor_id=monitor.id).rows
        self.assertEqual([(r['run_id'],r['value'],r['is_current']) for r in rows],[(new,0,1)])


if __name__=='__main__':unittest.main()
