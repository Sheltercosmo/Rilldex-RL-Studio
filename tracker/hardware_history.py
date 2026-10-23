"""Full capture history with bounded plots and exact sample statistics."""
import json
from datetime import datetime, timedelta, timezone

from .run_records import _text, timestamp_us, capture_filters
from .schema import InputError

HOST_METRICS=(('cpu_percent','CPU','%'),('memory_used_bytes','RAM used','bytes'),('memory_total_bytes','RAM capacity','bytes'))
GPU_METRICS=(('utilization_percent','GPU utilization','%'),('memory_used_bytes','GPU memory used','bytes'),
             ('memory_total_bytes','GPU memory capacity','bytes'),('temperature_c','Temperature','°C'),('power_watts','Power','W'))


def iso(us):
    return (datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(microseconds=us)).isoformat()


class Series:
    def __init__(self, key, label, unit, device, name, lo, hi, buckets):
        self.key,self.label,self.unit,self.device,self.name=key,label,unit,device,name
        self.lo,self.width,self.buckets=lo,max(1,hi-lo+1),buckets
        self.bins={};self.segment=0;self.count=0;self.total=0;self.low=self.high=None;self.latest=None

    def add(self, time, sequence, value):
        self.latest=dict(time=iso(time),sequence=sequence,value=value)
        if value is None:
            self.segment+=1;return
        point=dict(time=iso(time),sequence=sequence,value=value,segment=self.segment)
        self.count+=1;self.total+=(value-self.total)/self.count
        if self.low is None or value<self.low['value']:self.low=point
        if self.high is None or value>self.high['value']:self.high=point
        bucket=min(self.buckets-1,(time-self.lo)*self.buckets//self.width)
        if bucket not in self.bins:self.bins[bucket]=[point,point,point,point]
        else:
            cell=self.bins[bucket];cell[3]=point
            if value<cell[1]['value']:cell[1]=point
            if value>cell[2]['value']:cell[2]=point

    def result(self, samples):
        retained={p['sequence']:p for cell in self.bins.values() for p in cell}
        return dict(key=self.key,label=self.label,unit=self.unit,device=self.device,device_name=self.name,
                    measured=self.count,missing=samples-self.count,latest=self.latest,
                    minimum=self.low,maximum=self.high,mean=self.total if self.count else None,
                    points=sorted(retained.values(),key=lambda p:(p['time'],p['sequence'])))


def query(store, *, experiment, producer=None, session=None, observed_from=None, observed_to=None,
          as_of=None, points=160, offset=0, limit=6):
    _text(experiment,'experiment')
    bounds=capture_filters(observed_from,observed_to,as_of)
    if type(points) is not int or not 12<=points<=1000:raise InputError('Use 12–1000 plot points per sensor')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=20:raise InputError('Use a nonnegative group offset and limit 1–20')
    where="experiment=? AND kind='hardware'";args=[experiment]
    for column,value in (('producer',producer),('session',session)):
        if value is not None:_text(value,column);where+=' AND '+column+'=?';args.append(value)
    with store.connect() as c:
        c.create_function('capture_time',1,timestamp_us,deterministic=True);c.execute('BEGIN')
        cutoff=c.execute('SELECT COALESCE(MAX(sequence),0) FROM run_records WHERE experiment=?',(experiment,)).fetchone()[0]
        if as_of is not None:cutoff=min(cutoff,as_of)
        where+=' AND sequence<=?';args.append(cutoff)
        inventory=[dict(r) for r in c.execute("SELECT producer,session,count(*) samples FROM run_records WHERE experiment=? AND kind='hardware' AND sequence<=? GROUP BY producer,session ORDER BY MIN(sequence)",(experiment,cutoff))]
        full=c.execute('SELECT MIN(capture_time(observed_at)),MAX(capture_time(observed_at)) FROM run_records WHERE '+where,args).fetchone()
        for comparison,value in zip(('>=','<='),bounds):
            if value is not None:where+=' AND capture_time(observed_at)'+comparison+'?';args.append(value)
        groups=[dict(r) for r in c.execute("SELECT producer,session,json_extract(document,'$.payload.host') host,count(*) samples, MIN(capture_time(observed_at)) first,MAX(capture_time(observed_at)) last FROM run_records WHERE "+where+" GROUP BY producer,session,host ORDER BY producer,session,host",args)]
        total=sum(g['samples'] for g in groups);results=[]
        for group in groups[offset:offset+limit]:
            series={};unavailable=set();seen=0
            def ensure(key,label,unit,device=None,name=None):
                if key not in series:series[key]=Series(key,label,unit,device,name,group['first'],group['last'],points//4)
            for key,label,unit in HOST_METRICS:ensure(key,label,unit)
            sql="SELECT sequence,capture_time(observed_at) time,document FROM run_records WHERE "+where+" AND producer=? AND session=? AND json_extract(document,'$.payload.host')=? ORDER BY time,sequence"
            for r in c.execute(sql,args+[group['producer'],group['session'],group['host']]):
                payload=json.loads(r['document'])['payload'];values={key:payload.get(key) for key,_,_ in HOST_METRICS}
                devices={};duplicates=set()
                for gpu in payload.get('gpus',[]):
                    if gpu['uuid'] in devices:duplicates.add(gpu['uuid'])
                    devices[gpu['uuid']]=gpu
                for device,gpu in devices.items():
                    for key,label,unit in GPU_METRICS:
                        address=json.dumps([device,key]);ensure(address,label,unit,device,gpu['name'])
                        values[address]=None if device in duplicates else gpu.get(key)
                for key,sensor in series.items():sensor.add(r['time'],r['sequence'],values.get(key))
                unavailable.update(payload.get('unavailable',[]));seen+=1
                if duplicates:unavailable.add('Duplicate GPU identities in a sample; those sensor values are unavailable.')
            results.append(dict(producer=group['producer'],session=group['session'],host=group['host'],samples=seen,
                                start=iso(group['first']),end=iso(group['last']),unavailable=sorted(unavailable),
                                series=[sensor.result(seen) for sensor in series.values()]))
    return dict(schema='hardware-history/1',experiment=experiment,as_of=cutoff,streams=inventory,groups=results,
                group_count=len(groups),offset=offset,limit=limit,total_samples=total,
                full_range=[iso(t) if t is not None else None for t in full],
                range=[observed_from,observed_to],plot_points=points,
                boundary='Machine samples, not per-job allocation. Statistics use every captured sample in the selected interval. Means are sample-weighted; lines omit recorded sensor gaps. Worker clocks are not synchronized by this view.')
