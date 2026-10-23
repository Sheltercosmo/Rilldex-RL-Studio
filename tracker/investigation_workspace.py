"""A synchronized, immutable interval investigation over recorded evidence.

Generation coordinates select source rollouts. Learner signals are joined by
exact sample identity, never by equating generation and learner step numbers.
All readers share one SQLite read transaction. No classifier is invoked.
"""
from collections import Counter
from copy import deepcopy
import json

from . import monitoring as m, monitor_comparisons as comparisons, failure_investigations
from .schema import InputError, digest, dumps

VERSION='interval-investigation/1'
EVENT_TYPES=('curriculum','reward_grader','sampling','budget_phase','restart','infrastructure','other')


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS experiment_history(id TEXT PRIMARY KEY, document TEXT NOT NULL, created_at TEXT NOT NULL)')


def history(store,experiment,environment=None):
    with store.connect() as c:
        rows=[{'id':r[0],**json.loads(r[1])} for r in c.execute(
            "SELECT id,document FROM experiment_history WHERE json_extract(document,'$.experiment')=? ORDER BY created_at,id",(experiment,))]
    return [r for r in rows if not environment or r.get('environment') in (None,environment)]


def annotate(store,raw):
    required={'experiment','kind','title','detail','step','clock','basis'}
    if not isinstance(raw,dict) or not required<=set(raw) or set(raw)-required-{'environment','investigation_id','supersedes'}:
        raise InputError('History needs experiment, kind, title, detail, step, clock and basis')
    for key,limit in [('experiment',240),('title',200),('detail',6000),('clock',200),('basis',200)]:
        if not isinstance(raw[key],str) or not raw[key].strip() or len(raw[key])>limit:raise InputError('Provide '+key)
    if raw['kind'] not in EVENT_TYPES or type(raw['step']) is not int or raw['step']<0:raise InputError('Invalid event kind or coordinate')
    if raw.get('environment') is not None and (not isinstance(raw['environment'],str) or not raw['environment'].strip()):raise InputError('Invalid environment')
    if raw.get('investigation_id'):
        parent=failure_investigations.read(store,raw['investigation_id'])
        if parent.get('scope',{}).get('experiment')!=raw['experiment']:raise InputError('Investigation belongs to another experiment')
    if raw.get('supersedes'):
        prior=next((r for r in history(store,raw['experiment']) if r['id']==raw['supersedes']),None)
        if prior is None:raise InputError('Previous event is outside this experiment')
    value=dict(schema='experiment-history/1',**deepcopy(raw),recorded_at=m.now(),
        attribution='Researcher-recorded event; temporal coincidence does not establish causality')
    identifier='history-'+digest(value)
    with store.connect() as c:c.execute('INSERT INTO experiment_history VALUES (?,?,?)',(identifier,dumps(value),value['recorded_at']))
    return {'id':identifier,**value}


def audit_summary(store,monitor_id,measurement_ids):
    """Report only reviewed cases bound to these exact saved receipts."""
    from .measurement_reviews import labels
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='measurement_review_samples'").fetchone():return []
        samples=c.execute('SELECT id,document FROM measurement_review_samples WHERE monitor_id=? ORDER BY created_at',(monitor_id,)).fetchall()
    reports=[]
    for sid,text in samples:
        sample=json.loads(text)
        if sid!='review-sample-'+digest(sample) or sample['frame_hash']!=digest(sample['frame']):raise InputError('Review sample integrity mismatch')
        frame={r['id']:r for r in sample['frame']}
        eligible={cid for cid in sample['sample_ids'] if frame[cid]['measurement_id'] in measurement_ids}
        if not eligible:continue
        latest=labels(store,sid)
        for reviewer in sorted({name for cid,name in latest if cid in eligible}):
            counts=Counter();roles=set()
            for cid in eligible:
                label=latest.get((cid,reviewer))
                if not label:continue
                counts['reviewed']+=1;roles.add(label['reviewer_role']);pred=frame[cid]['prediction']
                if label['label']=='not_opportunity':counts['scope_agreements' if frame[cid].get('predicted_scope')=='outside' else 'scope_unresolved' if frame[cid].get('predicted_scope')=='unresolved' else 'eligibility_disputes']+=1
                elif label['label']=='unknown' or pred is None:
                    counts['unresolved']+=1
                    if label['label']!='unknown' and frame[cid].get('predicted_scope')=='outside':counts['eligibility_disputes']+=1
                else:
                    counts['comparable']+=1;counts['agree' if pred==(label['label']=='taken') else 'disagree']+=1
            reports.append(dict(sample_id=sid,reviewer=reviewer,declared_roles=sorted(roles),eligible=len(eligible),
                **dict(counts),agreement=counts['agree']/counts['comparable'] if counts['comparable'] else None))
    return reports


