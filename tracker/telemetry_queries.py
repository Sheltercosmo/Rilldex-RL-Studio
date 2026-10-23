"""Full-run telemetry queries over an incremental, rebuildable scalar index.

Native records remain authoritative. Plots retain actual first/last/extreme
points, while statistics and EMA use every coordinate before plot reduction.
Extrema selection follows the M4 idea (https://www.vldb.org/pvldb/vol7/p797-jugel.pdf),
with additional EMA extrema and gap segments; this is not pixel-exact M4 rendering.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math

from .schema import InputError, digest, dumps

VERSION = 'telemetry-query/1'
CONTEXT = ('session','clock','split','framework','framework_version','objective','population','environment','mapping')
PRIORITY = ('reward','mismatch','clipping','entropy','throughput','gradients','loss','kl','tokens','systems','other')


def initialize(c):
    c.executescript('''
      CREATE TABLE IF NOT EXISTS telemetry_query_streams (
        id TEXT PRIMARY KEY, context TEXT NOT NULL, experiment TEXT NOT NULL,
        environment TEXT NOT NULL, clock TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS telemetry_query_scope ON telemetry_query_streams(experiment,environment,clock);
      CREATE TABLE IF NOT EXISTS telemetry_query_series (
        id TEXT PRIMARY KEY, stream_id TEXT NOT NULL, native_key TEXT NOT NULL,
        definition TEXT NOT NULL, metric_group TEXT NOT NULL, first_row INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS telemetry_query_stream ON telemetry_query_series(stream_id);
      CREATE TABLE IF NOT EXISTS telemetry_query_records (
        source_row INTEGER PRIMARY KEY, stream_id TEXT NOT NULL, step INTEGER NOT NULL,
        record_id TEXT NOT NULL, received_at TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS telemetry_query_coordinate ON telemetry_query_records(stream_id,step,source_row);
      CREATE INDEX IF NOT EXISTS telemetry_query_receipt ON telemetry_query_records(stream_id,source_row);
      CREATE INDEX IF NOT EXISTS telemetry_query_session ON telemetry_query_streams(
        experiment,clock,json_extract(context,'$.producer'),json_extract(context,'$.session'));
      CREATE TABLE IF NOT EXISTS telemetry_query_values (
        series_id TEXT NOT NULL, source_row INTEGER NOT NULL, value TEXT, status TEXT NOT NULL,
        PRIMARY KEY(series_id,source_row));
      CREATE TABLE IF NOT EXISTS telemetry_query_cursor (id INTEGER PRIMARY KEY CHECK(id=1), source_row INTEGER NOT NULL);
      INSERT OR IGNORE INTO telemetry_query_cursor VALUES (1,0);
    ''')


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise InputError(f'{name} must be an integer from {low} to {high}')
    return value


def _range(start, end):
    for name,value in (('start',start),('end',end)):
        if value is not None and (type(value) not in (int,float) or value<0 or value>=2**63 or not math.isfinite(value)):
            raise InputError(name+' must be a finite nonnegative step')
    if start is not None and end is not None and start>end:
        raise InputError('end must follow start')


def ensure_index(store, as_of=None):
    """Catch up to a fixed source high-water mark; ongoing writers cannot extend it."""
    with store.connect() as c:
        maximum = c.execute('SELECT COALESCE(MAX(rowid),0) FROM trainer_telemetry').fetchone()[0]
    cutoff = maximum if as_of is None else _integer(as_of,'as_of',0,maximum)
    while True:
        with store.connect() as c:
            cursor = c.execute('SELECT source_row FROM telemetry_query_cursor WHERE id=1').fetchone()[0]
            rows = c.execute('SELECT rowid AS source_row,* FROM trainer_telemetry WHERE rowid>? AND rowid<=? ORDER BY rowid LIMIT 1000',
                             (cursor,cutoff)).fetchall()
        if not rows:
            return cutoff
        streams, series, records, values = {}, {}, [], []
        for row in rows:
            r=json.loads(row['document'])
            context={k:r[k] for k in CONTEXT}
            context.update(producer=row['producer'],experiment=row['experiment'])
            context_key=dumps(context);stream='telemetry-stream-'+digest(context_key)
            streams[stream]=(stream,context_key,row['experiment'],r['environment'],r['clock'])
            records.append((row['source_row'],stream,r['step'],r['id'],row['received_at']))
            for key,m in r['metrics'].items():
                definition=dumps({k:v for k,v in m.items() if k not in ('value','status')})
                sid='telemetry-'+digest([context_key,key,definition])
                series.setdefault(sid,(sid,stream,key,definition,m['group'],row['source_row']))
                values.append((sid,row['source_row'],dumps(m['value']),m['status']))
        with store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.executemany('INSERT OR IGNORE INTO telemetry_query_streams VALUES (?,?,?,?,?)',streams.values())
            c.executemany('INSERT OR IGNORE INTO telemetry_query_series VALUES (?,?,?,?,?,?)',series.values())
            c.executemany('INSERT OR IGNORE INTO telemetry_query_records VALUES (?,?,?,?,?)',records)
            c.executemany('INSERT OR IGNORE INTO telemetry_query_values VALUES (?,?,?,?)',values)
            c.execute('UPDATE telemetry_query_cursor SET source_row=MAX(source_row,?) WHERE id=1',(rows[-1]['source_row'],))


def _scope(experiment=None, environment=None, clock=None, producer=None, session=None):
    clauses=[];args=[]
    for key,value in (('experiment',experiment),('environment',environment),('clock',clock),('producer',producer),('session',session)):
        if value=='' and key not in ('producer','session'):continue
        if value is not None:
            if not isinstance(value,str) or not value or len(value)>1000:raise InputError('Invalid '+key)
            field="json_extract(s.context,'$."+key+"')" if key in ('producer','session') else 's.'+key
            clauses.append(field+'=?');args.append(value)
    return (' AND '.join(clauses) or '1'), args


def _sessions(c,where,args,cutoff,*,search='',limit=20,offset=0,producer=None,session=None):
    """Inventory is independent of metric/page limits and interval selection."""
    if not isinstance(search,str) or len(search)>200:raise InputError('Session search must be at most 200 characters')
    _integer(limit,'limit',1,200);_integer(offset,'offset',0,1_000_000)
    sql='''WITH inventory AS (
      SELECT s.experiment,s.clock,json_extract(s.context,'$.producer') producer,json_extract(s.context,'$.session') session,
        MIN(r.source_row) first_received_record,MAX(r.source_row) last_received_record,
        MIN(r.received_at) first_received_at,MAX(r.received_at) last_received_at,
        MIN(r.step) start,MAX(r.step) end,COUNT(*) records
      FROM telemetry_query_streams s JOIN telemetry_query_records r ON r.stream_id=s.id
      WHERE '''+where+''' AND r.source_row<=?
      GROUP BY s.experiment,s.clock,producer,session), numbered AS (
        SELECT *,ROW_NUMBER() OVER(ORDER BY first_received_record,experiment,clock,producer,session) ordinal FROM inventory)
      SELECT * FROM numbered WHERE 1=1'''
    values=args+[cutoff]
    for key,value in (('producer',producer),('session',session)):
        if value is not None:sql+=' AND '+key+'=?';values.append(value)
    if search:
        sql+=" AND (instr(lower(producer),lower(?)) OR instr(lower(session),lower(?)) OR instr(lower('Session '||ordinal),lower(?)))"
        values += [search]*3
    total=c.execute('SELECT COUNT(*) FROM ('+sql+')',values).fetchone()[0]
    rows=[dict(r) for r in c.execute(sql+' ORDER BY first_received_record DESC LIMIT ? OFFSET ?',values+[limit,offset])]
    return dict(rows=rows,total=total,offset=offset,next_offset=offset+len(rows) if offset+len(rows)<total else None)


def sessions(store,*,experiment=None,environment=None,clock=None,search='',limit=50,offset=0,as_of=None):
    cutoff=ensure_index(store,as_of);where,args=_scope(experiment,environment,clock)
    with store.connect() as c:result=_sessions(c,where,args,cutoff,search=search,limit=limit,offset=offset)
    return dict(schema=VERSION,as_of=cutoff,**result)


def _select(c,experiment,environment,clock,producer,session,mode,cutoff):
    if mode not in ('all','latest'):raise InputError('session_mode must be all or latest')
    if mode=='latest' and session is not None:raise InputError('Choose either latest session or an exact session')
    where,args=_scope(experiment,environment,clock,producer,session)
    base,values=_scope(experiment,environment,clock)
    inventory=_sessions(c,base,values,cutoff)
    matching=_sessions(c,base,values,cutoff,producer=producer,session=session,limit=2) if producer is not None or session is not None else inventory
    selected=None
    if mode=='latest':
        selected=matching['rows'][0] if matching['rows'] else None
        if selected:
            where,args=_scope(selected['experiment'],environment,selected['clock'],selected['producer'],selected['session'])
        else:where+=' AND 0'
    elif matching['total']==1 and (producer is not None or session is not None):selected=matching['rows'][0]
    return where,args,dict(mode=mode,producer=producer,session=session,selected=selected),inventory


def _clock(c,where,args,cutoff,clock):
    clocks=[r[0] for r in c.execute('''SELECT DISTINCT s.clock FROM telemetry_query_streams s
        JOIN telemetry_query_records r ON r.stream_id=s.id WHERE '''+where+' AND r.source_row<=? ORDER BY s.clock',args+[cutoff])]
    return clock or ('learner_update' if 'learner_update' in clocks else clocks[0] if clocks else None),clocks


def _descriptor(row):
    return dict(id=row['id'],stream_id=row['stream_id'],native_key=row['native_key'],
                context=json.loads(row['context']),**json.loads(row['definition']))


def catalog(store, *, experiment=None, environment=None, clock=None, producer=None,session=None,session_mode='all',search='', group=None, limit=100, offset=0, as_of=None):
    _integer(limit,'limit',1,200);_integer(offset,'offset',0,1_000_000)
    if not isinstance(search,str) or len(search)>200:raise InputError('search must contain at most 200 characters')
    cutoff=ensure_index(store,as_of)
    with store.connect() as c:
        where,args=_scope(experiment,environment,clock,producer,session)
        if session_mode=='latest':clock,_=_clock(c,where,args,cutoff,clock)
        where,args,selection,_=_select(c,experiment,environment,clock,producer,session,session_mode,cutoff)
        where+=' AND m.first_row<=?';args.append(cutoff)
        if search:
            where+=" AND (instr(lower(m.native_key),lower(?)) OR instr(lower(json_extract(m.definition,'$.label')),lower(?)))"
            args.extend([search,search])
        if group:where+=' AND m.metric_group=?';args.append(group)
        base='FROM telemetry_query_series m JOIN telemetry_query_streams s ON s.id=m.stream_id WHERE '+where
        total=c.execute('SELECT count(*) '+base,args).fetchone()[0]
        rows=c.execute('SELECT m.*,s.context '+base+' ORDER BY m.metric_group,m.native_key,m.id LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    return dict(schema=VERSION,as_of=cutoff,session_selection=selection,total_series=total,series=[_descriptor(r) for r in rows],
                offset=offset,next_offset=offset+len(rows) if offset+len(rows)<total else None)


def _points(c, series, cutoff, *, start=None, end=None, after=None, limit=None):
    where=['r.stream_id=?','r.source_row<=?'];args=[series['id'],series['stream_id'],cutoff]
    for op,value in (('>=',start),('<=',end),('>',after)):
        if value is not None:where.append('r.step'+op+'?');args.append(value)
    query='''SELECT r.step,COUNT(v.source_row) AS n,MIN(v.value) AS value,MIN(v.status) AS status,
        json_group_array(r.record_id) FILTER (WHERE v.source_row IS NOT NULL) AS record_ids
        FROM telemetry_query_records r LEFT JOIN telemetry_query_values v ON v.source_row=r.source_row AND v.series_id=?
        WHERE '''+' AND '.join(where)+' GROUP BY r.step ORDER BY r.step'
    if limit is not None:query+=' LIMIT ?';args.append(limit)
    for row in c.execute(query,args):
        status='missing' if row['n']==0 else 'conflicting' if row['n']>1 else row['status']
        ids=json.loads(row['record_ids'])
        yield dict(step=row['step'],status=status,value=json.loads(row['value']) if status=='recorded' else None,
                   record_ids=ids[:32],record_count=row['n'],omitted_record_ids=max(0,len(ids)-32))


def _stream_bounds(c, stream, cutoff):
    r=c.execute('SELECT MIN(step),MAX(step),COUNT(DISTINCT step),COUNT(*),MIN(source_row) FROM telemetry_query_records WHERE stream_id=? AND source_row<=?',
                (stream,cutoff)).fetchone()
    return dict(start=r[0],end=r[1],coordinates=r[2],records=r[3],first_received_record=r[4])


class _Bucket:
    def __init__(self):
        self.first=self.last=self.low=self.high=self.trend_low=self.trend_high=self.last_gap=None
        self.gaps={}

    def add(self,p):
        if self.first is None:self.first=p
        self.last=p
        if p['value'] is None:
            self.gaps.setdefault(p['status'],p);self.last_gap=p
            return
        if self.low is None or p['value']<self.low['value']:self.low=p
        if self.high is None or p['value']>self.high['value']:self.high=p
        if self.trend_low is None or p['ema']<self.trend_low['ema']:self.trend_low=p
        if self.trend_high is None or p['ema']>self.trend_high['ema']:self.trend_high=p

    def points(self):
        values=[self.first,self.last,self.low,self.high,self.trend_low,self.trend_high,self.last_gap,*self.gaps.values()]
        return {p['step']:p for p in values if p is not None}


def _plot(c, series, cutoff, start, end, budget, half_life):
    full=_stream_bounds(c,series['stream_id'],cutoff)
    lo=full['start'] if start is None else start
    hi=full['end'] if end is None else end
    buckets=[_Bucket() for _ in range(max(1,budget//12))]
    exact=[];counts=Counter();first=last=minimum=maximum=None;ema=None;last_step=None;segment=0;was_valid=False
    for p in _points(c,series,cutoff,end=end):
        if p['value'] is None:
            if was_valid:segment+=1
            ema=None;last_step=None;was_valid=False
        else:
            alpha=-math.expm1(-math.log(2)*(p['step']-last_step)/half_life) if half_life and last_step is not None else 1
            ema=p['value'] if ema is None else alpha*p['value']+(1-alpha)*ema
            last_step=p['step'];was_valid=True
        p.update(ema=ema,segment=segment)
        if lo is None or not lo<=p['step']<=hi:continue
        counts[p['status']]+=1
        if len(exact)<=budget:exact.append(p)
        if p['value'] is not None:
            first=first or p;last=p
            if minimum is None or p['value']<minimum['value']:minimum=p
            if maximum is None or p['value']>maximum['value']:maximum=p
        slot=min(len(buckets)-1,int((p['step']-lo)/(hi-lo or 1)*len(buckets)))
        buckets[slot].add(p)
    selected={p['step']:p for b in buckets for p in b.points().values()}
    points=exact if sum(counts.values())<=budget else [selected[k] for k in sorted(selected)]
    clean=lambda p: {k:v for k,v in p.items() if k!='ema'} if p else None
    stats=dict(coordinates=sum(counts.values()),recorded=counts['recorded'],status_counts=dict(counts),
               first=clean(first),last=clean(last),minimum=clean(minimum),maximum=clean(maximum),
               delta=last['value']-first['value'] if first and last and first is not last else None)
    return {**series,'points':[clean(p) for p in points],
            'trend_points':[{**clean(p),'value':p['ema']} for p in points] if half_life else [],
            'stats':stats,'recorded':stats['recorded'],'coordinates':stats['coordinates'],'full_range':full,
            'representation':{'method':'first_last_extrema','points':len(points),'source_coordinates':stats['coordinates'],
                              'reduced':len(points)<stats['coordinates'],'max_points':budget,
                              'half_life':half_life,'ema_basis':'all coordinates before interval selection',
                              'gap_policy':'Segments break across every unavailable coordinate; representatives retain each observed gap status per bucket.'}}


def query(store, *, experiment=None, environment=None, clock=None, start=None, end=None,
          max_points=240, half_life=0, series_ids=(), as_of=None,producer=None,session=None,session_mode='all'):
    _range(start,end);_integer(max_points,'max_points',24,2000)
    if half_life not in (0,10,50,100) or isinstance(half_life,bool):raise InputError('half_life must be 0, 10, 50 or 100')
    if not isinstance(series_ids,(list,tuple)) or len(series_ids)>40 or any(not isinstance(s,str) or len(s)>100 for s in series_ids):
        raise InputError('Supply at most 40 metric series identifiers')
    cutoff=ensure_index(store,as_of);where,args=_scope(experiment,environment,producer=producer,session=session)
    with store.connect() as c:
        selected_clock,clocks=_clock(c,where,args,cutoff,clock)
        where,args,selection,inventory=_select(c,experiment,environment,selected_clock,producer,session,session_mode,cutoff)
        counts_sql='FROM telemetry_query_records r JOIN telemetry_query_streams s ON s.id=r.stream_id WHERE '+where+' AND r.source_row<=?'
        total=c.execute('SELECT count(*) '+counts_sql,args+[cutoff]).fetchone()[0]
        window_sql=counts_sql;window_args=args+[cutoff]
        if start is not None:window_sql+=' AND r.step>=?';window_args.append(start)
        if end is not None:window_sql+=' AND r.step<=?';window_args.append(end)
        records=c.execute('SELECT count(*) '+window_sql,window_args).fetchone()[0]
        catalog_sql='FROM telemetry_query_series m JOIN telemetry_query_streams s ON s.id=m.stream_id WHERE '+where+' AND m.first_row<=?'
        available=c.execute('SELECT m.metric_group,count(*) '+catalog_sql+' GROUP BY m.metric_group',args+[cutoff]).fetchall()
        # Each metric family gets a visible default before additional definitions.
        ranked='SELECT m.*,s.context,ROW_NUMBER() OVER(PARTITION BY m.metric_group ORDER BY m.native_key,m.id) AS family_position '+catalog_sql
        order='CASE metric_group '+' '.join(f"WHEN '{g}' THEN {i}" for i,g in enumerate(PRIORITY))+' END'
        rows=c.execute('SELECT * FROM ('+ranked+') ORDER BY family_position,'+order+',native_key,id LIMIT 64',args+[cutoff]).fetchall()
        known={r['id'] for r in rows}
        extra=[s for s in dict.fromkeys(series_ids) if s not in known]
        if extra:
            rows+=c.execute('SELECT m.*,s.context '+catalog_sql+' AND m.id IN ('+','.join('?' for _ in extra)+')',args+[cutoff]+extra).fetchall()
        series=[_plot(c,_descriptor(row),cutoff,start,end,max_points,half_life) for row in rows]
    return dict(schema=VERSION,as_of=cutoff,captured_at=datetime.now(timezone.utc).isoformat(),
                experiment=experiment,environment=environment,clock=selected_clock,clocks=clocks,
                range=[start,end],records=records,total_records=total,series=series,
                session_selection=selection,session_inventory=inventory,
                total_series=sum(r[1] for r in available),loaded_series=len(series),
                available_groups={r[0]:r[1] for r in available},
                representation='Full native record range; bounded plot representatives. Statistics and EMA use all coordinates.',
                boundary='Separate writers, sessions, definitions and clocks remain separate series. No cross-writer averaging or inferred health thresholds.')


def points(store, *, series_id, as_of=None, start=None, end=None, after=None, limit=100):
    _range(start,end);_integer(limit,'limit',1,1000)
    if after is not None:_range(after,None)
    cutoff=ensure_index(store,as_of)
    with store.connect() as c:
        row=c.execute('''SELECT m.*,s.context FROM telemetry_query_series m JOIN telemetry_query_streams s ON s.id=m.stream_id
                        WHERE m.id=? AND m.first_row<=?''',(series_id,cutoff)).fetchone()
        if row is None:raise InputError('Metric series is not present in this snapshot')
        series=_descriptor(row)
        values=list(_points(c,series,cutoff,start=start,end=end,after=after,limit=limit+1))
    return dict(schema=VERSION,as_of=cutoff,series=series,points=values[:limit],
                next_after=values[limit-1]['step'] if len(values)>limit else None)


def selected_records(store, *, series_id, as_of, start=None, end=None, limit=10000):
    """Read every original record containing this exact metric definition.

    Call ensure_index on the writable store before entering a read snapshot.
    Plot representatives and their bounded record_ids never define a cohort.
    """
    _range(start, end); _integer(limit, 'limit', 1, 10000)
    with store.connect() as c:
        maximum = c.execute('SELECT COALESCE(MAX(rowid),0) FROM trainer_telemetry').fetchone()[0]
        _integer(as_of, 'as_of', 0, maximum)
        row = c.execute('''SELECT m.*,s.context FROM telemetry_query_series m
            JOIN telemetry_query_streams s ON s.id=m.stream_id WHERE m.id=? AND m.first_row<=?''',
            (series_id, as_of)).fetchone()
        if row is None: raise InputError('Metric series is not present in this snapshot')
        series = _descriptor(row)
        coordinates = list(_points(c, series, as_of, start=start, end=end, limit=limit+1))
        clauses = ['v.series_id=?', 'r.source_row<=?']; args = [series_id, as_of]
        for op, value in (('>=', start), ('<=', end)):
            if value is not None: clauses.append('r.step'+op+'?'); args.append(value)
        rows = c.execute('''SELECT t.* FROM telemetry_query_values v
            JOIN telemetry_query_records r ON r.source_row=v.source_row
            JOIN trainer_telemetry t ON t.rowid=r.source_row WHERE '''+' AND '.join(clauses)+
            ' ORDER BY r.step,r.source_row LIMIT ?', args+[limit+1]).fetchall()
    if len(rows)>limit or len(coordinates)>limit:
        raise InputError('Narrow each interval to at most 10,000 native records and coordinates')
    return dict(series=series, as_of=as_of, rows=rows,
                coordinates=dict(Counter(p['status'] for p in coordinates)))


def export_records(store, *, experiment=None, environment=None, clock=None, start=None, end=None, as_of=None,producer=None,session=None,session_mode='all'):
    """Return a frozen cutoff and a streaming iterator of replayable native packets."""
    from .trainer_telemetry import VERSION as NATIVE, LINKED_VERSION
    _range(start,end);cutoff=ensure_index(store,as_of)
    with store.connect() as c:
        where,args=_scope(experiment,environment,clock,producer,session)
        if session_mode=='latest':clock,_=_clock(c,where,args,cutoff,clock)
        where,args,_,_=_select(c,experiment,environment,clock,producer,session,session_mode,cutoff)
    where+=' AND r.source_row<=?';args.append(cutoff)
    if start is not None:where+=' AND r.step>=?';args.append(start)
    if end is not None:where+=' AND r.step<=?';args.append(end)
    def records():
        with store.connect() as c:
            # The source is append-only and the cutoff excludes later arrivals.
            for row in c.execute('''SELECT t.* FROM telemetry_query_records r JOIN telemetry_query_streams s ON s.id=r.stream_id
                                    JOIN trainer_telemetry t ON t.rowid=r.source_row WHERE '''+where+' ORDER BY r.source_row',args):
                record=json.loads(row['document'])
                yield dict(schema=LINKED_VERSION if 'training_uses' in record else NATIVE,
                           producer=row['producer'],experiment=row['experiment'],records=[record])
    return cutoff,records()
