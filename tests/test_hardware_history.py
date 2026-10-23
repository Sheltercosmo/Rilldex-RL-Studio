import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from rilldex import Workspace
from tracker import hardware_history as hh, run_records as rr
from tracker.schema import InputError
from tracker.store import Store


BASE=datetime(2026,10,23,tzinfo=timezone.utc)


def sample(i, *, session='process', host='host', cpu=50, gpus=None, kind='hardware', text=''):
    return dict(id=kind+session+str(i),session=session,kind=kind,observed_at=(BASE+timedelta(seconds=i)).isoformat(),
                payload=dict(host=host,cpu_percent=cpu,memory_used_bytes=2**30,memory_total_bytes=4*2**30,
                             gpus=gpus or [],unavailable=[]) if kind=='hardware' else dict(stream='stderr',text=text))


def insert(store, rows, producer='worker', experiment='training'):
    for offset in range(0,len(rows),100):
        rr.receive(store,dict(schema=rr.VERSION,producer=producer,experiment=experiment,records=rows[offset:offset+100]))


class HardwareHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(Path(self.tmp.name)/'study.sqlite')

    def test_complete_statistics_retain_old_spike_and_sensor_gaps_with_bounded_plot(self):
        rows=[sample(i,cpu=None if 500<=i<530 else 99 if i==3 else 50,
                     gpus=[dict(uuid='gpu',name='Test GPU',utilization_percent=80)] if i<1100 else []) for i in range(1200)]
        insert(self.store,rows[::-1])
        result=hh.query(self.store,experiment='training',points=40)
        group=result['groups'][0];series={s['key']:s for s in group['series']};cpu=series['cpu_percent']
        self.assertEqual(result['total_samples'],1200);self.assertEqual(cpu['maximum']['value'],99)
        self.assertEqual(cpu['maximum']['time'],rows[3]['observed_at']);self.assertEqual(cpu['measured'],1170);self.assertEqual(cpu['missing'],30)
        self.assertAlmostEqual(cpu['mean'],(1169*50+99)/1170)
        self.assertLessEqual(len(cpu['points']),40);self.assertIn(99,[p['value'] for p in cpu['points']])
        self.assertGreater(len({p['segment'] for p in cpu['points']}),1)
        gpu=next(s for s in group['series'] if s['device']=='gpu' and s['label']=='GPU utilization')
        self.assertEqual(gpu['measured'],1100);self.assertEqual(gpu['missing'],100);self.assertIsNone(gpu['latest']['value'])

    def test_interval_logs_cutoff_offsets_and_late_arrivals(self):
        insert(self.store,[sample(1),sample(2),sample(1,kind='console',text='inside'),sample(3,kind='console',text='outside')])
        saved=hh.query(self.store,experiment='training');cutoff=saved['as_of']
        offset=(BASE+timedelta(seconds=1)).astimezone(timezone(timedelta(hours=2))).isoformat()
        args=dict(experiment='training',observed_from=offset,observed_to=sample(2)['observed_at'],as_of=cutoff)
        insert(self.store,[sample(4,cpu=100),dict(sample(1,kind='console',text='late'),id='late')])
        self.assertEqual(hh.query(self.store,experiment='training',as_of=cutoff),saved)
        selected=hh.query(self.store,**args);self.assertEqual(selected['total_samples'],2)
        logs=rr.records(self.store,kind='console',producer='worker',session='process',**args)
        self.assertEqual([r['record']['payload']['text'] for r in logs['rows']],['inside'])
        args.pop('as_of');self.assertEqual(rr.records(self.store,kind='console',**args)['total'],2)

    def test_workers_restarts_hosts_and_paging_stay_separate(self):
        for i in range(8):insert(self.store,[sample(1,session='process-'+str(i),host='machine-'+str(i),cpu=i)],producer='worker')
        insert(self.store,[sample(2,session='process-0',host='moved-host',cpu=100)])
        result=hh.query(self.store,experiment='training',limit=3)
        self.assertEqual(result['group_count'],9);self.assertEqual(result['total_samples'],9);self.assertEqual(len(result['streams']),8)
        self.assertEqual(len(result['groups']),3);self.assertEqual(len(hh.query(self.store,experiment='training',offset=6,limit=3)['groups']),3)
        scoped=hh.query(self.store,experiment='training',session='process-0');self.assertEqual(scoped['group_count'],2)
        self.assertEqual(sorted(g['series'][0]['mean'] for g in scoped['groups']),[0,100])

    def test_duplicate_device_identity_and_absent_sensors_remain_missing(self):
        gpu=dict(uuid='gpu',name='GPU',utilization_percent=80)
        insert(self.store,[sample(1,cpu=None,gpus=[gpu,{**gpu,'utilization_percent':20}]),sample(2,cpu=None)])
        group=hh.query(self.store,experiment='training')['groups'][0]
        self.assertTrue(group['unavailable']);self.assertTrue(all(s['measured']==0 for s in group['series'] if s['device']))
        self.assertIsNone(group['series'][0]['mean']);self.assertEqual(group['series'][0]['points'],[])

    def test_empty_and_invalid_requests_and_python_access(self):
        self.assertEqual(hh.query(self.store,experiment='missing')['full_range'],[None,None])
        insert(self.store,[sample(1)])
        self.assertEqual(Workspace(self.store.path,experiment='training').hardware_history()['total_samples'],1)
        for kwargs in [dict(points=4),dict(limit=21),dict(offset=-1),dict(as_of=True),dict(observed_from='yesterday'),
                       dict(observed_from='2026-10-24T00:00:00Z',observed_to='2026-10-23T00:00:00Z')]:
            with self.subTest(kwargs=kwargs),self.assertRaises(InputError):hh.query(self.store,experiment='training',**kwargs)
        with self.assertRaises(InputError):rr.records(self.store,experiment='training',observed_from='2026-10-23')

    def test_same_instant_and_different_timezones_keep_both_samples(self):
        a=sample(1,cpu=10);b=copy.deepcopy(a);b.update(id='b',observed_at=(BASE+timedelta(seconds=1)).astimezone(timezone(timedelta(hours=-5))).isoformat());b['payload']['cpu_percent']=30
        insert(self.store,[a,b]);sensor=hh.query(self.store,experiment='training')['groups'][0]['series'][0]
        self.assertEqual(sensor['mean'],20);self.assertEqual(len(sensor['points']),2);self.assertEqual(sensor['latest']['value'],30)


if __name__=='__main__':unittest.main()