def reliability(store,monitor,runs):
    values=m.current_values(store,monitor,runs)
    ids={v['id'] for v in values.values() if v.get('id')}
    versions=Counter();graph_ids={v.get('graph_id') for v in values.values()}-{None};graph_versions={}
    with store.connect() as c:
        # Read only graph versions used by this measure, not other annotations.
        for gid in sorted(graph_ids):
            row=c.execute('SELECT document FROM rollout_graphs WHERE id=?',(gid,)).fetchone()
            if row:
                doc=json.loads(row[0]);definition={k:doc.get(k) for k in ('schema','observer','adapter_version')}
                definition['harnesses']=(doc.get('semantic_context') or {}).get('provenance',{})
                versions[dumps(definition)]+=1;graph_versions[gid]=definition
    source_coverage={}
    with store.connect() as c:
        for rid,v in values.items():
            gid=v.get('graph_id')
            row=c.execute('SELECT document FROM rollout_graphs WHERE id=?',(gid,)).fetchone() if gid else None
            if row:source_coverage[rid]=json.loads(row[0]).get('coverage',{})
    from .measurement_lineage import resolve
    recorded=resolve(store,observer=monitor['observer'],run_ids=[r['id'] for r in runs],metric='annotated_actions_fraction')['records']
    action_coverage={rid:json.loads(row['metric']) for (rid,_),row in recorded.items() if row.get('metric')}
    return dict(observer=monitor['observer'],definition_version=monitor.get('analysis_definition',{}).get('version') or
        monitor.get('custom',{}).get('version') or m.METRIC_VERSION,
        graph_versions=[dict(definition=json.loads(k),graphs=v) for k,v in sorted(versions.items())],
        measurement_ids=sorted(ids),annotation_coverage=source_coverage,action_coverage=action_coverage,
        versions_by_run={rid:graph_versions.get(v.get('graph_id')) for rid,v in values.items()},
        audits=audit_summary(store,monitor['id'],ids),
        boundary='Coverage and stable versions do not establish semantic accuracy. Audit roles are self-declared; these audits cover saved opportunities, not missed opportunities outside that frame.')


