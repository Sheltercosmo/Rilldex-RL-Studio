"""Versioned, exclusive analysis groupings above saved units and episodes.

Grouping is a projection, not new semantic inference. Observation coverage and
unknown categories remain separate from the distribution's denominator.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import re
from urllib.parse import urlencode
from .schema import InputError, digest, dumps
from . import strategy_profiles as profiles
from . import investigation_plans, work_episodes, adaptation_patterns, work_visits, work_order, task_mix, work_consistency
from . import distribution_readiness

VERSION = 'behavior-distribution/1'
WORK_VERSION = 'work-distribution/1|' + work_episodes.VERSION + '|' + adaptation_patterns.VERSION
WORK_LENSES = {'recurrence':'work_episodes', 'procedure':'adaptation_patterns', 'work_visits':'work_visits'}
ACTIVITIES = ('orient','knowledge','plan','inspect','reason','hypothesize','decide','construct','execute','report','verify','coordinate','decline','social')
COLORS = ['#6b68b3','#5594a2','#b78b54','#719273','#ad7694','#7c8ba7']
DEFAULT_GROUPS = [
    {'id':'frame','label':'Frame & plan','activities':['orient','plan'],'color':COLORS[0]},
    {'id':'investigate','label':'Inform & investigate','activities':['knowledge','inspect','reason','hypothesize','decide'],'color':COLORS[1]},
    {'id':'produce','label':'Produce & deliver','activities':['construct','execute','report'],'color':COLORS[2]},
    {'id':'check','label':'Check','activities':['verify'],'color':COLORS[3]},
    {'id':'coordinate','label':'Coordinate & respond','activities':['coordinate','decline','social'],'color':COLORS[4]},
]
LENSES = {
    'work_visits': {'label':'Work focus','grain':'work visits and coverage gaps',
        'question':'How often does the agent return to earlier work?',
        'limit':work_visits.LIMIT+' Consecutive same-subject units collapse into one visit. Missing-source and unreviewed blocks remain visible; visit shares include them. '+work_consistency.LIMIT},
    'recurrence': {'label':'Repeated actions','grain':'recorded actions','question':'When does the agent continue or return to the same work?',
                   'limit':'One position per recorded action. Recurrence needs a saved same-work relationship. An action without a recurrence witness may be first, uninspected or unresolved; it is not classified as exploration. Returns do not establish deviation or recovery.'},
    'procedure': {'label':'Approach changes','grain':'recorded same-work recurrences','question':'How does the procedure change when the agent returns to the same work?',
                  'limit':'Procedure comparisons concern the exact earlier/later work pair. Unknown comparisons remain in these shares. These shares differ from the procedure-change monitor, which excludes unknown comparisons. A different procedure does not establish exploration, improvement or a new objective.'},
    'work': {'label':'Activities','grain':'agent units','question':'Where is the agent allocating its expressed work?',
             'limit':'Unit share measures recorded contributions, not time, tokens, distinct attempts or correctness. Boundaries and selected labels affect the result.'},
    'feedback': {'label':'Feedback review','grain':'feedback windows','question':'How often is returned feedback assessed before the next action?',
                 'limit':'An expressed assessment is not evidence of correct interpretation. Open or unreadable windows remain unresolved.'},
    'failure': {'label':'After failure','grain':'failed-operation opportunities','question':'Which response paths are recorded after an operation fails?',
                'limit':'A missing adjustment or return link is not evidence that the agent made no change or stopped. These are observed paths, not preferences.'},
    'outcome': {'label':'Retry results','grain':'selected same-work retries','question':'What happens when the agent retries the same work?',
                'limit':'Operation completion is not verified task recovery. Outcomes do not establish that an adjustment caused recovery.'},
}
FIXED = {
    'work_visits': [('first_seen','First recorded subject visit'),('returned','Return after other work'),
                    ('resumed','Resume after no-target contributions'),('interrupted','Recurrence across a gap'),
                    ('not_applicable','No immediate work target'),('unknown','Unreviewed or missing units'),
                    ('disputed','Disputed work identity')],
    'recurrence': [('continued','Consecutive same-work recurrence'),('returned','Return after intervening work'),('interrupted','Recurrence across an observation gap'),('unknown','Recurrence not established')],
    'procedure': [('same_procedure','Same procedure'),('reconfigured_procedure','Changed settings or inputs'),('alternative_procedure','Different procedure'),('unknown','Procedure not established')],
    'feedback': [('assessed','Assessed before acting'),('unassessed','No expressed assessment'),('unknown','Window unresolved')],
    'failure': [('adjustment','Linked adjustment → retry'),('retry','Retry; adjustment path unresolved'),('unknown','Return not established')],
    'outcome': [('completed','Completed'),('failed','Failed'),('partial','Partial'),('unknown','Outcome unresolved')],
}


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS behavior_groupings(
        id TEXT PRIMARY KEY,document TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS behavior_unit_inputs(
        id TEXT PRIMARY KEY,graph_id TEXT NOT NULL REFERENCES rollout_graphs(id),
        run_id TEXT NOT NULL REFERENCES runs(id),observer TEXT NOT NULL,
        version TEXT NOT NULL,document TEXT NOT NULL,UNIQUE(graph_id,version));''')


def validate_grouping(raw):
    if not isinstance(raw,dict) or set(raw)-{'name','groups'}: raise InputError('Provide a grouping name and groups')
    name=raw.get('name'); groups=raw.get('groups')
    if not isinstance(name,str) or not 1<=len(name.strip())<=80: raise InputError('Use a grouping name of 1–80 characters')
    if not isinstance(groups,list) or not 1<=len(groups)<=8: raise InputError('Use 1–8 exclusive groups')
    ids=set(); activities=set(); cleaned=[]
    for i,g in enumerate(groups):
        if not isinstance(g,dict) or set(g)-{'id','label','activities','color'}: raise InputError('Invalid group fields')
        key=g.get('id'); label=g.get('label'); acts=g.get('activities')
        if not isinstance(key,str) or not re.fullmatch('[a-z][a-z0-9_]{0,39}',key) or key=='unknown' or key in ids: raise InputError('Distinct group IDs required')
        if not isinstance(label,str) or not 1<=len(label.strip())<=60: raise InputError('Use group labels of 1–60 characters')
        if not isinstance(acts,list) or not acts or any(a not in ACTIVITIES for a in acts): raise InputError('Select supported activities for each group')
        if len(set(acts))!=len(acts) or activities.intersection(acts): raise InputError('Each base activity can belong to only one group')
        color=g.get('color',COLORS[i%len(COLORS)])
        if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color): raise InputError('Use a hex color')
        ids.add(key); activities.update(acts); cleaned.append({'id':key,'label':label.strip(),'activities':sorted(acts),'color':color})
    return {'name':name.strip(),'groups':cleaned}


def save_grouping(store,raw):
    value=validate_grouping(raw); identifier='grouping-'+digest(value)
    with store.connect() as c:c.execute('INSERT OR IGNORE INTO behavior_groupings VALUES (?,?,?)',(identifier,dumps(value),datetime.now(timezone.utc).isoformat()))
    return {'id':identifier,**value}


def groupings(store):
    default={'id':'work-default','name':'Broad work categories','groups':DEFAULT_GROUPS}
    with store.connect() as c:saved=[{'id':r[0],**json.loads(r[1])} for r in c.execute('SELECT id,document FROM behavior_groupings ORDER BY created_at')]
    return [default,*saved]


def latest_graphs(c):
    # Combined recovery/recheck graphs are drill-down evidence, not independent
    # annotation profiles. Creating one during analysis must not replace a
    # selectable observer or change a comparison's measurement inventory.
    return c.execute("""SELECT g.* FROM rollout_graphs g
        WHERE g.observer NOT IN ('source','recovery-evidence/1','next-check-evidence/1')
        AND NOT EXISTS(SELECT 1 FROM rollout_graphs n WHERE n.run_id=g.run_id AND n.observer=g.observer
        AND n.rowid>g.rowid)""").fetchall()


def sync(store, *, graph_ids=None):
    selected=set(graph_ids) if graph_ids is not None else None
    with store.connect() as c:
        known={r[0] for r in c.execute('SELECT graph_id FROM behavior_unit_inputs WHERE version=?',(VERSION,))}; added=0
        for row in latest_graphs(c):
            if selected is not None and row['id'] not in selected: continue
            if row['id'] in known: continue
            graph=json.loads(row['document']); units=[]; records=set(); grounded=set()
            for saved in c.execute('SELECT document FROM graph_nodes WHERE graph_id=?',(row['id'],)):
                n=json.loads(saved[0]); p=n['properties']
                if n['kind']=='event' and p.get('actor')=='agent': records.add(p['id'])
                if n['kind']!='unit' or p.get('actor')!='agent' or p.get('kind')=='feedback': continue
                source=p.get('source',{}); grounded.add(source.get('event_id'))
                units.append({'id':n['id'],'category':n.get('activity') or 'unknown','event_id':source.get('event_id'),
                              'text':source.get('text',''),'source_pointer':source.get('source_pointer'),
                              'event_index':n.get('event_index'),'start':source.get('start')})
            value={'schema':VERSION,'graph_id':row['id'],'run_id':row['run_id'],'observer':row['observer'],
                   'observer_label':graph['observer_label'],'source_hash':row['source_hash'],
                   'records':units,'agent_records':len(records),'records_with_units':len(records & grounded),
                   'review_notes':graph.get('semantic_context',{}).get('review_notes',[]) if graph.get('semantic_context') else []}
            identifier='distribution-input-'+digest(value)
            c.execute('INSERT OR IGNORE INTO behavior_unit_inputs VALUES (?,?,?,?,?,?)',
                      (identifier,row['id'],row['run_id'],row['observer'],VERSION,dumps(value))); added+=1
        return added


def work_inputs(store,lens,run_ids=None,recurrence_order=None):
    """Reuse cached graph projections, retaining native opportunity identities.

    No new semantic decision or population inferred from positive links alone.
    Source-only/state graphs cannot supply these semantic observations.
    """
    with store.connect() as c:
        rows=[dict(r) for r in latest_graphs(c) if run_ids is None or r['run_id'] in run_ids]
        sources={r[0]:r[1] for r in c.execute("SELECT run_id,source_hash FROM rollout_graphs WHERE observer='source'")}
    result=[]
    for row in rows:
        if row['source_hash']!=sources.get(row['run_id']):continue
        graph=json.loads(row['document'])
        if not graph.get('semantic_context') or graph.get('coverage',{}).get('semantic_relations')=='unavailable':continue
        if lens=='work_visits' and not graph['semantic_context'].get('work_subjects'):continue
        plan={'schema':investigation_plans.VERSION,'nodes':[{'name':'observation','op':WORK_LENSES[lens],
            'inputs':[],'params':{k:row[k] for k in ('run_id','source_hash')}|{'graph_id':row['id']}}]}
        if recurrence_order:
            plan['nodes'][0]['params']['recurrence_order']=recurrence_order
        if lens=='work_visits':
            plan['nodes'][0]['params']['scope_consistency']=work_consistency.POLICY
        saved=investigation_plans.execute(store,plan);output=saved['outputs']['observation'];records=[]
        def url(uid,episode=None):
            args={'run':row['run_id'],'observer':row['observer'],'graph':row['id'],'level':'work','focus_unit':uid}
            if episode:args['work_episode']=episode
            if recurrence_order:args['recurrence_order']=recurrence_order
            return '/semantic-map?'+urlencode(args)
        if lens=='recurrence':
            by_id={e['id']:e for e in output['episodes']}
            for path in output['paths']:
                for p in path['positions']:
                    episode=by_id.get(p['episode_id']);uid=p['unit_id'] or 'event:'+p['event_id']
                    records.append({'id':p['event_id'],'category':p['category'] if episode else 'unknown',
                        'text':p['target'] or 'Recorded action without a usable work observation',
                        'event_id':p['event_id'],'unit_id':p['unit_id'],'identity_status':p['identity_status'],
                        'episode':episode,'edge_ids':episode['edge_ids'] if episode else [],
                        'map_url':url(uid,p['episode_id'])})
            coverage=output['counts']
            if not coverage['recorded_actions']:continue
        elif lens=='work_visits':
            for p in output['records']:
                uid=p['unit_ids'][0] if p['unit_ids'] else 'event:'+p['event_ids'][0]
                records.append({'id':p['id'],'category':p['category'],'text':p['target'],
                    'unit_id':uid,'episode':p['episode'],'edge_ids':p['edge_ids'],
                    'map_url':url(uid)+(('&work_visit='+p['id'])), 'record':p})
            coverage=output['coverage']
        else:
            for p in output['records']:
                records.append({'id':p['id'],'category':p['procedure'] if p['procedure']!='unresolved' else 'unknown',
                    'text':p['target'],'episode':p['episode'],'procedure_reason':p['procedure_reason'],
                    'correction_location':p['correction_location'],'method_request':p['method_request'],
                    'work_request':p['work_request'],'edge_ids':p['episode']['edge_ids'],
                    'map_url':url(p['current_unit_id'],p['episode_id'])})
            coverage=output['coverage']
            if not output['observed']:continue
        result.append({'schema':(work_visits.VERSION if lens=='work_visits' else WORK_VERSION),'input_id':output['id'],'graph_id':row['id'],
            'run_id':row['run_id'],'observer':row['observer'],'observer_label':graph['observer_label'],
            'source_hash':row['source_hash'],'updated_at':row['created_at'],'records':records,
            'coverage':coverage,'analysis_plan_id':saved['id'],'analysis_receipt':saved['manifest'],
            **({'switches':output['metrics'],'recurrence_order':recurrence_order,'scope_consistency':work_consistency.POLICY} if lens=='work_visits' else {}),
            'review_notes':graph['semantic_context'].get('review_notes',[]), 'issues':output.get('issues',[])})
    return result


def inputs(store,lens,run_ids=None,recurrence_order=None):
    if lens in WORK_LENSES:return work_inputs(store,lens,run_ids,recurrence_order)
    with store.read_snapshot() as saved:
        return saved_inputs(saved,lens,run_ids)


def saved_inputs(store,lens,run_ids=None):
    with store.connect() as c:
        if lens=='work':
            current={r['id']:r['created_at'] for r in latest_graphs(c)}
            values=[{'input_id':r[0],**json.loads(r[1])} for r in c.execute('SELECT id,document FROM behavior_unit_inputs WHERE version=?',(VERSION,))]
            return [{**d,'updated_at':current[d['graph_id']]} for d in values if d['graph_id'] in current and d['records']]
        from .measurement_lineage import resolve
        current={r['id']:r['created_at'] for r in resolve(store,run_ids=run_ids)['records'].values()}
        values=[json.loads(r[0]) for r in c.execute('SELECT document FROM strategy_profile_observations WHERE version=?',(profiles.VERSION,))]
    result=[]; family='feedback' if lens=='feedback' else 'failure'
    for d in values:
        if d['input_id'] not in current or family not in d['families']:continue
        records=[]
        for e in d['families'][family]:
            if lens=='outcome' and not e['selected_retry']:continue
            category=e['category'] if lens=='feedback' else ('adjustment' if e['adjustment_observed'] else 'retry' if e['selected_retry'] else 'unknown') if lens=='failure' else e['outcome'] if e['outcome'] in {'completed','failed','partial'} else 'unknown'
            records.append({'id':e['id'],'category':category,'episode':e,
                            'text':' → '.join(s['label'] for s in e['stages']),
                            'map_url':'/semantic-map?'+urlencode({'run':d['run_id'],'observer':d['observer'],'profile':d['id'],'episode':e['id']})})
        result.append({**d,'records':records,'updated_at':current[d['input_id']]})
    return result


def aggregate(points,categories,weighting):
    eligible=[p for p in points if p['total']>0]; counts={k:sum(p['counts'][k] for p in eligible) for k in categories}
    total=sum(counts.values())
    shares={k:(sum(p['counts'][k]/p['total'] for p in eligible)/len(eligible) if weighting=='rollout' else counts[k]/total) if total else None for k in categories}
    return {'counts':counts,'total':total,'rollouts':len(points),'eligible_rollouts':len(eligible),'shares':shares}


def cohort(metadata,run_id,population_mode='task'):
    value=profiles.cohort(metadata,run_id)
    # Policy/checkpoint identity is the changing quantity in a logged training
    # experiment. Keep it on each rollout rather than partitioning the curve.
    if metadata.get('experiment') and type(metadata.get('training_step')) is int and metadata['training_step']>=0:
        value.pop('policy_version',None);value.pop('checkpoint',None)
        value['comparison_basis']='logged steps within one experiment'
    if population_mode=='task_mix':
        for key in ('task_id','task_revision','unidentified_task_run'):value.pop(key,None)
        value['population_basis']='multiple tasks; inspect shared-task comparison'
    return value


def snapshot(store,*,lens='work',grouping='work-default',observer=None,cohort_id=None,
             weighting='rollout',population_mode='task',a_start=None,a_end=None,b_start=None,b_end=None,experiment=None,environment=None,recurrence_order=None):
    if recurrence_order is not None:
        work_order.validate(recurrence_order)
        if lens!='work_visits':raise InputError('Work ordering applies only to work visits')
    if population_mode not in {'task','task_mix'}:raise InputError('Choose single task or task-mix comparison')
    if lens not in LENSES:raise InputError('Unknown distribution lens')
    if weighting not in {'rollout','opportunity'}:raise InputError('Choose rollout or opportunity weighting')
    configs=groupings(store); config=next((g for g in configs if g['id']==grouping),None)
    if not config:raise InputError('Unknown grouping')
    categories=config['groups']+[{'id':'unknown','label':'Unmapped activity','activities':[],'color':'#b9bdc8'}] if lens=='work' else [{'id':k,'label':v,'color':'#b9bdc8' if k=='unknown' else '#b7791f' if k=='disputed' else COLORS[i%len(COLORS)]} for i,(k,v) in enumerate(FIXED[lens])]
    keys=[x['id'] for x in categories]; mapping={a:g['id'] for g in config['groups'] for a in g['activities']}
    from .monitoring import population,scoped
    population_rows=scoped(population(store),experiment,environment); runs={r['id']:r for r in population_rows}
    with store.connect() as c:
        index=[dict(r) for r in c.execute('''SELECT g.id,g.run_id,g.observer,g.source_hash FROM rollout_graphs g
            WHERE NOT EXISTS(SELECT 1 FROM rollout_graphs newer WHERE newer.run_id=g.run_id
            AND newer.observer=g.observer AND newer.rowid>g.rowid)''')]
    sources={r['run_id']:r['source_hash'] for r in index if r['observer']=='source'}
    graph_index={(r['run_id'],r['observer']):r for r in index}
    eligible_runs={rid for rid,r in runs.items() if r['state'] not in {'failed','in_progress'}}
    docs=[d for d in inputs(store,lens,eligible_runs,recurrence_order) if d['run_id'] in eligible_runs and d['source_hash']==sources.get(d['run_id'])]
    choices={}
    for d in docs:
        choice=choices.setdefault(d['observer'],{'id':d['observer'],'label':d['observer_label'],'rollouts':0,'placed':0,'updated_at':''})
        choice['rollouts']+=1; choice['placed']+=type(runs[d['run_id']]['metadata'].get('training_step')) is int
        choice['updated_at']=max(choice['updated_at'],d['updated_at'])
    choices=sorted(choices.values(),key=lambda x:(x['placed'],x['updated_at'],x['id']),reverse=True)
    observer=observer if observer is not None else choices[0]['id'] if choices else None
    groups={}
    # Source membership must survive an empty or delayed annotation layer.
    for r in population_rows:
        meta=cohort(r['metadata'],r['id'],population_mode);cid='cohort-'+digest(meta)
        g=groups.setdefault(cid,{'id':cid,'metadata':meta,'docs':[],'runs':[]});g['runs'].append(r)
    for d in docs:
        if d['observer']!=observer:continue
        meta=cohort(runs[d['run_id']]['metadata'],d['run_id'],population_mode); cid='cohort-'+digest(meta)
        groups[cid]['docs'].append(d)
    ordered=sorted(groups.values(),key=lambda g:(-len(g['docs']),-sum(len(d['records']) for d in g['docs']),-len(g['runs']),g['id']))
    cohort_id=cohort_id if cohort_id is not None else ordered[0]['id'] if ordered else None
    chosen=groups.get(cohort_id); selected=chosen['docs'] if chosen else []
    scope_runs=chosen['runs'] if chosen else []
    readiness_members=distribution_readiness.members(scope_runs,selected,graph_index,sources,observer)
    points=[]; cases=[]
    for d in selected:
        r=runs[d['run_id']]; m=r['metadata']; step=m.get('training_step')
        step=step if type(step) is int and step>=0 and m.get('experiment') else None
        counts=Counter()
        for record in d['records']:
            category=mapping.get(record['category'],'unknown') if lens=='work' else record['category'];counts[category]+=1
            url=record.get('map_url') or '/semantic-map?'+urlencode({'run':r['id'],'observer':observer,'graph':d['graph_id'],'focus_unit':record['id']})
            cases.append({**record,'category':category,'base_category':record['category'],'run_id':r['id'],'step':step,'map_url':url,'input_id':d['input_id'],'graph_id':d['graph_id']})
        points.append({'run_id':r['id'],'step':step,'input_id':d['input_id'],'graph_id':d['graph_id'],
                       'policy_version':m.get('policy_version'),'checkpoint':m.get('checkpoint'),'task':task_mix.identity(m),
                       'counts':{k:counts[k] for k in keys},'total':sum(counts.values()),
                       'agent_records':d.get('agent_records'),'records_with_units':d.get('records_with_units'),
                       **({'switches':d['switches']} if lens=='work_visits' else {}),
                       **({'work_coverage':d['coverage'],'analysis_plan_id':d['analysis_plan_id']} if lens in WORK_LENSES else {})})
    points.sort(key=lambda p:(p['step'] is None,p['step'] or 0,p['run_id']))
    scope_steps=Counter(r['metadata']['training_step'] for r in scope_runs if type(r['metadata'].get('training_step')) is int and r['metadata']['training_step']>=0 and r['metadata'].get('experiment'))
    bins=[{'step':step,'population':scope_steps[step],**aggregate([p for p in points if p['step']==step],keys,weighting),
           'observation_readiness':distribution_readiness.summarize([r for r in readiness_members if r['step']==step])} for step in sorted(scope_steps)]
    def bound(value,default):
        if value is None:return default
        if isinstance(value,bool) or not re.fullmatch(r'\d+',str(value)):raise InputError('Training bounds must be nonnegative integers')
        return int(value)
    first=min(scope_steps) if scope_steps else None; last=max(scope_steps) if scope_steps else None
    def bounds(start,end,default):
        lo=bound(start,default);hi=bound(end,default)
        return (lo if lo is not None else hi,hi if hi is not None else lo)
    a=bounds(a_start,a_end,first);b=bounds(b_start,b_end,last)
    if any(x is not None and y is not None and x>y for x,y in (a,b)):raise InputError('Window start must not exceed its end')
    def window(bounds):
        lo,hi=bounds
        ps=[p for p in points if p['step'] is not None and lo is not None and lo<=p['step']<=hi]
        return {'start':lo,'end':hi,'population':sum(n for step,n in scope_steps.items() if lo is not None and lo<=step<=hi),**aggregate(ps,keys,weighting),
                'observation_readiness':distribution_readiness.summarize([r for r in readiness_members if r['step'] is not None and lo is not None and lo<=r['step']<=hi])}
    baseline=window(a);current=window(b); comparable=bool(baseline['eligible_rollouts'] and current['eligible_rollouts'] and a[1]<b[0])
    deltas=[{'id':k,'before':baseline['shares'][k],'after':current['shares'][k],
             'pp':100*(current['shares'][k]-baseline['shares'][k]) if comparable else None} for k in keys]
    total=aggregate(points,keys,weighting)
    result={'schema':work_visits.VERSION if lens=='work_visits' else WORK_VERSION if lens in WORK_LENSES else VERSION,'lens':lens,'lenses':LENSES,'definition':LENSES[lens],'categories':categories,
            'grouping':grouping,'groupings':configs,'activities':list(ACTIVITIES),'weighting':weighting,
            'population_mode':population_mode,'observer':observer,'observers':choices,'cohort_id':cohort_id,'metadata':chosen['metadata'] if chosen else None,
            'cohorts':[{'id':g['id'],'metadata':g['metadata'],'rollouts':len(g['docs']),'population':len(g['runs'])} for g in ordered],
            'population':len(scope_runs),'scope_population':len(population_rows),'observed_rollouts':len(points),'distribution':total,'points':points,'bins':bins,
            'baseline':baseline,'current':current,'deltas':deltas,'comparable':comparable,
            'comparison_reason':None if comparable else 'Choose two non-overlapping windows with observations; earlier window must precede later window.',
            'cases':cases,'unplaced_rollouts':sum(p['step'] is None for p in points),
            'observation_readiness':distribution_readiness.summarize(readiness_members),
            'observation_members':readiness_members,'observation_statuses':distribution_readiness.STATUSES,
            'observation_checks':distribution_readiness.review(baseline['observation_readiness'],current['observation_readiness']),
            'review_note_count':sum(len(d.get('review_notes',[])) for d in selected),
            'annotation_status':'Experimental selected observations; independent semantic accuracy and sample representativeness are not established.',
            'denominator':'Mean of each eligible rollout’s category share' if weighting=='rollout' else 'Category opportunities divided by all recorded opportunities',
            'inference_calls':0}
    basis=(chosen['metadata'].get('training_step_basis') if chosen else None)
    result['axis']={'basis':basis,'label':str(basis).replace('_',' ').capitalize()+' index' if basis else 'Recorded step · basis unspecified',
                    'meaning':'Source-declared progress coordinate. Generation batches, optimizer updates and checkpoint evaluations are different clocks.'}
    if lens=='work_visits':
        result['recurrence_order']=recurrence_order
        result['scope_consistency']=work_consistency.POLICY
        result['ordering_label']='Parallel work included' if recurrence_order else 'Earlier ordering rule'
    if population_mode=='task_mix':
        scope_points=[{'run_id':r['id'],'task':task_mix.identity(r['metadata']),
                       'step':r['metadata'].get('training_step') if type(r['metadata'].get('training_step')) is int and r['metadata']['training_step']>=0 and r['metadata'].get('experiment') else None} for r in scope_runs]
        result['task_mix']=task_mix.compare(points,scope_points,keys,weighting,a,b,[x['step'] for x in bins],aggregate)
        for row in result['task_mix']['tasks']:
            member=next(r for r in scope_runs if task_mix.identity(r['metadata'])==row['task'])
            row['cohort_id']='cohort-'+digest(cohort(member['metadata'],member['id']))
    if lens in WORK_LENSES:
        result['analysis_receipts']=[{'run_id':d['run_id'],'graph_id':d['graph_id'],
            'plan_id':d['analysis_plan_id'],'manifest':d['analysis_receipt'],'issues':d['issues']} for d in selected]
    result['snapshot_id']='distribution-'+digest(result)
    return result
