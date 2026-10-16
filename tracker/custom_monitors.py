"""Code-computed measurements published into the ordinary monitor registry.

Only data crosses the HTTP boundary. User callbacks run in their own Python
process, never in the web server. Immutable source/graph/dependency bindings
make restart and duplicate publication safe.
"""
from dataclasses import dataclass
import json
import math
import time
from .schema import InputError, digest, dumps

VERSION='custom-monitor-input/1'


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS custom_monitor_inputs(
        id TEXT PRIMARY KEY,monitor_id TEXT NOT NULL REFERENCES monitors(id),
        run_id TEXT NOT NULL REFERENCES runs(id),basis_hash TEXT NOT NULL,
        document TEXT NOT NULL,created_at TEXT NOT NULL,
        UNIQUE(monitor_id,run_id,basis_hash));
        CREATE INDEX IF NOT EXISTS custom_monitor_lookup ON custom_monitor_inputs(monitor_id,run_id);''')


def text(value,name,limit=4000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise InputError(f'{name} must be nonempty text, at most {limit} characters')
    return value


def json_value(value):
    try:encoded=json.dumps(value,allow_nan=False)
    except (TypeError,ValueError) as error:raise InputError('Custom data must be finite JSON') from error
    if len(encoded.encode('utf-8'))>131072:raise InputError('Custom data exceeds 128 KiB')
    return json.loads(encoded)


def validate(raw):
    if not isinstance(raw,dict) or set(raw)-{'version','description','unit','aggregation','config'}:
        raise InputError('Custom monitor requires version, description, unit, aggregation and optional config')
    result={**raw,'version':text(raw.get('version'),'Version',80),
        'description':text(raw.get('description'),'Description'),'unit':raw.get('unit','value'),
        'aggregation':raw.get('aggregation','mean'),'config':json_value(raw.get('config',{}))}
    if not isinstance(result['config'],dict):raise InputError('Custom config must be a JSON object')
    if result['unit'] not in {'value','fraction'} or result['aggregation'] not in {'mean','opportunity_ratio','incidence'}:
        raise InputError('Use value/fraction units and mean/opportunity_ratio/incidence aggregation')
    if result['aggregation'] in {'opportunity_ratio','incidence'} and result['unit']!='fraction':
        raise InputError('Ratios and incidence use fraction units')
    return result


def definition(store,identifier):
    from .monitoring import definitions
    m=next((m for m in definitions(store) if m['id']==identifier),None)
    if not m or m['kind']!='custom':raise InputError('Select a registered custom monitor')
    return m


def current_inputs(store,monitor,sources,graphs):
    result={}
    with store.connect() as c:
        for row in c.execute('SELECT id,run_id,document FROM custom_monitor_inputs WHERE monitor_id=? ORDER BY rowid',(monitor['id'],)):
            d=json.loads(row['document']);rid=row['run_id']
            if d['source_hash']==sources.get(rid,{}).get('source_hash') and d['graph_id']==graphs.get(rid,{}).get('id'):
                result[rid]={'id':row['id'],'source_hash':d['source_hash'],'result':d['result']}
    return result


def validate_evidence(result,graph):
    ids={node['id'] for node in graph['nodes']}
    ids|={identifier.removeprefix('event:') for identifier in ids if identifier.startswith('event:')}
    if set(result['evidence_ids'])-ids:raise InputError('Evidence IDs do not belong to the selected graph')


def clean_result(raw,spec):
    if not isinstance(raw,dict) or set(raw)-{'value','numerator','denominator','status','reason','evidence_ids','feedback','details','unknown'}:
        raise InputError('Custom result uses value or numerator/denominator, status, reason, evidence_ids, feedback, details and unknown')
    r={'value':None,'numerator':None,'denominator':None,'evidence_ids':[],**json_value(raw)}
    def number(v):return type(v) in {int,float} and math.isfinite(v)
    if spec['aggregation']=='opportunity_ratio':
        n,d=r['numerator'],r['denominator']
        if n is None and d is None and r.get('value') is None:pass
        elif not number(n) or not number(d) or not 0<=n<=d:raise InputError('Ratio requires finite 0 <= numerator <= denominator')
        else:
            value=n/d if d else None
            if 'value' in raw and r['value']!=value:raise InputError('Value differs from numerator / denominator')
            r['value']=value
    elif r['numerator'] is not None or r['denominator'] is not None:raise InputError('Numerator and denominator require opportunity_ratio aggregation')
    if isinstance(r['value'],bool) and spec['aggregation']=='incidence':r['value']=int(r['value'])
    if r['value'] is not None:
        if not number(r['value']):raise InputError('Custom value must be a finite number or null')
        if spec['unit']=='fraction' and not 0<=r['value']<=1:raise InputError('Fraction must be in [0,1]')
        if spec['aggregation']=='incidence' and r['value'] not in {0,1}:raise InputError('Incidence requires 0 or 1')
    r.setdefault('status','available' if r['value'] is not None else 'unavailable')
    if r['status'] not in {'available','unavailable','error'} or (r['status']=='available')!=(r['value'] is not None):
        raise InputError('Available requires a number; unavailable/error require null')
    if r['value'] is None:r['reason']=text(r.get('reason'),'Reason for missing value')
    elif r.get('reason') is not None:text(r['reason'],'Reason')
    if not isinstance(r['evidence_ids'],list) or any(not isinstance(e,str) for e in r['evidence_ids']):raise InputError('Evidence IDs must be a list of strings')
    if 'unknown' in r and (type(r['unknown']) is not int or r['unknown']<0):raise InputError('Unknown opportunities must be a nonnegative integer')
    if 'feedback' in r:
        f=r['feedback']
        if not isinstance(f,dict) or set(f)-{'severity','summary','next_check'} or f.get('severity') not in {'info','warning','critical'}:raise InputError('Feedback requires info/warning/critical severity and summary')
        text(f.get('summary'),'Feedback summary')
        if f.get('next_check') is not None:text(f['next_check'],'Next check')
    return r


def publish(store,body):
    from . import monitoring,graph_store
    if not isinstance(body,dict) or set(body)-{'monitor_id','run_id','source_hash','graph_id','dependencies','result'}:
        raise InputError('Provide monitor_id, run_id, source_hash, graph_id, dependencies and result')
    monitor=definition(store,body.get('monitor_id'))
    run=next((r for r in monitoring.population(store) if r['id']==body.get('run_id')),None)
    if not run or not monitoring.in_population(monitor,run):raise InputError('Rollout is not in this monitor current population')
    if run['state'] in {'in_progress','failed'}:raise InputError('Custom completed-rollout monitor waits for a complete source')
    graphs={g['observer']:g for g in graph_store.catalog(store,run_id=run['id'])['graphs']}
    g=graphs.get(monitor['observer']);source=graphs.get('source')
    if not g or not source or g['source_hash']!=source['source_hash'] or body.get('source_hash')!=source['source_hash'] or body.get('graph_id')!=g['id']:
        raise InputError('Publish against the current source and selected graph; recompute stale inputs')
    result=clean_result(body.get('result'),monitor['custom'])
    if result['evidence_ids']:
        validate_evidence(result,graph_store.read(store,g['id']))
    dependencies=json_value(body.get('dependencies',{}))
    if not isinstance(dependencies,dict):raise InputError('Dependencies must be a JSON object')
    basis=dict(source_hash=source['source_hash'],graph_id=g['id'],dependencies=dependencies)
    basis_hash=digest(basis)
    doc=dict(schema=VERSION,monitor_id=monitor['id'],run_id=run['id'],**basis,result=result)
    identifier='custom-input-'+digest(doc)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT id FROM custom_monitor_inputs WHERE monitor_id=? AND run_id=? AND basis_hash=?',(monitor['id'],run['id'],basis_hash)).fetchone()
        if old and old[0]!=identifier:raise InputError('Conflicting result for the same source, graph and dependencies. Change the code version or explicit dependency revision; existing evidence was retained.')
        c.execute('INSERT OR IGNORE INTO custom_monitor_inputs VALUES (?,?,?,?,?,?)',(identifier,monitor['id'],run['id'],basis_hash,dumps(doc),monitoring.now()))
    return {'id':identifier,'inserted':not bool(old),'monitor_id':monitor['id'],'run_id':run['id']}


@dataclass(frozen=True)
class Context:
    run: dict
    graph: dict
    workspace: object
    config: dict


class CustomMonitor:
    """Arbitrary local Python; immutable published results shared with the UI."""
    def __init__(self,workspace,name,*,version,description,unit='value',aggregation='mean',config=None,group='Behavior'):
        from .store import Store
        from .monitoring import create,validate,definitions
        if workspace.scope['history']:raise InputError('Create monitors from a current workspace, not history=True')
        self.workspace=workspace;self.store=Store(workspace.data.path)
        raw=validate(dict(name=name,kind='custom',observer=workspace.scope['observer'] or 'source',group=group,
            population={k:v for k,v in workspace.scope.items() if k=='experiment' and v is not None},
            custom=dict(version=version,description=description,unit=unit,aggregation=aggregation,config={} if config is None else config)))
        identifier='monitor-'+digest(raw)
        self.definition=next((d for d in definitions(self.store) if d['id']==identifier),None)
        if self.definition is None:self.definition=create(self.store,raw)
        self.id=self.definition['id']

    def publish(self,run_id,*,source_hash,graph_id,result,dependencies=None):
        return publish(self.store,dict(monitor_id=self.id,run_id=run_id,source_hash=source_hash,graph_id=graph_id,result=result,dependencies={} if dependencies is None else dependencies))

    def run(self,function,*,dependencies=None):
        """Backfill current complete rollouts; unchanged inputs are skipped on restart.

        Increment version/config when code semantics change. Include revisions of
        external/cross-rollout inputs in dependencies. No callback runs on UI reads.
        """
        from . import monitoring,graph_store
        if not callable(function):raise InputError('Provide a Python callback')
        dependencies=json_value({} if dependencies is None else dependencies)
        if not isinstance(dependencies,dict):raise InputError('Dependencies must be a JSON object')
        monitor=definition(self.store,self.id)
        counts=dict(published=0,skipped=0,waiting=0,errors=0,paused=not monitor['enabled'])
        if not monitor['enabled']:return counts
        catalog=graph_store.catalog(self.store)
        graphs={(g['run_id'],g['observer']):g for g in catalog['graphs']}
        for row in monitoring.population(self.store):
            if not monitoring.in_population(monitor,row):continue
            g=graphs.get((row['id'],monitor['observer']));source=graphs.get((row['id'],'source'))
            if row['state'] in {'in_progress','failed'} or not g or not source or g['source_hash']!=source['source_hash']:
                counts['waiting']+=1;continue
            basis=digest(dict(source_hash=source['source_hash'],graph_id=g['id'],dependencies=dependencies))
            with self.store.connect() as c:
                old=c.execute('SELECT document FROM custom_monitor_inputs WHERE monitor_id=? AND run_id=? AND basis_hash=?',(self.id,row['id'],basis)).fetchone()
            if old:
                # Failed callbacks are durable too. Retrying needs a new explicit
                # dependency, avoiding conflict with the original error receipt.
                counts['skipped']+=1;continue
            with self.store.connect() as c:
                run=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(row['id'],)).fetchone()[0])
            try:
                graph=graph_store.read(self.store,g['id'])
                value=function(Context(run,graph,self.workspace,json_value(monitor['custom']['config'])))
                value=clean_result(value,monitor['custom'])
                validate_evidence(value,graph)
            except Exception as error:
                value=dict(value=None,status='error',reason=f'{type(error).__name__}: {str(error)[:3000]}');counts['errors']+=1
            try:
                receipt=self.publish(row['id'],source_hash=source['source_hash'],graph_id=g['id'],result=value,dependencies=dependencies)
            except InputError as error:
                # Collection/annotation can advance while the callback runs.
                # Do not publish against a superseded input or stop other runs.
                if str(error).startswith(('Publish against the current source','Rollout is not in this monitor current population')):
                    counts['waiting']+=1;continue
                raise
            counts['published']+=int(receipt['inserted'])
        monitoring.sync(self.store,monitor_ids={self.id})
        return counts

    def follow(self,function,*,interval=5,dependencies=None):
        """Run until Ctrl-C. Restart the same script to backfill and continue."""
        if type(interval) not in {int,float} or not math.isfinite(interval) or interval<.2:raise InputError('Interval must be at least 0.2 seconds')
        try:
            while True:
                self.run(function,dependencies=dependencies)
                time.sleep(interval)
        except KeyboardInterrupt:return