def learning_context(lineage,source_rows=()):
    """Selection-conditioned scores and use signals, with explicit grains."""
    output={};source_metadata={r['id']:r['metadata'] for r in source_rows}
    for side,window in lineage['windows'].items():
        scores={};filters={};uses={}
        for rollout in window['rollouts']:
            for sample in rollout['samples']:
                context={k:sample.get(k) for k in ('experiment','producer','split','environment','environment_version','recipe','step_basis','sample_identity_schema')}
                context['source_configuration']={k:source_metadata.get(rollout['run_id'],{}).get(k) for k in
                    ('training_clock','training_step_basis','sampling','reward_definition','task_revision','source_selection','training_inclusion')}
                sample_scores={};sample_filters={}
                for r in sample['records']:
                    data=r['data'];producer=r['record_producer']
                    if r['kind']=='score':
                        key=dumps(dict(context,scorer=producer,component=data['component'],definition=data['definition']))
                        sample_scores.setdefault(key,[]).append(data)
                    elif r['kind']=='selection':
                        key=dumps(dict(context,filter_producer=producer,filter=data['filter'],definition=data['definition']))
                        sample_filters.setdefault(key,[]).append(data['decision'])
                    elif r['kind']=='use':
                        key=dumps(dict(context,learner_producer=producer,stage=data['stage'],use_recipe=data.get('recipe')))
                        group=uses.setdefault(key,dict(context=json.loads(key),uses=0,paired_token_uses=0,model_tokens=0,loss_tokens=0,learner_steps=set(),advantages=[]))
                        group['uses']+=1;group['learner_steps'].add(data['learner_step'])
                        if 'model_tokens' in data and 'loss_tokens' in data:
                            group['paired_token_uses']+=1;group['model_tokens']+=data['model_tokens'];group['loss_tokens']+=data['loss_tokens']
                        if 'advantage' in data:group['advantages'].append(data['advantage'])
                for key,rows in sample_scores.items():
                    group=scores.setdefault(key,dict(context=json.loads(key),stages={stage:dict(members=0,scored=0,ambiguous=0,values=[]) for stage in ('generated','admitted','optimizer')}))
                    for stage,entry in group['stages'].items():
                        if sample['stage_membership'][stage]!='member':continue
                        entry['members']+=1
                        if len(rows)!=1:entry['ambiguous']+=1
                        elif rows[0]['status']=='scored':entry['scored']+=1;entry['values'].append(rows[0]['value'])
                for key,decisions in sample_filters.items():
                    group=filters.setdefault(key,dict(context=json.loads(key),admitted=0,rejected=0,unknown=0,conflicting=0))
                    decision=decisions[0] if len(set(decisions))==1 else 'conflicting';group[decision]+=1
        for group in scores.values():
            for stage in group['stages'].values():
                values=stage.pop('values');stage['mean']=sum(values)/len(values) if values else None
        for group in uses.values():
            group['learner_steps']=sorted(group['learner_steps']);values=group.pop('advantages')
            group['advantage_mean']=sum(values)/len(values) if values else None;group['advantage_observed_uses']=len(values)
            group['masked_fraction']=1-group['loss_tokens']/group['model_tokens'] if group['model_tokens'] else None
        output[side]=dict(scores=list(scores.values()),filters=list(filters.values()),uses=list(uses.values()))
    return dict(windows=output,boundary='Scores use uniquely scored exact-joined samples with each component/definition kept separate. Members here have a record for that score component, not all generated samples. Selection and use omissions remain unknown in the population panel. Use counts retain reuse; backward and optimizer stages are separate. Token masking is measured only for uses with both model and loss token counts. This is not throughput, GPU-hours or causal gradient contribution.')


