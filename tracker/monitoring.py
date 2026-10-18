"""Persistent population monitors and incremental per-rollout materialization.

This service consumes saved observations; it does not initiate paid inference.
Definitions and values are immutable. Enabled state and a rebuildable latest
index are mutable; previous values remain auditable after graph revisions.
"""
import json
import math
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from .schema import InputError, digest, dumps
from . import graph_store, graph_queries, analysis_metrics
from .rollout_metrics import DEFINITIONS, VERSION as METRIC_VERSION, metric_aggregation

VERSION='population-monitor/1'
GRAPH_MONITOR_VERSION='recorded-relation-monitor/2'


def now():return datetime.now(timezone.utc).isoformat()


def initialize(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS monitors(id TEXT PRIMARY KEY,document TEXT NOT NULL,enabled INTEGER NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS monitor_values(id TEXT PRIMARY KEY,monitor_id TEXT NOT NULL REFERENCES monitors(id),run_id TEXT NOT NULL REFERENCES runs(id),input_hash TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(monitor_id,run_id,input_hash));
    CREATE INDEX IF NOT EXISTS monitor_value_lookup ON monitor_values(monitor_id,run_id,created_at);
    CREATE TABLE IF NOT EXISTS monitor_latest(monitor_id TEXT NOT NULL REFERENCES monitors(id),run_id TEXT NOT NULL REFERENCES runs(id),value_id TEXT NOT NULL REFERENCES monitor_values(id),PRIMARY KEY(monitor_id,run_id));
    CREATE TABLE IF NOT EXISTS monitor_service(id TEXT PRIMARY KEY,document TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS monitor_comparisons(id TEXT PRIMARY KEY,document TEXT NOT NULL,created_at TEXT NOT NULL);
    ''')
    from .custom_monitors import initialize as initialize_custom
    initialize_custom(c)


def validate(raw):
    if not isinstance(raw,dict):raise InputError('Monitor must be an object')
    allowed={'schema','name','kind','observer','metric','requirement','group','analysis','analysis_definition','population','custom'}
    if set(raw)-allowed:raise InputError('Unknown monitor fields')
    d={**raw,'schema':VERSION}
    if raw.get('schema',VERSION)!=VERSION:raise InputError('Unsupported monitor schema')
    for k in ('name','observer'):
        if not isinstance(d.get(k),str) or not d[k].strip() or len(d[k])>200:raise InputError('Provide '+k)
    if d.get('group','Behavior') not in {'Training','Behavior','Reward integrity'}:raise InputError('Unknown monitor group')
    d.setdefault('group','Behavior')
    if 'population' in d:
        scope=d['population']
        if (not isinstance(scope,dict) or set(scope)-{'experiment','environment','split'} or
                any(not isinstance(v,str) or not v.strip() or len(v)>240 for v in scope.values())):
            raise InputError('Population uses nonempty exact experiment, environment or split values')
        if scope:d['population']=dict(scope)
        else:d.pop('population')  # Empty scope preserves the legacy definition identity.
    if d.get('kind')!='analysis' and ('analysis' in d or 'analysis_definition' in d):raise InputError('Analysis settings require an analysis monitor')
    if d.get('kind')!='custom' and 'custom' in d:raise InputError('Custom settings require a custom monitor')
    if d.get('kind')=='metric':
        if not isinstance(d.get('metric'),str) or d['metric'] not in DEFINITIONS or 'requirement' in d:raise InputError('Select a recorded metric')
        from .feedback_assessment import protocol,LEGACY
        if d['observer']==protocol(LEGACY)['id'] and d['metric'].startswith('feedback_assessment_'):
            raise InputError('Feedback v1 missed explicit success assessments and is retained for audit only; use a reviewed later observer')
    elif d.get('kind')=='graph':
        if 'metric' in d:raise InputError('Graph monitors use a requirement')
        d['requirement']=graph_queries.validate(d.get('requirement'))
    elif d.get('kind')=='analysis':
        if 'metric' in d or 'requirement' in d:raise InputError('Analysis monitors use a versioned measure')
        d['analysis']=analysis_metrics.validate(d.get('analysis'))
        spec=analysis_metrics.definition(d['analysis'])
        if 'analysis_definition' in d and d['analysis_definition']!=spec:raise InputError('Analysis definition differs from selected measure')
        d['analysis_definition']=spec
        from .analysis_contracts import registered
        contract=registered()[spec['operation']]['observer_input']
        if ('source' if d['observer']=='source' else 'observed') not in contract['accepted']:
            raise InputError(contract['guidance'])
    elif d.get('kind')=='custom':
        if 'metric' in d or 'requirement' in d:raise InputError('Custom monitors use a custom definition')
        from .custom_monitors import validate as validate_custom
        d['custom']=validate_custom(d.get('custom'))
    else:raise InputError('Monitor kind must be metric, graph, analysis or custom')
    return d


def create(store,raw,replace=None):
    d=validate(raw);identifier='monitor-'+digest(d)
    with store.connect() as c:
        if replace and not c.execute('SELECT 1 FROM monitors WHERE id=?',(replace,)).fetchone():raise InputError('Original monitor not found')
        c.execute('INSERT OR IGNORE INTO monitors VALUES (?,?,1,?)',(identifier,dumps(d),now()))
        c.execute('UPDATE monitors SET enabled=1 WHERE id=?',(identifier,))
        if replace and replace!=identifier:c.execute('UPDATE monitors SET enabled=0 WHERE id=?',(replace,))
    return {'id':identifier,**d,'enabled':True}


def enabled(store,identifier,value):
    if type(value) is not bool:raise InputError('Enabled must be a boolean')
    with store.connect() as c:
        if not c.execute('UPDATE monitors SET enabled=? WHERE id=?',(int(value),identifier)).rowcount:raise KeyError(identifier)
    return {'id':identifier,'enabled':value}


def definitions(store):
    with store.connect() as c:return [{'id':r['id'],**json.loads(r['document']),'enabled':bool(r['enabled'])} for r in c.execute('SELECT * FROM monitors ORDER BY created_at,id')]


def seed(store):
    with store.connect() as c:
        if c.execute('SELECT count(*) FROM monitors').fetchone()[0]:return
    add_starters(store,{})


def add_starters(store,body):
    """Add missing core measures without duplicating or resuming existing ones."""
    from .monitor_catalog import default_definitions
    if not isinstance(body,dict) or set(body)-{'observer'}:raise InputError('Provide optional observer for semantic starters')
    observer=body.get('observer')
    if observer is not None and (observer=='source' or observer not in {g['observer'] for g in graph_store.catalog(store)['graphs']}):
        raise InputError('Select a saved non-source observer for semantic starters')
    def identity(d):return {k:v for k,v in d.items() if k not in {'name','group','id','enabled','schema'}}
    existing=definitions(store);added=[];reused=[]
    for raw in default_definitions(observer):
        d=validate(raw);previous=next((m for m in existing if identity(m)==identity(d)),None)
        if previous:reused.append(previous['id'])
        else:
            saved=create(store,d);added.append(saved['id']);existing.append(saved)
    return {'added':added,'existing':reused}


def population(store):
    with store.connect() as c:
        rows=c.execute('''SELECT r.id,r.imported_at,json_extract(r.document,'$.metadata') metadata,
            json_extract(r.document,'$.adapter') adapter,
            coalesce((SELECT state FROM rollout_revisions WHERE run_id=r.id ORDER BY revision DESC LIMIT 1),'imported_snapshot') state
            FROM runs r WHERE NOT EXISTS(SELECT 1 FROM rollout_revisions rr WHERE rr.run_id=r.id)
              OR EXISTS(SELECT 1 FROM rollout_revisions rr WHERE rr.run_id=r.id AND rr.revision=(SELECT max(revision) FROM rollout_revisions WHERE producer=rr.producer AND rollout_id=rr.rollout_id))''').fetchall()
    return [{'id':r['id'],'imported_at':r['imported_at'],'metadata':json.loads(r['metadata']),
             'adapter':r['adapter'],'state':r['state']} for r in rows]


def in_population(monitor,run):
    """Exact recorded-metadata scope; absent fields never match a named value."""
    return all((run['metadata'].get(k) or '__unassigned__' if k=='experiment' else run['metadata'].get(k))==v
               for k,v in monitor.get('population',{}).items())


def fingerprint(store):
    with store.connect() as c:
        data=[tuple(c.execute('SELECT count(*),max(created_at) FROM '+table).fetchone()) for table in ('rollout_measurements','rollout_graphs','custom_monitor_inputs')]
        data.append(tuple(c.execute('SELECT count(*),max(imported_at) FROM runs').fetchone()))
        data.append(tuple(c.execute('SELECT count(*),max(received_at) FROM evaluation_receipts').fetchone()))
        data.append([tuple(r) for r in c.execute('SELECT producer,rollout_id,revision,run_id,state FROM rollout_revisions ORDER BY producer,rollout_id,revision')])
        data.append([tuple(r) for r in c.execute('SELECT id,enabled FROM monitors ORDER BY id')])
        # Another worker can finish an older annotation after this service has
        # reconciled the new one. A changed index must trigger reconciliation
        # even if no source or graph was added since our last pass.
        data.append([tuple(r) for r in c.execute('SELECT monitor_id,run_id,value_id FROM monitor_latest ORDER BY monitor_id,run_id')])
    return digest([METRIC_VERSION,graph_queries.ENGINE_VERSION,GRAPH_MONITOR_VERSION,data])


def observation_inputs(store, monitor, catalog=None):
    """Read current input identities without materializing observations."""
    catalog = catalog if catalog is not None else graph_store.catalog(store)
    sources = {g['run_id']: g for g in catalog['graphs'] if g['observer'] == 'source'}
    graphs = {g['run_id']: g for g in catalog['graphs'] if g['observer'] == monitor['observer']}
    records = {};input_errors={}
    if monitor['kind']=='custom':
        from .custom_monitors import current_inputs
        records=current_inputs(store,monitor,sources,graphs)
    if monitor['kind'] == 'metric':
        from .measurement_lineage import resolve
        resolved=resolve(store,catalog=catalog,observer=monitor['observer'],metric=monitor['metric'])
        records={key[0]:r for key,r in resolved['records'].items()}
        input_errors={key[0]:reason for key,reason in resolved['unavailable'].items()}
    return {'sources': sources, 'graphs': graphs, 'records': records,'input_errors':input_errors}


def observation_binding(monitor, run, inputs):
    """The same identity rule is used by materialization and read-only readiness."""
    rid = run['id']; source = inputs['sources'].get(rid)
    g = inputs['graphs'].get(rid); record = inputs['records'].get(rid)
    # Source graphs are accepted only by analysis, preserving graph-query rules.
    if monitor['kind'] == 'graph' and monitor['observer'] == 'source': g = None
    if g and (not source or g['source_hash'] != source['source_hash']): g = None
    input_ref = g['id'] if monitor['kind'] in {'graph', 'analysis'} and g else record['id'] if monitor['kind'] in {'metric','custom'} and record else None
    key = digest({'source_hash': source['source_hash'] if source else None, 'input': input_ref, 'state': run['state'],
                  'engine': monitor['custom']['version'] if monitor['kind']=='custom' else monitor['analysis']['version'] if monitor['kind'] == 'analysis' else graph_queries.ENGINE_VERSION+'|'+GRAPH_MONITOR_VERSION if monitor['kind'] == 'graph' else METRIC_VERSION})
    return {'source': source, 'graph': g, 'record': record, 'input_id': input_ref, 'input_hash': key}


def publish_values(c, pending, index):
    """Publish one monitor atomically after potentially concurrent computation.

    Equal results reuse the committed receipt. Different results for the same
    input must not overwrite it or point at an ignored INSERT candidate.
    """
    c.execute('BEGIN IMMEDIATE')
    for vid, monitor_id, run_id, key, _, _ in pending:
        existing = c.execute('SELECT id FROM monitor_values WHERE monitor_id=? AND run_id=? AND input_hash=?',
                             (monitor_id, run_id, key)).fetchone()
        if existing and existing[0] != vid:
            raise InputError('Conflicting monitor results for the same input. Retained receipt '+existing[0]+
                             '; attempted '+vid+'. Check worker versions before retrying. No receipt was overwritten.')
    before = c.total_changes
    c.executemany('INSERT OR IGNORE INTO monitor_values VALUES (?,?,?,?,?,?)', pending)
    inserted = c.total_changes-before
    c.executemany('INSERT INTO monitor_latest VALUES (?,?,?) ON CONFLICT(monitor_id,run_id) DO UPDATE SET value_id=excluded.value_id WHERE monitor_latest.value_id<>excluded.value_id', index)
    return inserted


def sync(store,monitor_ids=None):
    """Idempotent sync, publishing each measurement with its exact input identity."""
    if monitor_ids is None:
        from .rollout_metrics import ensure_current
        ensure_current(store)
        from .strategy_profiles import sync as sync_profiles
        sync_profiles(store)
        from .behavior_distributions import sync as sync_distributions
        sync_distributions(store)
    before=fingerprint(store);runs=population(store);catalog=graph_store.catalog(store)
    inserted=0;reused=0;errors=0
    for monitor in definitions(store):
        if not monitor['enabled']:continue
        if monitor_ids is not None and monitor['id'] not in monitor_ids:continue
        inputs=observation_inputs(store,monitor,catalog)
        with store.connect() as c:
            cached={(r['run_id'],r['input_hash']):r['id'] for r in c.execute('SELECT id,run_id,input_hash FROM monitor_values WHERE monitor_id=?',(monitor['id'],))}
        pending=[];index=[]
        for run in runs:
            if not in_population(monitor,run):continue
            rid=run['id'];binding=observation_binding(monitor,run,inputs)
            source,g,record=binding['source'],binding['graph'],binding['record']
            input_ref,key=binding['input_id'],binding['input_hash']
            if (rid,key) in cached:
                index.append((monitor['id'],rid,cached[(rid,key)]));reused+=1;continue
            result={'value':None,'numerator':None,'denominator':None,'status':'waiting','reason':'Awaiting the selected observer',
                    'graph_id':g['id'] if g and monitor['kind']=='graph' else None,'evidence_ids':[]}
            if inputs.get('input_errors',{}).get(rid):result['reason']=inputs['input_errors'][rid]
            if run['state'] in {'in_progress','failed'}:result.update(status='incomplete',reason='Rollout snapshot is '+run['state'])
            elif monitor['kind']=='custom' and record:
                result.update(record['result'],graph_id=g['id'] if g else None,custom_input_id=record['id'])
            elif monitor['kind']=='custom':
                result.update(reason='Waiting for the code publisher. Run or restart the custom monitor worker.')
            elif monitor['kind']=='analysis' and g:
                try:result.update(analysis_metrics.evaluate(store,monitor,g))
                except (InputError,KeyError,ValueError) as e:result.update(status='error',reason=str(e));errors+=1
            elif monitor['kind']=='metric' and record:
                m=json.loads(record['metric']) if record['metric'] else None
                if m:result.update({k:m.get(k) for k in ('value','numerator','denominator','reason','evidence_ids')},status='available' if m.get('value') is not None else 'unavailable')
            elif monitor['kind']=='graph' and g:
                try:
                    q=graph_queries.evaluate(graph_store.read(store,g['id']),monitor['requirement'])
                    result.update(value=q['recorded_match_fraction'],numerator=q['matched_anchors'],denominator=q['anchors'],
                        status='available' if q['recorded_match_fraction'] is not None else 'unavailable',
                        reason='Recorded graph matches; missing edges remain unknown' if q['anchors'] else 'Required evidence or denominator unavailable',
                        query=q,evidence_ids=[c['anchor'] for c in q['cases'] if c['matches']])
                    # The generic graph query enumerates saved positive paths;
                    # it has no protocol for a fully inspected negative window.
                    # Keep its structural zero in the query receipt, but never
                    # plot it as measured absence of a behavior. Coverage-aware
                    # analysis monitors (e.g. feedback_reference) can report a
                    # supported zero using their explicit opportunity records.
                    if q['anchors'] and not q['matched_anchors']:
                        result.update(value=None,status='unavailable',reason=
                            'No stored matching path; relationship inspection coverage is not established. '
                            'This is not a zero behavior rate. Use a coverage-aware analysis for inspected negatives.')
                    result['graph_monitor_version']=GRAPH_MONITOR_VERSION
                except (InputError,KeyError,ValueError) as e:result.update(status='error',reason=str(e));errors+=1
            result.update(schema=VERSION,monitor_id=monitor['id'],run_id=rid,input_hash=key,input_id=input_ref,
                          source_hash=source['source_hash'] if source else None)
            vid='value-'+digest(result);pending.append((vid,monitor['id'],rid,key,dumps(result),now()));index.append((monitor['id'],rid,vid))
        with store.connect() as c:
            created = publish_values(c, pending, index)
        inserted += created; reused += len(pending)-created
    state={'checked_at':now(),'fingerprint':before,'inserted':inserted,'reused':reused,'errors':errors}
    if monitor_ids is None:
        with store.connect() as c:c.execute('INSERT OR REPLACE INTO monitor_service VALUES (?,?)',('last_sync',dumps(state)))
    return state


def scoped(runs,experiment=None,environment=None):
    return [r for r in runs if (experiment is None or (r['metadata'].get('experiment') or '__unassigned__')==experiment)
            and (not environment or r['metadata'].get('environment')==environment)]


def values(store,monitor_id,run_ids):
    with store.connect() as c:
        return {r['run_id']:{'id':r['id'],**json.loads(r['document'])} for r in c.execute('''SELECT v.id,v.run_id,v.document FROM monitor_latest l
            JOIN monitor_values v ON v.id=l.value_id WHERE l.monitor_id=?''',(monitor_id,)) if r['run_id'] in run_ids}


def current_values(store,monitor,runs,catalog=None):
    """Do not expose an old annotation as a measurement of the current input.

    Old immutable receipts remain inspectable. Pending materialization is a gap,
    including when a slower worker has published an older input after a newer one.
    Receipt and input reads share a snapshot. Call within an outer read snapshot
    when also joining a previously selected population or graph catalog.
    """
    with store.read_snapshot() as saved:
        return _current_values(saved,monitor,runs,catalog)


def _current_values(store,monitor,runs,catalog=None):
    rows=values(store,monitor['id'],{r['id'] for r in runs})
    inputs=observation_inputs(store,monitor,catalog)
    for run in runs:
        value=rows.get(run['id'])
        binding=observation_binding(monitor,run,inputs)
        if value and value.get('input_hash')!=binding['input_hash']:
            rows[run['id']]={'value':None,'status':'pending','reason':'Input changed; awaiting current measurement',
                'previous_value_id':value['id'],'id':None,'run_id':run['id'],
                'source_hash':(binding['source'] or {}).get('source_hash'),
                'graph_id':(binding['graph'] or {}).get('id')}
    return rows


def procedure_coverage(value):
    """Read saved comparison coverage without rewriting historical values."""
    c=value.get('coverage') or {}
    ns=[c.get(k) for k in ('recurrences','procedure_compared','procedure_unknown')]
    valid=all(type(n) is int and n>=0 for n in ns) and ns[1]+ns[2]==ns[0]
    return {'total':ns[0] if valid else 0,'compared':ns[1] if valid else 0,
            'unresolved':ns[2] if valid else 0,'observed_rollouts':int(valid),'total_rollouts':1}


def combine_procedure_coverage(items):
    return {key:sum(item[key] for item in items) for key in
            ('total','compared','unresolved','observed_rollouts','total_rollouts')}


def chart(monitor,runs,rows):
    from . import population_readiness
    groups=defaultdict(list);missing_coordinates=0;statuses=Counter();reasons=Counter();unplaced=[]
    available=[]
    procedures=monitor.get('analysis_definition',{}).get('operation')=='adaptation_patterns'
    for r in runs:
        v=rows.get(r['id'],{'value':None,'status':'pending','reason':'Monitor is being materialized'})
        comparison={'procedure_comparisons':procedure_coverage(v)} if procedures else {}
        statuses[v['status']]+=1
        if v['value'] is not None:available.append(v)
        elif v.get('reason'):reasons[v['reason']]+=1
        m=r['metadata'];step=m.get('training_step')
        if not m.get('experiment') or type(step) is not int or step<0:
            if v['value'] is not None:
                missing_coordinates+=1;unplaced.append({'run_id':r['id'],'value':v['value'],'numerator':v.get('numerator'),'denominator':v.get('denominator'),'value_id':v.get('id'),
                    'opportunities':v.get('opportunities'),'unknown_opportunities':v.get('unknown'),**comparison})
            continue
        cohort={k:m.get(k) for k in ('experiment','environment','environment_version','split','task_revision','sampling','training_clock','training_step_basis','reward_definition','source_selection','training_inclusion')}
        cohort['adapter']=r.get('adapter')
        groups[dumps(cohort)].append({'run_id':r['id'],'step':step,'source_line':m.get('source_line'),
            'capture_state':r.get('state','unknown'),'source_received_at':r.get('imported_at'),
            'task_id':m.get('task_id'),'policy_version':m.get('policy_version'),
            'value':v['value'],'numerator':v.get('numerator'),'denominator':v.get('denominator'),'status':v['status'],
            'opportunities':v.get('opportunities'),'unknown_opportunities':v.get('unknown'),
            'value_id':v.get('id'),**comparison})
    series=[]
    for key,points in sorted(groups.items()):
        points.sort(key=lambda p:(p['step'],p['source_line'] if type(p['source_line']) is int else math.inf,p['run_id']))
        bins=defaultdict(list)
        for i,p in enumerate(points):p['order']=i+1;bins[p['step']].append(p)
        summaries=[]
        for step,ps in sorted(bins.items()):
            known=[p for p in ps if p['value'] is not None];n=sum(p['numerator'] or 0 for p in known);d=sum(p['denominator'] or 0 for p in known)
            pooled=aggregation(monitor) in {'anchor_ratio','opportunity_ratio'}
            value=(n/d if d else None) if pooled else sum(p['value'] for p in known)/len(known) if known else None
            summaries.append({'step':step,'value':value,'n':len(known),'unknown':len(ps)-len(known),'numerator':n if pooled else None,'denominator':d if pooled else None,
                'readiness':population_readiness.summarize(ps,include_mix=False),
                'opportunities':sum(p.get('opportunities') or 0 for p in ps),'unknown_opportunities':sum(p.get('unknown_opportunities') or 0 for p in ps),
                **({'procedure_comparisons':combine_procedure_coverage([p['procedure_comparisons'] for p in ps])} if procedures else {})})
        series.append({'cohort':json.loads(key),'points':points,'bins':summaries})
    is_indicator=aggregation(monitor)=='incidence'
    detector_counts=None
    detector=monitor.get('custom',{}).get('config',{}).get('reward_detector')
    if isinstance(detector,dict) and detector.get('schema')=='reward-detector/1':
        counts=Counter()
        for r in runs:
            value=rows.get(r['id'],{});details=value.get('details');finding=details.get('detector') if isinstance(details,dict) else None
            status=finding.get('status') if isinstance(finding,dict) else None
            if not isinstance(status,str) or status not in {'flagged','clear','unknown','not_applicable'}:
                status='error' if value.get('status')=='error' else 'pending'
            counts[status]+=1
        detector_counts=dict(counts)
    selection=None
    if monitor.get('analysis',{}).get('measure')=='history_query':
        counts=[rows.get(r['id'],{}).get('opportunities') for r in runs]
        selected=sum(type(n) is int and n>0 for n in counts)
        unselected=sum(type(n) is int and n==0 for n in counts)
        selection={'with_dispatches':selected,'without_dispatches':unselected,'unavailable':len(runs)-selected-unselected}
    return {'series':series,'unplaced_points':unplaced,'coverage':{'population':len(runs),'available':len(available),'unknown':len(runs)-len(available),
            'statuses':dict(statuses),'missing_training_coordinates':missing_coordinates,'reasons':dict(reasons),
            'opportunities':sum(rows.get(r['id'],{}).get('opportunities') or 0 for r in runs),
            'unknown_opportunities':sum(rows.get(r['id'],{}).get('unknown') or 0 for r in runs),'query_selection':selection,
            'disputed_work_rollouts':sum(bool(rows.get(r['id'],{}).get('coverage',{}).get('disputed_work_visits')) for r in runs),
            'disputed_work_switches':sum(rows.get(r['id'],{}).get('coverage',{}).get('disputed_work_switches',0) for r in runs),
            **({'procedure_comparisons':combine_procedure_coverage([procedure_coverage(rows.get(r['id'],{})) for r in runs])} if procedures else {})},
            'feedback_counts':dict(Counter(v['feedback']['severity'] for v in rows.values() if v.get('feedback'))),
            **({'detector_counts':detector_counts} if detector_counts is not None else {}),
            'positive_rollouts':sum(v['value']==1 for v in available) if is_indicator else None,
            'aggregation':aggregation(monitor),'unit':unit(monitor)}


def aggregation(monitor):
    if monitor['kind']=='custom':return monitor['custom']['aggregation']
    if monitor['kind']=='analysis':return monitor['analysis_definition']['aggregation']
    if monitor['kind']=='graph':return 'anchor_ratio'
    a=metric_aggregation(monitor['metric']);return a if a in {'opportunity_ratio','incidence'} else 'mean'


def unit(monitor):
    if monitor['kind']=='custom':return monitor['custom']['unit']
    if monitor['kind']=='analysis':return monitor['analysis_definition']['unit']
    return 'fraction' if monitor['kind']=='graph' or aggregation(monitor)=='incidence' or monitor.get('metric')=='recorded_success' or monitor.get('metric','').endswith(('_rate','_fraction','_share','_coverage')) else 'value'


def description(monitor,diagnostic_definitions=None):
    text=monitor['custom']['description'] if monitor['kind']=='custom' else monitor['analysis_definition']['description'] if monitor['kind']=='analysis' else DEFINITIONS[monitor['metric']][1] if monitor['kind']=='metric' else monitor['requirement']['question']
    if monitor['kind']=='metric':
        saved=(diagnostic_definitions or {}).get(monitor['observer'],{}).get(monitor['metric'].removeprefix('diagnostic_'))
        if saved:text=saved['description']
    scope=monitor.get('population',{})
    return text+(' Saved source population: '+', '.join(k+'='+v for k,v in scope.items())+'.' if scope else '')


def snapshot(store,experiment=None,environment=None):
    with store.read_snapshot() as saved:
        return _snapshot(saved,experiment,environment)


def _snapshot(store,experiment=None,environment=None):
    from . import execution_records, generation_cohorts, active_captures
    all_runs=population(store);runs=scoped(all_runs,experiment,environment);ids={r['id'] for r in runs};monitors=[]
    catalog=graph_store.catalog(store)
    from .reward_detectors import catalog as reward_catalog
    diagnostic_definitions={row['id']:row['checks'] for row in reward_catalog(store)['observers']}
    graph_counts=Counter(g['run_id'] for g in catalog['graphs'] if g['observer']!='source' and g['coverage'].get('semantic_relations')!='unavailable' and g['coverage'].get('observation_kind')!='feedback-assessment')
    for d in definitions(store):
        row={**d,'description':description(d,diagnostic_definitions)}
        row['observer_label']=next((g['observer_label'] for g in catalog['graphs'] if g['observer']==d['observer']),None)
        notice=analysis_metrics.definition_notice(d)
        if notice:row['definition_notice']=notice
        if d['enabled']:
            selected=[r for r in runs if in_population(d,r)]
            row.update(chart(d,selected,current_values(store,d,selected,catalog)))
            row['outside_population']=len(runs)-len(selected)
        monitors.append(row)
    with store.connect() as c:
        state=c.execute('SELECT document FROM monitor_service WHERE id=?',('last_sync',)).fetchone()
    experiments=Counter(r['metadata'].get('experiment') or '__unassigned__' for r in all_runs)
    environments={r['metadata'].get('environment') for r in all_runs if r['metadata'].get('environment')}
    # Designs and training facts can arrive before source rollouts. Their scopes
    # must still be selectable; counts remain counts of source rollouts.
    with store.connect() as c:
        facets=c.execute('''SELECT DISTINCT experiment,json_extract(document,'$.data.environment') environment
            FROM training_records WHERE kind='sample'
            UNION SELECT DISTINCT experiment,json_extract(document,'$.data.environment') environment
            FROM training_sample_records WHERE kind='sample'
            UNION SELECT DISTINCT experiment,json_extract(document,'$.environment') environment
            FROM continuation_studies
            UNION SELECT DISTINCT experiment,json_extract(document,'$.environment') environment
            FROM trainer_telemetry
            UNION SELECT DISTINCT experiment,json_extract(document,'$.context.environment') environment
            FROM execution_records
            UNION SELECT DISTINCT experiment,json_extract(document,'$.context.environment') environment
            FROM generation_cohorts
            UNION SELECT DISTINCT experiment,json_extract(m.value,'$.context.environment') environment
            FROM generation_cohorts,json_each(document,'$.members') m''').fetchall()
    for row in facets:
        experiments.setdefault(row['experiment'],0)
        if row['environment']:environments.add(row['environment'])
    return {'schema':VERSION,'captured_at':now(),'workspace':{'database':str(store.path),'rollouts':len(all_runs),'semantic_rollouts':sum(bool(graph_counts[r['id']]) for r in all_runs)},'monitors':monitors,'runs':[{**r,'semantic_graphs':graph_counts[r['id']],'metadata':{k:r['metadata'].get(k) for k in ('task_id','experiment','environment','training_step','source_line','model','policy_version','checkpoint')}} for r in runs],
        'execution_context':execution_records.overview(store,experiment,environment),
        'declared_populations':generation_cohorts.project(store,experiment=experiment,environment=environment),
        'active_captures':active_captures.snapshot(store,experiment=experiment,environment=environment),
        'experiments':[{'id':k,'count':v} for k,v in sorted(experiments.items())],
        'environments':sorted(environments),
        'last_sync':json.loads(state[0]) if state else None,'population':len(runs),'training_rollouts':sum(type(r['metadata'].get('training_step')) is int and bool(r['metadata'].get('experiment')) for r in runs)}


def live_snapshot(store,service,experiment=None,environment=None):
    """Do not acknowledge a new service revision with an older data snapshot.

    Materialization publishes monitors independently. If it overlaps this read,
    the client must refresh even when its service revision already looks current.
    """
    before=service.status();result=snapshot(store,experiment,environment);after=service.status()
    stale=before['revision']!=after['revision'] or before['updating'] or after['updating']
    return {**result,'service':{**after,'snapshot_stale':bool(stale)}}


def cases(store,monitor_id,experiment=None,environment=None):
    with store.read_snapshot() as saved:
        return _cases(saved,monitor_id,experiment,environment)


def _cases(store,monitor_id,experiment=None,environment=None):
    monitor=next((d for d in definitions(store) if d['id']==monitor_id),None)
    if monitor is None:raise KeyError(monitor_id)
    runs=[r for r in scoped(population(store),experiment,environment) if in_population(monitor,r)]
    rows=current_values(store,monitor,runs)
    return {'rows':[{'run':r,'measurement':rows.get(r['id'])} for r in runs]}


def options(store):
    from .reward_detectors import catalog as reward_catalog
    from .monitor_catalog import catalog as starter_catalog
    from .measurement_reviews import VERSION as review_version
    from .analysis_contracts import registered, VERSION as contract_version
    from .feedback_assessment import protocol,LEGACY
    with store.connect() as c:
        observers=[{'id':r['observer'],'label':r['label'] or r['observer']} for r in c.execute("SELECT observer,json_extract(document,'$.observer_label') label FROM rollout_measurements GROUP BY observer")]
        activities=[r[0] for r in c.execute('SELECT DISTINCT activity FROM graph_nodes WHERE activity IS NOT NULL ORDER BY activity')]
        relations=[r[0] for r in c.execute('SELECT DISTINCT type FROM graph_edges ORDER BY type')]
    observers=[o for o in observers if o['id']!=protocol(LEGACY)['id']]
    graphs=graph_store.catalog(store)['graphs'];semantic={g['observer']:g['observer_label'] for g in graphs if g['observer']!='source' and g['coverage'].get('semantic_relations')!='unavailable'}
    return {'starters':starter_catalog(),'metrics':{k:{'label':v[0],'description':v[1]} for k,v in DEFINITIONS.items()},'analysis_measures':analysis_metrics.catalog(),'observers':observers,
            'custom_setup':{'database':str(store.path.resolve()),'sdk':'Workspace.monitor'},
            'reward_checks':reward_catalog(store),
            'custom_observers':[{'id':k,'label':v} for k,v in sorted({g['observer']:g['observer_label'] for g in graphs}.items())],
            'analysis_inputs':{'schema':contract_version,'operations':{k:dict(v['observer_input'],accepted=list(v['observer_input']['accepted'])) for k,v in registered().items()}},
            'graph_observers':[{'id':k,'label':v} for k,v in sorted(semantic.items())], 'presets':graph_queries.PRESETS,
            'activities':activities,'relations':relations,
            'measurement_review':{'version':review_version,'aggregation':'opportunity_ratio','custom_aggregation':'incidence','default_size':20},
            'question_setup':{'schema':'monitor-question-setup/1','population_fields':['experiment','environment','split']}}


def preflight(store,body):
    """Page through a declared population without saving or running analysis."""
    from . import investigation_plans as plans, analysis_contracts
    if not isinstance(body,dict) or set(body)-{'definition','offset','limit','expected_revision'}:
        raise InputError('Provide a monitor definition and optional bounded page')
    monitor=validate(body.get('definition'))
    if monitor['kind'] not in {'graph','analysis'}:raise InputError('Evidence check supports relationship and analysis questions')
    offset,limit=body.get('offset',0),body.get('limit',20)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise InputError('Evidence check offset must be nonnegative and limit must be 1–100')
    runs=sorted((r for r in population(store) if in_population(monitor,r)),key=lambda r:r['id'])
    graphs={(g['run_id'],g['observer']):g for g in graph_store.catalog(store)['graphs']}
    revision=digest([monitor,[(r['id'],r['state'],graphs.get((r['id'],'source'),{}).get('id'),
                            graphs.get((r['id'],monitor['observer']),{}).get('id')) for r in runs]])
    if body.get('expected_revision') is not None and body['expected_revision']!=revision:
        raise InputError('Question or population evidence changed; check again from the first page')
    rows=[]
    for row in runs[offset:offset+limit]:
        rid=row['id'];source=graphs.get((rid,'source'));selected=graphs.get((rid,monitor['observer']))
        run=plans.run_source(store,rid)
        current=bool(source and selected and source['source_hash']==selected['source_hash'])
        graph=graph_store.read(store,selected['id'] if current else source['id']) if source else {'nodes':[],'edges':[]}
        item={'run_id':rid,'task_id':row['metadata'].get('task_id'),'state':row['state'],
              'source_hash':source['source_hash'] if source else None,'graph_id':selected['id'] if current else None,
              'recorded_counts':analysis_contracts.inventory(run,graph),'nodes':[],
              'status':'presence_only' if current else 'needs_observer','guidance':[]}
        if not source:
            item.update(status='needs_source',guidance=['Import the complete source record before checking this question.'])
        elif not current:
            item['guidance']=['Prepare or register the selected observer for this exact source revision. A source import alone does not supply semantic observations.']
        else:
            if monitor['kind']=='graph':
                plan={'schema':plans.VERSION,'nodes':[{'name':'question','op':'relation_query','inputs':[],
                    'params':{'run_id':rid,'source_hash':source['source_hash'],'graph_id':selected['id'],'query':monitor['requirement']}}]}
                item['recorded_anchors']=sum(n.get('activity')==monitor['requirement']['anchor_activity'] for n in graph['nodes'] if n['kind']=='unit')
            else:plan=analysis_metrics.projection_plan(monitor['analysis_definition'],rid,source['source_hash'],selected['id'])
            try:
                checked=plans.preflight(store,plan);item['nodes']=checked['nodes']
                needs={k for node in checked['nodes'] for k in node['missing_evidence']}
                item['status']='missing_inputs' if needs else 'presence_only'
                item['guidance']=[analysis_contracts.EVIDENCE_GUIDANCE[k] for k in sorted(needs)]
            except InputError as error:
                item.update(status='changed_evidence',guidance=[str(error)])
        if row['state'] in {'in_progress','failed'}:
            item['guidance'].append('The source snapshot is incomplete; completed-rollout monitors wait for a completed snapshot.')
        rows.append(item)
    return {'schema':'monitor-question-setup/1','definition':monitor,'definition_hash':digest(monitor),
            'revision':revision,'population':len(runs),'offset':offset,'limit':limit,
            'next_offset':offset+len(rows) if offset+len(rows)<len(runs) else None,
            'rows':rows,'page_statuses':dict(Counter(r['status'] for r in rows)),
            'persisted':False,'new_model_calls':0,
            'notice':'Evidence presence only: no projections, selections or model jobs ran. This page is ordered by rollout ID, not sampled for prevalence. Missing relationships do not establish absence; no readiness or accuracy certification is implied.'}


def rollout(store,run_id,observer=None):
    with store.connect() as c:
        row=c.execute('SELECT document FROM runs WHERE id=?',(run_id,)).fetchone()
    if row is None:raise KeyError(run_id)
    run=json.loads(row[0]);graphs=graph_store.catalog(store,run_id=run_id)['graphs']
    chosen=next((g for g in graphs if g['observer']==observer),None)
    if chosen is None:chosen=next((g for g in graphs if g['observer']=='software-plan-evidence'),None) or next((g for g in graphs if g['coverage'].get('semantic_relations')!='unavailable'),None) or next((g for g in graphs if g['observer']=='source'),None) or next(iter(graphs),None)
    return {'run':run,'graphs':graphs,'graph':graph_store.read(store,chosen['id']) if chosen else None,
            'capabilities':{'work_subject_review':'work-subject-bindings/2','relationship_review':'relationship-review/1','unit_review':'unit-review/1'}}


class Service:
    def __init__(self,store):
        self.store=store;self.stop=threading.Event();self.changed=threading.Event();self.lock=threading.Lock();self.last=None;self.error=None;self.checked_at=None
        seed(store);self.thread=threading.Thread(target=self.loop,name='rollout-monitor-materializer',daemon=True);self.thread.start()
    def loop(self):
        while not self.stop.is_set():
            self.changed.clear()
            try:
                current=fingerprint(self.store)
                if current!=self.last:
                    with self.lock:self.last=sync(self.store)['fingerprint']
                self.error=None;self.checked_at=now()
            except Exception as e:self.error=str(e)
            self.changed.wait(5)
    def wake(self):self.changed.set()
    def status(self):return {'running':self.thread.is_alive(),'checked_at':self.checked_at,'error':self.error,'revision':self.last,'updating':self.lock.locked(),'poll_seconds':5,'refresh_mode':'on ingestion plus 5s reconciliation','inference':'Consumes saved observations; no automatic model calls'}
    def close(self, timeout=10):
        self.stop.set();self.changed.set();self.thread.join(timeout=timeout)
        return not self.thread.is_alive()
