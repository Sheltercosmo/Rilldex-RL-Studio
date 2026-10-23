"""Full-history session selection, independent of the 64-series plot budget."""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError

from rilldex import Workspace
from tracker.store import Store
from tracker import telemetry_queries as q,trainer_telemetry as t
from tracker.schema import InputError
import test_generation_cohort_transport as transport


def add(store,session,*,producer='learner',experiment='many-restarts',clock='learner_update',start=0,n=4):
    logger=t.TrainerTelemetry(store,producer=producer,experiment=experiment,framework='trl-grpo',framework_version='test',
        objective='grpo',session=session,clock=clock)
    for i in range(start,start+n):logger.log({'loss':.1+i,'reward':.5,'entropy':.7,'kl':.01,'clip_ratio/region_mean':.1,'num_tokens':1000+i},step=i)


class SessionTests(unittest.TestCase):
    def setUp(self):
        root=tempfile.TemporaryDirectory();self.addCleanup(root.cleanup);self.root=Path(root.name);self.store=Store(self.root/'study.sqlite')

    def test_latest_is_resolved_before_metric_limit_and_never_changes_for_old_late_arrivals(self):
        for i in range(120):add(self.store,f'restart-{i:03}')
        legacy=q.query(self.store);self.assertEqual((legacy['total_series'],legacy['loaded_series']),(720,64))
        selected=q.query(self.store,experiment='many-restarts',session_mode='latest');cutoff=selected['as_of']
        self.assertEqual(selected['total_series'],6);self.assertEqual(selected['records'],4)
        self.assertEqual({s['context']['session'] for s in selected['series']},{'restart-119'})
        self.assertEqual(selected['session_inventory']['total'],120)
        self.assertEqual(selected['session_selection']['selected']['ordinal'],120)
        add(self.store,'restart-000',start=99,n=1)
        self.assertEqual(q.query(self.store,session_mode='latest')['session_selection']['selected']['session'],'restart-119')
        add(self.store,'new-after-selection',n=1)
        frozen=q.query(self.store,session_mode='latest',as_of=cutoff)
        self.assertEqual(frozen['series'],selected['series'])
        self.assertEqual(frozen['session_inventory'],selected['session_inventory'])
        self.assertEqual(q.query(self.store,session_mode='latest')['records'],1)

    def test_workers_same_session_names_and_experiments_do_not_merge(self):
        for worker in ('a','b','c'):add(self.store,'shared',producer=worker)
        add(self.store,'shared',producer='a',experiment='another',start=100)
        exact=q.query(self.store,experiment='many-restarts',producer='a',session='shared')
        self.assertEqual(exact['records'],4);self.assertEqual(exact['total_series'],6)
        self.assertEqual(q.query(self.store,experiment='many-restarts',session='shared')['records'],12)
        self.assertEqual(q.query(self.store,producer='missing',session_mode='latest')['records'],0)
        self.assertEqual(q.query(self.store,experiment='many-restarts',session='absent')['records'],0)
        self.assertEqual(q.sessions(self.store)['total'],4)
        latest=q.query(self.store,producer='a',session_mode='latest')
        self.assertEqual(latest['session_selection']['selected']['experiment'],'another')
        self.assertEqual({s['context']['experiment'] for s in latest['series']},{'another'})

    def test_inventory_search_paging_and_exact_catalog_cover_hidden_history(self):
        for i in range(31):add(self.store,f'restart-{i:03}',n=1)
        pages=[];offset=0
        while True:
            page=q.sessions(self.store,limit=7,offset=offset);pages+=page['rows']
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual([r['ordinal'] for r in pages],list(range(31,0,-1)))
        self.assertEqual(q.sessions(self.store,search='restart-003')['rows'][0]['ordinal'],4)
        self.assertEqual(q.sessions(self.store,search='%')['total'],0)
        exact=q.catalog(self.store,producer='learner',session='restart-003')
        self.assertEqual(exact['total_series'],6)
        self.assertTrue(all(s['context']['session']=='restart-003' for s in exact['series']))
        self.assertEqual(q.catalog(self.store,session_mode='latest')['session_selection']['selected']['ordinal'],31)

    def test_freeze_export_range_and_python_access_use_same_scope(self):
        add(self.store,'old',start=100)
        add(self.store,'reset')
        selected=Workspace(self.store.path,experiment='many-restarts').trainer_signals(session_mode='latest',start=1,end=2)
        self.assertEqual(selected['records'],2);self.assertEqual(Workspace(self.store.path).trainer_sessions()['total'],2)
        self.assertEqual(q.query(self.store,session='old',start=0,end=2)['records'],0)
        add(self.store,'later')
        cutoff,packets=q.export_records(self.store,session_mode='latest',start=1,end=2,as_of=selected['as_of'])
        rows=list(packets);self.assertEqual(len(rows),2)
        self.assertTrue(all(p['records'][0]['session']=='reset' for p in rows))
        self.assertEqual([p['records'][0]['step'] for p in rows],[1,2])
        replica=Store(self.root/'replica.sqlite')
        for p in rows:t.receive(replica,p)
        self.assertEqual(q.query(replica)['records'],2)
        self.assertEqual(q.query(self.store,session_mode='latest',as_of=0)['records'],0)

    def test_clock_boundaries_and_invalid_selection(self):
        add(self.store,'old',clock='learner_update');add(self.store,'new',clock='environment_timesteps')
        self.assertEqual(q.query(self.store,session='new')['clock'],'environment_timesteps')
        self.assertEqual(q.query(self.store,session_mode='latest')['session_selection']['selected']['session'],'old')
        _,packets=q.export_records(self.store,session_mode='latest')
        self.assertEqual({p['records'][0]['session'] for p in packets},{'old'})
        for options in ({'session_mode':'bad'},{'session_mode':'latest','session':'new'},{'producer':''},{'session':[]},{'producer':'x'*1001}):
            with self.subTest(options=options),self.assertRaises(InputError):q.query(self.store,**options)


class SessionHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_session_query_catalog_export_and_malformed_scope(self):
        add(self.store,'same',producer='worker-a');add(self.store,'same',producer='worker-b')
        endpoint=self.start_server()+'/api/trainer-telemetry/'
        def get(path,**options):
            with urlopen(endpoint+path+'?'+urlencode(options)) as response:return json.load(response)
        inventory=get('sessions',limit=1);self.assertEqual(inventory['next_offset'],1)
        self.assertEqual(get('sessions',search='worker-a')['rows'][0]['producer'],'worker-a')
        selection=dict(experiment='many-restarts',producer='worker-a',session='same')
        result=get('query',**selection);self.assertEqual(result['records'],4)
        self.assertTrue(all(s['context']['producer']=='worker-a' for s in get('catalog',**selection)['series']))
        with urlopen(endpoint+'export?'+urlencode({**selection,'as_of':result['as_of']})) as response:
            packets=[json.loads(line) for line in response]
        self.assertEqual(len(packets),4);self.assertTrue(all(p['producer']=='worker-a' for p in packets))
        with self.assertRaises(HTTPError) as error:get('query',session_mode='bad')
        self.assertEqual(error.exception.code,400)


if __name__=='__main__':unittest.main()