def capture(store,raw):
    allowed={'experiment','environment','baseline','current','monitor_ids','title','hypothesis','parent_id'}
    if not isinstance(raw,dict) or set(raw)-allowed:raise InputError('Unknown interval investigation fields')
    experiment=raw.get('experiment')
    if not isinstance(experiment,str) or not experiment.strip():raise InputError('Select one experiment')
    baseline=comparisons.window(raw.get('baseline'),'baseline');current=comparisons.window(raw.get('current'),'current')
    if baseline[1]>=current[0]:raise InputError('Baseline must end before the selected interval')
    environment=raw.get('environment') or None
    if environment is not None and not isinstance(environment,str):raise InputError('Invalid environment')
    title=raw.get('title') or f'Interval review · {current[0]}–{current[1]}'
    hypothesis=raw.get('hypothesis','')
    if not isinstance(title,str) or len(title)>120 or not isinstance(hypothesis,str) or len(hypothesis)>6000:raise InputError('Invalid research notes')
    if raw.get('parent_id'):
        parent=failure_investigations.read(store,raw['parent_id'])
        if parent['schema']!=VERSION or parent['scope']['experiment']!=experiment:raise InputError('Invalid interval parent')
    with store.read_snapshot() as saved:
        runs=m.scoped(m.population(saved),experiment,environment)
        selected=[r for r in runs if type(r['metadata'].get('training_step')) is int and any(lo<=r['metadata']['training_step']<=hi for lo,hi in (baseline,current))]
        if len(selected)>20000:raise InputError('Narrow the interval to at most 20,000 source rollouts')
        definitions=m.definitions(saved)
        requested=raw.get('monitor_ids')
        if requested is None:requested=[v['id'] for v in definitions if v['enabled']][:24]
        if not isinstance(requested,list) or len(requested)>24 or any(not isinstance(v,str) for v in requested) or len(set(requested))!=len(requested):raise InputError('Select at most 24 distinct monitors')
        by_id={v['id']:v for v in definitions}
        if any(v not in by_id for v in requested):raise InputError('Unknown monitor')
        panels=[]
        for mid in requested:
            comparison=comparisons.capture(saved,mid,baseline=baseline,current=current,experiment=experiment,environment=environment)
            panel={k:comparison[k] for k in ('monitor','aggregation','unit','cohorts','mix','review','population','limits')}
            panel['reliability']=reliability(saved,by_id[mid],[r for r in selected if m.in_population(by_id[mid],r)])
            panels.append(panel)
        # These shared panels use the entire selected source population, not
        # the first monitor's potentially narrower custom population.
        from . import training_lineage, comparison_lineage, generation_cohorts, telemetry_evidence
        windows={'baseline':baseline,'current':current}
        members={side:[r['id'] for r in selected if lo<=r['metadata']['training_step']<=hi] for side,(lo,hi) in windows.items()}
        training=training_lineage.snapshot(saved,experiment=experiment,environment=environment)
        lineage=comparison_lineage.capture(members,training)
        native_telemetry=telemetry_evidence.capture(saved,experiment=experiment,lineage=lineage)
        pending=generation_cohorts.project(saved,experiment=experiment,environment=environment,windows=windows,include_members=True,limit=1000)
        events=history(saved,experiment,environment)
        # Preserve exact outcomes and task composition even without a monitor.
        sources=[]
        with saved.connect() as c:
            for r in selected:
                source=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(r['id'],)).fetchone()[0])
                sources.append({**r,'outcome':source.get('outcome',{})})
        from .question_bundles import listing
        questions=listing(saved,experiment,environment)['questions']
        from .case_comparisons import capture as capture_cases
        snapshot=dict(captured_at=m.now(),scope=dict(experiment=experiment,environment=environment,baseline=baseline,current=current),
            population=members,source_rows=sources,case_evidence=capture_cases(saved,sources),panels=panels,training_lineage=lineage,declared_populations=pending,
            history=events,questions=questions,learning_context=learning_context(lineage,sources),native_telemetry=native_telemetry,excluded=dict(missing_coordinates=sum(type(r['metadata'].get('training_step')) is not int for r in runs),
                unselected_monitors=len(definitions)-len(requested)),
            clock_boundary='Windows select recorded source training coordinates. Configurations and clocks remain separate cohorts. Learner updates are joined through exact source revisions, not equal step numbers. Generation declarations retain their own clock; unaligned declarations cannot establish closure of this source population.')
    snapshot['snapshot_id']='interval-'+digest(snapshot)
    value=dict(schema=VERSION,title=title,hypothesis=hypothesis,hypothesis_status='Researcher hypothesis; not a verified cause',
        scope=snapshot['scope'],snapshot=snapshot,controls={**snapshot['scope'],'monitor_ids':requested},inference_calls=0,
        limits=['Frozen at capture. Late arrivals, corrected outcomes, new annotations and audits require an explicitly new comparison.',
                'A change in activity frequency is not improvement without outcome, task, budget and measurement context.',
                'Recorded success is not necessarily independent of the reward grader. Missing cost/resource records do not permit GPU-hour efficiency estimates.'])
    if raw.get('parent_id'):value['parent_id']=raw['parent_id']
    return value


def save(store,raw):
    return failure_investigations.persist(store,capture(store,raw))
