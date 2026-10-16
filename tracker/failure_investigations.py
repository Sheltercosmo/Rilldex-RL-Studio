"""Explicit focus/reference comparisons over saved rollout measurements.

No causal attribution, automatic failure inference, model calls or imputation.
Investigations freeze their population, measurements and researcher hypothesis.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math
import statistics
from urllib.parse import urlencode

from .schema import InputError, digest, dumps
from .population_statistics import spearman
from . import monitoring, behavior_distributions as distributions
from .rollout_metrics import DEFINITIONS, VERSION as METRIC_VERSION
from .reward_records import DEFINITIONS as REWARD_DEFINITIONS
from .environment_metrics import DEFINITIONS as ENVIRONMENT_DEFINITIONS

VERSION='failure-investigation/1'
SOURCE_KEYS={'actions','agent_text_chars','feedback_link_rate','exact_dispatch_repeat_rate','recorded_success','recorded_reward',*REWARD_DEFINITIONS,*ENVIRONMENT_DEFINITIONS}
OPTIONS={'run','focus','scope','steps','limit','observer','signal','operator','threshold','reference'}


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS failure_investigations(id TEXT PRIMARY KEY,document TEXT NOT NULL,created_at TEXT NOT NULL)')


def finite(v):return type(v) in (int,float) and math.isfinite(v)


def catalog(store):
    runs=monitoring.population(store)
    with store.connect() as c:
        outcomes={r[0]:json.loads(r[1] or '{}') for r in c.execute("SELECT id,json_extract(document,'$.outcome') FROM runs")}
    for r in runs:
        o=outcomes.get(r['id'],{});r['success']=o.get('verified_success') if type(o.get('verified_success')) is bool else None
        r['reward']=o.get('recorded_reward') if finite(o.get('recorded_reward')) else None
        r['complete']=r['state'] not in {'in_progress','failed'}
    return sorted(runs,key=lambda r:(r['imported_at'],r['id']),reverse=True)


def cohort(r,scope):
    value=distributions.cohort(r['metadata'],r['id'])
    if scope=='configuration':value.pop('task_id',None);value.pop('unidentified_task_run',None)
    return value


def select_population(runs,anchor,scope,steps,limit):
    matched=[r for r in runs if r['complete'] and cohort(r,scope)==cohort(anchor,scope)]
    at=anchor['metadata'].get('training_step');placed=type(at) is int and at>=0 and bool(anchor['metadata'].get('experiment'))
    if placed:
        eligible=[r for r in matched if type(r['metadata'].get('training_step')) is int and 0<=r['metadata']['training_step']<=at]
        selected_steps=sorted({r['metadata']['training_step'] for r in eligible},reverse=True)[:steps]
        eligible=[r for r in eligible if r['metadata']['training_step'] in selected_steps]
        eligible.sort(key=lambda r:(-r['metadata']['training_step'],r['metadata'].get('source_line') if type(r['metadata'].get('source_line')) is int else 0,r['id']))
        basis='Current and preceding recorded training steps; same-step file order is not temporal order.'
    else:
        eligible=[r for r in matched if r['imported_at']<=anchor['imported_at']]
        eligible.sort(key=lambda r:(r['imported_at'],r['id']),reverse=True)
        basis='Import recency only; generation chronology is unavailable.'
    result=eligible[:limit]
    if anchor['id'] not in {r['id'] for r in result}:result=[anchor,*result[:limit-1]]
    return result,{'matched':len(matched),'eligible':len(eligible),'displayed':len(result),'truncated':max(0,len(eligible)-len(result)),
                   'basis':basis,'steps':sorted({r['metadata']['training_step'] for r in result}) if placed else [],
                   'task_count':len({r['metadata'].get('task_id') or r['id'] for r in result})}


def describe(values,ids):
    rows=[values[r] for r in ids if finite(values.get(r,{}).get('value'))];vs=[r['value'] for r in rows]
    return {'n':len(vs),'total':len(ids),'missing':len(ids)-len(vs),'mean':statistics.fmean(vs) if vs else None,
            'median':statistics.median(vs) if vs else None,'min':min(vs) if vs else None,'max':max(vs) if vs else None}




def flag(value,operator,threshold):
    if not finite(value):return None
    return value<=threshold if operator=='le' else value>=threshold if operator=='ge' else value==threshold


def measurements(store,runs,anchor_id,observer,*,cache_store=None):
    ids={r['id'] for r in runs}
    with store.connect() as c:
        sources={r['run_id']:dict(r) for r in c.execute("SELECT id,run_id,source_hash FROM rollout_graphs WHERE observer='source' ORDER BY rowid")}
    from .measurement_lineage import resolve
    latest=resolve(store,run_ids=ids,include_metrics=True)['records']
    graph_inputs=[v for v in distributions.inputs(store,'work') if v['run_id'] in ids and v['source_hash']==sources.get(v['run_id'],{}).get('source_hash')]
    protocols={}
    for r in latest.values():
        if r['observer']=='source':continue
        p=protocols.setdefault(r['observer'],{'id':r['observer'],'label':r['label'] or r['observer'],'rollouts':set(),'updated_at':'','anchor':False})
        p['rollouts'].add(r['run_id']);p['updated_at']=max(p['updated_at'],r['created_at']);p['anchor']|=r['run_id']==anchor_id
    for r in graph_inputs:
        p=protocols.setdefault(r['observer'],{'id':r['observer'],'label':r['observer_label'],'rollouts':set(),'updated_at':'','anchor':False})
        p['rollouts'].add(r['run_id']);p['anchor']|=r['run_id']==anchor_id;p['updated_at']=max(p['updated_at'],r['updated_at'])
    choices=sorted([{**p,'rollouts':len(p['rollouts'])} for p in protocols.values()],key=lambda p:(p['anchor'],p['updated_at']),reverse=True)
    observer=observer or (choices[0]['id'] if choices else 'source')
    metrics=[]
    def metric(key,label,definition,group,unit,values):
        metrics.append({'id':key,'label':label,'definition':definition,'group':group,'unit':unit,'values':values})
    for key,(label,definition) in DEFINITIONS.items():
        source=key in SOURCE_KEYS;protocol='source' if source else observer;values={}
        for rid in ids:
            r=latest.get((rid,protocol));m=json.loads(r['metrics']).get(key) if r and r['metrics'] else None
            if not m:continue
            g=r['graph_id'] or (sources.get(rid,{}).get('id') if source else None)
            values[rid]={**m,'input_id':r['id'],'observer':protocol,'graph_id':g,'source_hash':r['source_hash']}
        group='Outcome & evaluator' if key.startswith('reward_') or key.startswith('recorded_') else 'Recorded behavior' if source else 'Coverage' if any(w in key for w in ('coverage','unknown','unresolved')) else 'Semantic behavior'
        unit='fraction' if key.endswith(('_fraction','_share','_rate','_coverage')) or key.startswith('diagnostic_') or key in {'recorded_success','reward_penalty_observed','reward_zero_with_negative_rubric'} else 'value'
        metric(('source:' if source else 'observation:')+key,label,definition,group,unit,values)
    # Coarse activity mix uses the same saved graph projection as Distributions.
    for g in [*distributions.DEFAULT_GROUPS,{'id':'unknown','label':'Unmapped activity','activities':[]}]:
        values={};assigned={a for group in distributions.DEFAULT_GROUPS for a in group['activities']}
        for r in graph_inputs:
            if r['observer']!=observer:continue
            chosen=[u for u in r['records'] if u['category'] in g['activities'] or g['id']=='unknown' and u['category'] not in assigned]
            total=len(r['records']);values[r['run_id']]={'value':len(chosen)/total if total else None,'numerator':len(chosen),'denominator':total,
                'input_id':r['input_id'],'observer':observer,'graph_id':r['graph_id'],'source_hash':r['source_hash'],'evidence_ids':[u['id'] for u in chosen]}
        metric('mix:'+g['id'],g['label']+' · unit share','Selected agent units in this broad activity group / all selected agent units. Unit share is not time or quality.','Behavior mix','fraction',values)
    # Use the same immutable projection as the episode chart. The dependency
    # cache makes adding another comparison reuse, rather than reinterpret, it.
    from . import investigation_plans as plans
    with store.connect() as c:
        graphs=c.execute('SELECT id,run_id,source_hash FROM rollout_graphs WHERE observer=? ORDER BY rowid',(observer,)).fetchall()
    selected={r['run_id']:dict(r) for r in graphs if r['run_id'] in ids and r['source_hash']==sources.get(r['run_id'],{}).get('source_hash')}
    definitions=[('continued','Consecutive work recurrences'),('returned','Returns after intervening operations'),
                 ('interrupted','Recurrences across observation gaps'),('recurrences_with_assessment','Recurrences with recorded feedback assessment'),
                 ('recurrences_with_adjustment','Recurrences with attempted correction')]
    episode_values={key:{} for key,_ in definitions}
    if selected and observer!='source':
        result=plans.execute(store,{'schema':plans.VERSION,'nodes':[{'name':rid,'op':'work_episodes','inputs':[],
            'params':{'run_id':rid,'source_hash':r['source_hash'],'graph_id':r['id']}} for rid,r in sorted(selected.items())]},cache_store=cache_store)
        for rid,r in result['outputs'].items():
            c=r['counts'];observed=bool(c['identity_reviewed'] or r['episodes'])
            for key,_ in definitions:
                cases=[e for e in r['episodes'] if (bool(e['assessment_unit_ids']) if key=='recurrences_with_assessment' else
                        bool(e['adjustments']) if key=='recurrences_with_adjustment' else e['category']==key)]
                episode_values[key][rid]={'value':c[key] if observed else None,'input_id':r['id'],
                    'observer':observer,'graph_id':r['graph_id'],'source_hash':r['source_hash'],
                    'evidence_ids':[e['current_unit_id'] for e in cases],'episode_ids':[e['id'] for e in cases],
                    'coverage':{k:c[k] for k in ('recorded_actions','represented_actions','identity_reviewed')},
                    'reason':'Recorded witnesses; unlinked actions and missing relations remain unresolved.' if observed else 'No recorded work-identity review or positive recurrence link.'}
    for key,label in definitions:
        metric('episode:'+key,label,'Count of recorded work-identity episodes under this definition. Includes only source-grounded links available by the recurrence; missing links do not establish absence. Compare annotation coverage and rollout length.','Work recurrence','value',episode_values[key])
    for m in monitoring.definitions(store):
        # Independently configured monitors can use other specialized harnesses.
        # Each series keeps one exact monitor/protocol; never merge predictions.
        if not m['enabled']:continue
        if m['kind']=='metric' and (m['metric'] in SOURCE_KEYS or m['observer']==observer):continue
        values=monitoring.current_values(store,m,[r for r in runs if monitoring.in_population(m,r)])
        values={rid:v for rid,v in values.items() if v.get('source_hash')==sources.get(rid,{}).get('source_hash')}
        for v in values.values():v['observer']=m['observer']
        if m['kind']=='analysis':definition=m['analysis_definition']['description'];group='Saved analysis';unit=m['analysis_definition']['unit']
        elif m['kind']=='graph':definition=m['requirement']['question'];group='Graph relationships';unit='fraction'
        elif m['kind']=='custom':definition=m['custom']['description'];group='Custom code';unit=m['custom']['unit']
        else:
            template=next(x for x in metrics if x['id']=='observation:'+m['metric'])
            definition=template['definition'];unit=template['unit'];group='Diagnostic monitor' if m['metric'].startswith('diagnostic_') else 'Saved monitor'
        metric('monitor:'+m['id'],m['name'],definition,group,unit,values)
        metrics[-1]['protocol']=m['observer']
        if m.get('population'):
            metrics[-1]['definition']=monitoring.description(m)
            metrics[-1]['monitor_population']=m['population']
    return metrics,observer,[{'id':'source','label':'Recorded source only','rollouts':len(ids)},*choices],sources,selected


def snapshot(store,**options):
    # Freeze population, metrics and graph choices together. Derived process
    # projections can then publish their caches using these immutable identities.
    with store.read_snapshot() as saved:
        result,sources,selected=_snapshot(saved,cache_store=store,**options)
    from .investigation_plans import build as build_process
    result['process']=build_process(store,result['rows'],result['controls']['observer'],sources,selected_graphs=selected)
    result['snapshot_id']='investigation-snapshot-'+digest(result)
    return result


def _snapshot(store,*,cache_store,**options):
    if set(options)-OPTIONS:raise InputError('Unknown investigation controls')
    runs=catalog(store);by_id={r['id']:r for r in runs}
    anchor_id=options.get('run') or next((r['id'] for r in runs if r['complete'] and (r['success'] is False or r['reward'] is not None and r['reward']<=0)),None) or next((r['id'] for r in runs if r['complete']),None)
    if anchor_id not in by_id:raise InputError('Select an available rollout to investigate')
    anchor=by_id[anchor_id]
    if not anchor['complete']:raise InputError('An incomplete ingestion is not a model failure; choose a completed snapshot')
    scope=options.get('scope','task');reference=options.get('reference','others');operator=options.get('operator') or ('eq' if anchor['success'] is False else 'le')
    if scope not in {'task','configuration'} or reference not in {'others','signal_negative'} or operator not in {'le','ge','eq'}:raise InputError('Invalid comparison controls')
    def integer(key,default,lo,hi):
        v=options.get(key,default)
        if isinstance(v,bool) or not str(v).isdigit() or not lo<=int(v)<=hi:raise InputError('Invalid '+key)
        return int(v)
    steps=integer('steps',1,1,1000);limit=integer('limit',64,2,256)
    try:threshold=float(options.get('threshold',0))
    except (ValueError,TypeError):raise InputError('Signal threshold must be a finite number')
    if not finite(threshold):raise InputError('Signal threshold must be a finite number')
    pool,population=select_population(runs,anchor,scope,steps,limit);ids=[r['id'] for r in pool]
    focus=options.get('focus',[anchor_id]);focus=focus.split(',') if isinstance(focus,str) else focus
    if not isinstance(focus,list) or not focus or any(not isinstance(r,str) or r not in ids for r in focus):raise InputError('Focus must contain at least one rollout inside the selected window')
    focus=list(dict.fromkeys(focus))
    metrics,observer,protocols,sources,selected=measurements(store,pool,anchor_id,options.get('observer'),cache_store=cache_store)
    signal=options.get('signal') or ('source:recorded_success' if anchor['success'] is False else 'source:recorded_reward')
    index={m['id']:m for m in metrics}
    if signal not in index:raise InputError('Select a signal measured by this protocol')
    signals={rid:flag(index[signal]['values'].get(rid,{}).get('value'),operator,threshold) for rid in ids}
    baseline=[rid for rid in ids if rid not in focus and (reference=='others' or signals[rid] is False)]
    included=set(focus+baseline)
    for m in metrics:
        m['focus']=describe(m['values'],focus);m['reference']=describe(m['values'],baseline)
        a=m['focus']['mean'];b=m['reference']['mean'];m['difference']=a-b if a is not None and b is not None else None
        pairs=[(m['values'][rid]['value'],index[signal]['values'][rid]['value']) for rid in ids if rid in included and finite(m['values'].get(rid,{}).get('value')) and finite(index[signal]['values'].get(rid,{}).get('value'))]
        m['signal_association']=spearman(pairs) if m['id']!=signal else {'rho':None,'n':len(pairs),'reason':'The selected signal cannot explain itself'}
        if signal=='source:recorded_reward' and m['id'] in {'source:reward_score_gap','source:reward_zero_with_negative_rubric'}:
            m['signal_association']={'rho':None,'n':len(pairs),'reason':'Uses logged reward in its own definition; not an independent correlate'}
        for rid,v in m['values'].items():
            q={'run':rid,'observer':v.get('observer',observer)}
            if m['id'].startswith('monitor:') and v.get('id'):q['value']=v['id']
            elif v.get('graph_id'):
                q['graph']=v['graph_id'];evidence=v.get('evidence_ids') or []
                if m['id'].startswith('mix:') and evidence:q['focus_unit']=evidence[0]
            v['map_url']='/semantic-map?'+urlencode(q)
    controls={'run':anchor_id,'focus':focus,'scope':scope,'steps':steps,'limit':limit,'observer':observer,'signal':signal,'operator':operator,'threshold':threshold,'reference':reference}
    result={'schema':VERSION,'controls':controls,'anchor':anchor,'population':population,'protocols':protocols,
        'rows':[{**r,'focus':r['id'] in focus,'reference':r['id'] in baseline,'signal_flag':signals[r['id']],
                 'source_graph_id':sources.get(r['id'],{}).get('id')} for r in pool],
        'focus_count':len(focus),'reference_count':len(baseline),'excluded_count':len(ids)-len(included),'metrics':metrics,
        'recent':[{k:r[k] for k in ('id','metadata','imported_at','success','reward','complete')} for r in runs[:100]],
        'signal_known':sum(v is not None for v in signals.values()),'signal_positive':sum(v is True for v in signals.values()),
        'inference_calls':0,'limits':['Whole-rollout metrics can include responses after the failure; temporal precedence is not established.',
            'Spearman correlations are exploratory, unadjusted associations within this sample, not causal explanations or significance tests.',
            'Task mix, training step, shared reward components and annotation coverage can explain associations. Unknown values are never zero-filled.',
            'Semantic observations remain experimental; comparison checks do not validate their accuracy.']}
    return result,sources,selected


def save(store,raw):
    if set(raw)-{'controls','snapshot_id','title','hypothesis','x','y'}:raise InputError('Unknown investigation fields')
    for key,size in [('title',120),('hypothesis',6000)]:
        if not isinstance(raw.get(key),str) or len(raw[key])>size or key=='title' and not raw[key].strip():raise InputError('Invalid '+key)
    if not isinstance(raw.get('controls'),dict):raise InputError('Comparison controls required')
    data=snapshot(store,**raw['controls'])
    if data['snapshot_id']!=raw.get('snapshot_id'):raise InputError('Observations changed. Refresh and review before saving.')
    keys={m['id'] for m in data['metrics']}
    if raw.get('x') not in keys or raw.get('y') not in keys:raise InputError('Select valid plot metrics')
    value={'schema':VERSION,'title':raw['title'].strip(),'hypothesis':raw['hypothesis'],'hypothesis_status':'Researcher hypothesis; not a verified cause',
           'x':raw['x'],'y':raw['y'],'snapshot':data}
    return persist(store,value)


def persist(store,value):
    identifier='investigation-'+digest(value)
    with store.connect() as c:c.execute('INSERT OR IGNORE INTO failure_investigations VALUES (?,?,?)',(identifier,dumps(value),datetime.now(timezone.utc).isoformat()))
    return {'id':identifier,**value}


def read(store,identifier):
    with store.connect() as c:r=c.execute('SELECT document FROM failure_investigations WHERE id=?',(identifier,)).fetchone()
    if not r:raise KeyError(identifier)
    d=json.loads(r[0])
    if identifier!='investigation-'+digest(d):raise InputError('Saved investigation identity mismatch')
    return {'id':identifier,**d}


def saved(store):
    with store.connect() as c:
        return [{'id':r[0], 'title':r[1], 'created_at':r[2], 'check_count':r[3], 'finding_count':r[4]}
                for r in c.execute("""SELECT id,json_extract(document,'$.title'),created_at,
                    coalesce(json_array_length(document,'$.follow_up.checks'),0),
                    coalesce((SELECT sum(json_array_length(j.value,'$.results'))
                              FROM json_each(f.document,'$.follow_up.checks') AS j),0)
                    FROM failure_investigations AS f ORDER BY created_at DESC,id LIMIT 100""")]
