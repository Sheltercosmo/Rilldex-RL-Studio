"""Code-computed measurements published into the ordinary monitor registry.

Only data crosses the HTTP boundary. User callbacks run in their own Python
process, never in the web server. Immutable source/graph/dependency bindings
make restart and duplicate publication safe.
"""
from dataclasses import dataclass
from copy import deepcopy
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
    if not isinstance(raw,dict) or set(raw)-{'version','description','unit','aggregation','config','evaluations'}:
        raise InputError('Custom monitor requires version, description, unit, aggregation and optional config')
    result={**raw,'version':text(raw.get('version'),'Version',80),
        'description':text(raw.get('description'),'Description'),'unit':raw.get('unit','value'),
        'aggregation':raw.get('aggregation','mean'),'config':json_value(raw.get('config',{}))}
    if not isinstance(result['config'],dict):raise InputError('Custom config must be a JSON object')
    if result['unit'] not in {'value','fraction'} or result['aggregation'] not in {'mean','opportunity_ratio','incidence'}:
        raise InputError('Use value/fraction units and mean/opportunity_ratio/incidence aggregation')
    if result['aggregation'] in {'opportunity_ratio','incidence'} and result['unit']!='fraction':
        raise InputError('Ratios and incidence use fraction units')
    if 'evaluations' in raw:
        from .monitor_evaluation_inputs import validate as validate_evaluations
        result['evaluations']=validate_evaluations(json_value(raw['evaluations']))
    return result


def definition(store,identifier):
    from .monitoring import definitions
    m=next((m for m in definitions(store) if m['id']==identifier),None)
    if not m or m['kind']!='custom':raise InputError('Select a registered custom monitor')
    return m


def current_inputs(store,monitor,sources,graphs):
    from .monitor_evaluation_inputs import capture,KEY
    result={};evaluations={}
    with store.connect() as c:
        for row in c.execute('SELECT id,run_id,document FROM custom_monitor_inputs WHERE monitor_id=? ORDER BY rowid',(monitor['id'],)):
            d=json.loads(row['document']);rid=row['run_id']
            if d['source_hash']==sources.get(rid,{}).get('source_hash') and d['graph_id']==graphs.get(rid,{}).get('id'):
                if monitor['custom'].get('evaluations'):
                    if rid not in evaluations:evaluations[rid]=capture(store,monitor['custom'],rid,d['source_hash'])[0]
                    if d['dependencies'].get(KEY)!=evaluations[rid]:continue
                result[rid]={'id':row['id'],'source_hash':d['source_hash'],'result':d['result']}
    return result


def validate_evidence(result,graph):
    ids={node['id'] for node in graph['nodes']}
    ids|={identifier.removeprefix('event:') for identifier in ids if identifier.startswith('event:')}
    if set(result['evidence_ids'])-ids:raise InputError('Evidence IDs do not belong to the selected graph')


def validate_source_evidence(result,run,spec):
    from .evaluation_receipts import validate_citation, check_citations
    citations=result.get('source_citations',[])
    if not isinstance(citations,list) or len(citations)>32:raise InputError('Attach at most 32 source citations')
    seen=set();source_hash=digest(run)
    for citation in citations:
        validate_citation(citation)
        if citation['run_id']!=run['id'] or citation['source_hash']!=source_hash:
            raise InputError('Custom source citation belongs to another rollout revision')
        key=digest(citation)
        if key in seen:raise InputError('Duplicate custom source citation')
        seen.add(key)
    check_citations(run,result)
    detector=spec.get('config',{}).get('reward_detector')
    if isinstance(detector,dict) and detector.get('schema')=='reward-detector/1':
        from .reward_detectors import checked_inputs
        checked_inputs(run,detector,result)


def clean_result(raw,spec):
    if not isinstance(raw,dict) or set(raw)-{'value','numerator','denominator','status','reason','evidence_ids','source_citations','evaluation_ids','feedback','details','unknown'}:
        raise InputError('Custom result uses value or numerator/denominator, status, reason, evidence_ids, source_citations, evaluation_ids, feedback, details and unknown')
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
    with store.connect() as c:
        document=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(run['id'],)).fetchone()[0])
    validate_source_evidence(result,document,monitor['custom'])
    dependencies=json_value(body.get('dependencies',{}))
    if not isinstance(dependencies,dict):raise InputError('Dependencies must be a JSON object')
    basis=dict(source_hash=source['source_hash'],graph_id=g['id'],dependencies=dependencies)
    basis_hash=digest(basis)
    doc=dict(schema=VERSION,monitor_id=monitor['id'],run_id=run['id'],**basis,result=result)
    identifier='custom-input-'+digest(doc)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        # Pin evaluator selection and publication in one transaction. A verifier
        # arriving during a callback makes that result stale, not current.
        from .store import ReadSnapshot
        from .monitor_evaluation_inputs import capture,pinned,validate_evidence as validate_evaluations,KEY
        saved=ReadSnapshot(store.path,c)
        expected,_=capture(saved,monitor['custom'],run['id'],source['source_hash'])
        if dependencies.get(KEY)!=expected:
            raise InputError('Evaluator inputs changed; recompute against the current report selection')
        selected=pinned(saved,monitor['custom'],run['id'],source['source_hash'],dependencies)
        validate_evaluations(result,selected)
        old=c.execute('SELECT id FROM custom_monitor_inputs WHERE monitor_id=? AND run_id=? AND basis_hash=?',(monitor['id'],run['id'],basis_hash)).fetchone()
        if old and old[0]!=identifier:raise InputError('Conflicting result for the same source, graph and dependencies. Change the code version or explicit dependency revision; existing evidence was retained.')
        c.execute('INSERT OR IGNORE INTO custom_monitor_inputs VALUES (?,?,?,?,?,?)',(identifier,monitor['id'],run['id'],basis_hash,dumps(doc),monitoring.now()))
    return {'id':identifier,'inserted':not bool(old),'monitor_id':monitor['id'],'run_id':run['id']}


