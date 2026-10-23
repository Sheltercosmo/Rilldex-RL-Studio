import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor

from tracker import telemetry_queries as q, trainer_telemetry as t
from tracker.schema import InputError
from tracker.store import Store
from tracker.telemetry_cli import run
import test_generation_cohort_transport as transport


CONFIG = dict(experiment='long-study',producer='learner',framework='trl-grpo',framework_version='test',
              objective='grpo/test',session='start-1')


def add(store, rows, **fields):
    records=[]
    for step,logs in rows:
        packet=t.packet(logs,step=step,**{**CONFIG,**fields})
        records+=packet['records']
        if len(records)==1000:
            t.receive(store,{**packet,'records':records});records=[]
    if records:t.receive(store,{**packet,'records':records})


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'study.sqlite')

    def test_session_order_uses_first_receipt_and_stays_frozen_on_late_records(self):
        add(self.store,[(100,{'loss':1.})],session='old')
        add(self.store,[(0,{'loss':2.})],session='reset')
        frozen=q.query(self.store);cutoff=frozen['as_of']
        first={s['context']['session']:s['full_range']['first_received_record'] for s in frozen['series']}
        self.assertLess(first['old'],first['reset'])
        add(self.store,[(101,{'loss':.9})],session='old')
        self.assertEqual(first,{s['context']['session']:s['full_range']['first_received_record'] for s in q.query(self.store,as_of=cutoff)['series']})

    def test_full_long_run_retains_early_spike_and_exact_stats(self):
        add(self.store,((i,{'loss':20 if i==17 else -4 if i==19001 else math.sin(i/25)/5+.8}) for i in range(20000)))
        result=q.query(self.store,max_points=120,half_life=10);s=result['series'][0]
        self.assertEqual(result['records'],20000)
        self.assertEqual(s['stats']['coordinates'],20000)
        self.assertLessEqual(len(s['points']),120)
        self.assertTrue({0,17,19001,19999}<={p['step'] for p in s['points']})
        self.assertEqual(s['stats']['maximum']['value'],20)
        self.assertEqual(s['stats']['minimum']['step'],19001)
        window=q.query(self.store,start=19000,end=19020,half_life=10)['series'][0]
        value=None
        for i in range(19021):
            raw=20 if i==17 else -4 if i==19001 else math.sin(i/25)/5+.8
            value=raw if value is None else (1-2**(-.1))*raw+2**(-.1)*value
        self.assertAlmostEqual(window['trend_points'][-1]['value'],value,places=12)
        self.assertEqual(window['stats']['coordinates'],21)
        self.assertEqual(window['full_range']['coordinates'],20000)

    def test_gaps_conflicts_exact_integers_and_frozen_late_records(self):
        add(self.store,[(0,{'loss':2**60+3}),(1,{'entropy':.4}),(2,{'loss':float('nan')}),
                        (3,{'loss':True}),(4,{'loss':.2}),(5,{'loss':.3})])
        original=q.query(self.store,half_life=10);sid=next(s['id'] for s in original['series'] if s['native_key']=='loss')
        first=q.points(self.store,series_id=sid)['points']
        self.assertEqual(first[0]['value'],2**60+3)
        self.assertEqual([p['status'] for p in first],['recorded','missing','nonfinite','invalid','recorded','recorded'])
        add(self.store,[(4,{'loss':.9})])
        live=q.query(self.store,half_life=10)
        frozen=q.query(self.store,as_of=original['as_of'],half_life=10)
        self.assertEqual(frozen['series'],original['series'])
        changed=next(s for s in live['series'] if s['id']==sid)
        self.assertEqual(changed['points'][4]['status'],'conflicting')
        self.assertEqual(changed['trend_points'][5]['value'],.3)
        self.assertNotEqual(changed['points'][0]['segment'],changed['points'][5]['segment'])
        # Replay does not duplicate index or native records.
        add(self.store,[(4,{'loss':.9})]);self.assertEqual(q.query(self.store)['records'],7)

    def test_catalog_pagination_explicit_series_and_scope(self):
        add(self.store,[(2,{f'metric/{i:03}':i for i in range(100)})])
        add(self.store,[(3,{'loss':9})],clock='generation_batch')
        base=q.query(self.store);self.assertEqual(base['clock'],'learner_update')
        self.assertEqual(base['loaded_series'],64);self.assertEqual(base['total_series'],100)
        catalog=q.catalog(self.store,clock=base['clock'],search='099')
        self.assertEqual(catalog['total_series'],1);sid=catalog['series'][0]['id']
        expanded=q.query(self.store,series_ids=[sid]);self.assertTrue(any(s['id']==sid for s in expanded['series']))
        self.assertEqual(q.catalog(self.store,search='%')['total_series'],0)
        self.assertEqual(q.catalog(self.store,clock=base['clock'],limit=30)['next_offset'],30)
        self.assertEqual(q.query(self.store,clock='generation_batch')['records'],1)

    def test_separate_writers_sessions_definitions_and_empty_ranges(self):
        for fields in ({},{'producer':'worker-2'},{'session':'restart'},{'objective':'other'}):
            add(self.store,[(0,{'loss':.3})],**fields)
        add(self.store,[(1,{'loss':.4})],definitions={'loss':t.metric('Different loss','loss','native','other','Different objective reduction')})
        self.assertEqual(len(q.query(self.store)['series']),5)
        empty=q.query(self.store,start=10,end=20)
        self.assertEqual(empty['records'],0)
        self.assertTrue(all(s['stats']['coordinates']==0 for s in empty['series']))
        self.assertEqual(q.query(self.store,experiment='absent')['series'],[])

    def test_raw_paging_export_replay_and_cli(self):
        add(self.store,((i,{'loss':i/100,'entropy':1}) for i in reversed(range(305))))
        result=q.query(self.store);sid=result['series'][0]['id'];all_points=[];after=None
        while True:
            page=q.points(self.store,series_id=sid,start=10,end=250,after=after,limit=27,as_of=result['as_of'])
            all_points+=page['points'];after=page['next_after']
            if after is None:break
        self.assertEqual([p['step'] for p in all_points],list(range(10,251)))
        cutoff,packets=q.export_records(self.store,start=10,end=250,as_of=result['as_of'])
        replica=Store(self.root/'replica.sqlite');count=0
        for packet in packets:count+=t.receive(replica,packet)['inserted']
        self.assertEqual(count,241);self.assertEqual(q.query(replica)['records'],241)
        args=SimpleNamespace(db=self.store.path,telemetry_command='query',experiment='long-study',environment=None,
                             clock='learner_update',start=10,end=250,as_of=cutoff,max_points=24,half_life=0,series_ids=[])
        self.assertEqual(run(args)['records'],241)
        args.telemetry_command='export';args.destination=str(self.root/'export.jsonl')
        self.assertEqual(run(args)['records'],241)
        self.assertEqual(len(Path(args.destination).read_text().splitlines()),241)
        with self.assertRaises(FileExistsError):run(args)

    def test_validation(self):
        for options in ({'start':float('nan')},{'start':10**400},{'start':5,'end':4},{'as_of':1},{'as_of':True},
                        {'max_points':0},{'half_life':True},{'series_ids':['x']*41}):
            with self.assertRaises(InputError):q.query(self.store,**options)

    def test_incremental_backfill_concurrency_and_omitted_gaps(self):
        add(self.store,((i,{'loss':None if i%17==0 else math.sin(i)}) for i in range(2000)))
        with ThreadPoolExecutor(max_workers=3) as pool:
            snapshots=list(pool.map(lambda n:q.query(self.store,as_of=n,max_points=24,half_life=10),[500,1500,2000]))
        self.assertEqual([s['records'] for s in snapshots],[500,1500,2000])
        s=snapshots[-1]['series'][0]
        self.assertLessEqual(len(s['points']),24)
        for a,b in zip(s['points'],s['points'][1:]):
            if any(i%17==0 for i in range(a['step']+1,b['step']+1)):
                self.assertNotEqual(a['segment'],b['segment'])
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM telemetry_query_records').fetchone()[0],2000)
        add(self.store,[(5,{'loss':10}),(2000,{'loss':.1})])
        self.assertEqual(q.query(self.store)['records'],2002)
        self.assertEqual(q.query(self.store,as_of=500,max_points=24,half_life=10)['series'],snapshots[0]['series'])


class QueryHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_query_inspect_export_and_error(self):
        add(self.store,((i,{'loss':i}) for i in range(300)))
        endpoint=self.start_server()
        def get(path):
            with urlopen(endpoint+'/api/trainer-telemetry/'+path,timeout=20) as response:return json.load(response)
        result=get('query?start=20&end=50&half_life=10');self.assertEqual(result['records'],31)
        sid=result['series'][0]['id']
        self.assertEqual(get('points?series='+sid+'&limit=3')['next_after'],2)
        self.assertEqual(get('catalog?search=loss')['total_series'],1)
        with urlopen(endpoint+'/api/trainer-telemetry/export?start=20&end=50&as_of='+str(result['as_of']),timeout=20) as response:
            self.assertEqual(response.headers['X-Rilldex-As-Of'],str(result['as_of']))
            packets=[json.loads(line) for line in response]
        self.assertEqual([p['records'][0]['step'] for p in packets],list(range(20,51)))
        with self.assertRaises(HTTPError) as err:get('query?start=NaN')
        self.assertEqual(err.exception.code,400)
        large=2**60+3
        add(self.store,[(large,{'loss':.1}),(large+1,{'loss':.2})])
        exact=get('query?start='+str(large)+'&end='+str(large))
        self.assertEqual(exact['records'],1);self.assertEqual(exact['series'][0]['points'][0]['step'],large)


if __name__=='__main__':unittest.main()