def input_snapshot(store,monitor_id,run_id):
    """One current source/graph/evaluator snapshot for an external code worker."""
    from . import monitoring,graph_store
    from .monitor_evaluation_inputs import capture,KEY
    with store.read_snapshot() as saved:
        monitor=definition(saved,monitor_id)
        run=next((r for r in monitoring.population(saved) if r['id']==run_id and monitoring.in_population(monitor,r)),None)
        if not run:raise InputError('Rollout is not in this monitor current population')
        if run['state'] in {'in_progress','failed'}:raise InputError('Custom completed-rollout monitor waits for a complete source')
        graphs={g['observer']:g for g in graph_store.catalog(saved,run_id=run_id)['graphs']}
        source=graphs.get('source');graph=graphs.get(monitor['observer'])
        if not source or not graph or source['source_hash']!=graph['source_hash']:
            raise InputError('Waiting for the selected graph to match this source')
        with saved.connect() as c:document=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(run_id,)).fetchone()[0])
        dependency,evaluations=capture(saved,monitor['custom'],run_id,source['source_hash'])
        return dict(schema='custom-monitor-snapshot/1',monitor_id=monitor_id,run_id=run_id,
            source_hash=source['source_hash'],graph_id=graph['id'],custom=monitor['custom'],
            dependencies={KEY:dependency} if dependency is not None else {},
            run=document,graph=graph_store.read(saved,graph['id']),evaluations=evaluations)


@dataclass(frozen=True)
class Context:
    run: dict
    graph: dict
    workspace: object
    config: dict
    evaluations: dict

    def compare_evaluations(self,left,right):
        from .monitor_evaluation_inputs import compare
        return compare(self.evaluations,left,right)

    def cite(self,event_id,*,role='context',quote=None,start=None,end=None):
        """Quote this exact source snapshot, independently of newer arrivals."""
        from .evaluation_receipts import cite_source
        return cite_source(self.run,event_id,role=role,quote=quote,start=start,end=end)


class CustomMonitor:
    """Arbitrary local Python; immutable published results shared with the UI."""
    def __init__(self,workspace,name,*,version,description,unit='value',aggregation='mean',config=None,group='Behavior',evaluations=None,alert=None):
        from .store import Store
        from .monitoring import create,validate,definitions
        if workspace.scope['history']:raise InputError('Create monitors from a current workspace, not history=True')
        self.workspace=workspace;self.store=Store(workspace.data.path)
        raw=validate(dict(name=name,kind='custom',observer=workspace.scope['observer'] or 'source',group=group,
            **({'alert':alert} if alert is not None else {}),
            population={k:v for k,v in workspace.scope.items() if k=='experiment' and v is not None},
            custom=dict(version=version,description=description,unit=unit,aggregation=aggregation,config={} if config is None else config,
                        **({'evaluations':evaluations} if evaluations is not None else {}))))
        identifier='monitor-'+digest(raw)
        self.definition=next((d for d in definitions(self.store) if d['id']==identifier),None)
        if self.definition is None:self.definition=create(self.store,raw)
        self.id=self.definition['id']

    def publish(self,run_id,*,source_hash,graph_id,result,dependencies=None):
        return publish(self.store,dict(monitor_id=self.id,run_id=run_id,source_hash=source_hash,graph_id=graph_id,result=result,dependencies={} if dependencies is None else dependencies))

    def input_snapshot(self,run_id):
        return input_snapshot(self.store,self.id,run_id)

    def run(self,function,*,dependencies=None):
        """Backfill current complete rollouts; unchanged inputs are skipped on restart.

        Increment version/config when code semantics change. Include revisions of
        external/cross-rollout inputs in dependencies. No callback runs on UI reads.
        """
        from . import monitoring,graph_store
        if not callable(function):raise InputError('Provide a Python callback')
        dependencies=json_value({} if dependencies is None else dependencies)
        if not isinstance(dependencies,dict):raise InputError('Dependencies must be a JSON object')
        from .monitor_evaluation_inputs import capture,validate_evidence as validate_evaluations,KEY
        if KEY in dependencies:raise InputError('rilldex_evaluations is reserved for declared evaluator inputs')
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
            evaluation_input,evaluations=capture(self.store,monitor['custom'],row['id'],source['source_hash'])
            resolved_dependencies=json_value({**dependencies,**({KEY:evaluation_input} if evaluation_input is not None else {})})
            basis=digest(dict(source_hash=source['source_hash'],graph_id=g['id'],dependencies=resolved_dependencies))
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
                # A callback may edit its working objects; validation always
                # uses the original saved source and graph.
                value=function(Context(deepcopy(run),deepcopy(graph),self.workspace,json_value(monitor['custom']['config']),deepcopy(evaluations)))
                value=clean_result(value,monitor['custom'])
                validate_evidence(value,graph)
                validate_source_evidence(value,run,monitor['custom'])
                validate_evaluations(value,evaluations)
            except Exception as error:
                value=dict(value=None,status='error',reason=f'{type(error).__name__}: {str(error)[:3000]}');counts['errors']+=1
            try:
                receipt=self.publish(row['id'],source_hash=source['source_hash'],graph_id=g['id'],result=value,dependencies=resolved_dependencies)
            except InputError as error:
                # Collection/annotation can advance while the callback runs.
                # Do not publish against a superseded input or stop other runs.
                if str(error).startswith(('Publish against the current source','Rollout is not in this monitor current population','Evaluator inputs changed')):
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
