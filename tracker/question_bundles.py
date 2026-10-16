"""Monitor presets over existing, versioned definitions. No inference or auto-tuning."""
from copy import deepcopy
from .schema import InputError
from . import monitoring

QUESTIONS = [
    dict(id='comparable-performance', title='Outcomes',
         description='Recorded reward and success, with task and population coverage.',
         needs=['Task IDs, train/eval split and generation coordinates', 'Stable task, environment, reward and sampling definitions', 'Explicit outcomes; completed and pending population counts'],
         metrics=['recorded_success','recorded_reward'], measures=[],
         reading='Charts use the selected experiment and environment. Task identity, training coordinates and missing outcomes appear in input coverage.'),
    dict(id='selection-delay', title='Selection & delivery',
         description='Reward and success alongside selection, learner-use and generation records.',
         needs=['Declared generation membership including unfinished work', 'Exact sample-to-source revision joins', 'Named filter decisions and recorded learner use'],
         metrics=['recorded_reward','recorded_success'], measures=[],
         reading='Input coverage lists recorded selection and learner use. Missing records remain unknown; they are not counted as rejected samples.'),
    dict(id='recovery', title='Recovery',
         description='Results after revisions, repeated failures and incomplete follow-up.',
         needs=['Visible failure and same-work links', 'An expressed change linked to its executing action', 'Comparable check results, input versions and follow-up coverage'],
         metrics=['enacted_revision_completion_fraction','enacted_revision_unknown_fraction'],
         measures=['criterion_recovery_window','next_check_success_changed','repeated_failed_checks','incomplete_recovery_followup'],
         reading='Operation completion and criterion recovery have separate charts. Open a rollout value to see its linked attempt, revision and result.'),
    dict(id='reward-outcomes', title='Reward checks',
         description='Recorded reward, success and verification before delivery.',
         needs=['Reward component and grader definition/version', 'Independent outcome provenance on the same samples', 'Comparable population and missing-pair counts'],
         metrics=['recorded_reward','recorded_success'], measures=['delivery_verification'],
         reading='Source success is not an independent evaluation. Evaluator provenance is shown separately when recorded.'),
    dict(id='compute-progress', title='Effort & progress',
         description='Action counts, attempted plan steps, deferred work and verification.',
         needs=['Recorded tokens, cost or time with consistent units', 'Comparable tasks and explicit progress/outcome evidence', 'Final modification, applicable verification and unfinished work'],
         metrics=['actions','recorded_success'], measures=['delivery_verification','incomplete_recovery_followup','plan_steps_attempted','work_defer_decisions'],
         reading='This preset counts recorded actions and work events, not compute cost. Attempted steps and deferred work retain their recorded status.'),
]


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS monitor_question_bindings(question_id TEXT NOT NULL, monitor_id TEXT NOT NULL, PRIMARY KEY(question_id,monitor_id))')


def question(identifier):
    item=next((q for q in QUESTIONS if q['id']==identifier),None)
    if item is None: raise InputError('Unknown monitor question')
    return item


def listing(store,experiment=None,environment=None):
    with store.read_snapshot() as saved:return _listing(saved,experiment,environment)


def _listing(store,experiment=None,environment=None):
    from .analysis_metrics import catalog
    from .rollout_metrics import DEFINITIONS
    measure_names={k:v['label'] for k,v in catalog().items()}
    measure_names.update({k:v[0] for k,v in DEFINITIONS.items()})
    definitions=monitoring.definitions(store)
    with store.connect() as c:
        links=list(c.execute('SELECT question_id,monitor_id FROM monitor_question_bindings'))
    runs=monitoring.scoped(monitoring.population(store),experiment,environment);available={}
    for monitor in definitions:
        eligible=[r for r in runs if monitoring.in_population(monitor,r)]
        values=monitoring.current_values(store,monitor,eligible);ids={r['id'] for r in eligible}
        available[monitor['id']]={'eligible':len(eligible),'measured':sum(v.get('value') is not None for rid,v in values.items() if rid in ids)}
    from . import training_lineage
    training=training_lineage.snapshot(store,experiment=experiment,environment=environment)
    samples=training['samples'];joined=[s for s in samples if s['join_status']=='matched']
    with store.connect() as c:
        declarations=c.execute("SELECT count(*) FROM generation_cohorts WHERE (? IS NULL OR experiment=?)",(experiment,experiment)).fetchone()[0]
    facts={'sources':len(runs),'task_ids':sum(bool(r['metadata'].get('task_id')) for r in runs),
        'coordinates':sum(type(r['metadata'].get('training_step')) is int and bool(r['metadata'].get('training_clock')) and bool(r['metadata'].get('training_step_basis')) for r in runs),
        'declared_generations':declarations,'samples':len(samples),'joined_samples':len(joined),
        'selected_samples':sum(bool(s['records']) and any(r['kind']=='selection' for r in s['records']) for s in joined),
        'used_samples':sum(any(r['kind']=='use' for r in s['records']) for s in joined)}
    requirements=[dict(label='Task identity',observed=facts['task_ids'],total=len(runs)),
        dict(label='Explicit coordinate, clock and basis',observed=facts['coordinates'],total=len(runs)),
        dict(label='Sample/source joins',observed=len(joined),total=len(samples))]
    result=[]
    for q in QUESTIONS:
        linked={r[1] for r in links if r[0]==q['id']}
        matches=[m for m in definitions if m['id'] in linked or
                 m.get('metric') in q['metrics'] or m.get('analysis',{}).get('measure') in q['measures']]
        checks=deepcopy(requirements)
        if q['id']=='selection-delay':checks += [dict(label='Selection receipts on joined samples',observed=facts['selected_samples'],total=len(joined)),dict(label='Learner-use receipts on joined samples',observed=facts['used_samples'],total=len(joined)),dict(label='Generation declarations (experiment scope)',observed=declarations,total=None)]
        if q['id']=='reward-outcomes':checks.append(dict(label='Independence of outcome evaluator from reward grader',status='not established by source-success fields'))
        if q['id']=='compute-progress':checks.append(dict(label='GPU-hour accounting with comparable evaluation',status='not computed; resource allocation evidence required'))
        missing=[key for key in q['metrics']+q['measures'] if not any(
            m.get('metric')==key or m.get('analysis',{}).get('measure')==key for m in matches)]
        result.append({**deepcopy(q),'monitors':matches,'readiness':checks,'measurement_coverage':{m['id']:available[m['id']] for m in matches},
            'missing_measures':missing,'missing_measure_labels':[measure_names.get(k,k) for k in missing],
            'status':'configured_evidence_not_validated' if matches else 'not_configured'})
    return {'questions':result,'boundary':'Configuration is not evidence readiness. The interval investigation shows actual coverage, missing inputs and audit results.'}


def bind(store,raw):
    if not isinstance(raw,dict) or set(raw)!={'question_id','monitor_id'}: raise InputError('Supply question_id and monitor_id')
    question(raw['question_id'])
    if not isinstance(raw['monitor_id'],str):raise InputError('Unknown monitor')
    if raw['monitor_id'] not in {m['id'] for m in monitoring.definitions(store)}: raise InputError('Unknown monitor')
    with store.connect() as c:c.execute('INSERT OR IGNORE INTO monitor_question_bindings VALUES (?,?)',(raw['question_id'],raw['monitor_id']))
    return {'question_id':raw['question_id'],'monitor_id':raw['monitor_id'],'bound':True}


def activate(store,raw):
    if not isinstance(raw,dict) or set(raw)-{'question_id','observer','experiment','environment'}: raise InputError('Unknown question setup fields')
    q=question(raw.get('question_id'));observer=raw.get('observer')
    if observer is not None and (not isinstance(observer,str) or not observer):raise InputError('Choose an observation protocol')
    if observer and observer!='source':
        from .graph_store import catalog as graph_catalog
        if observer not in {g['observer'] for g in graph_catalog(store)['graphs']}:raise InputError('Choose a saved observation protocol')
    from .analysis_metrics import catalog
    from .analysis_contracts import registered
    from .rollout_metrics import DEFINITIONS
    population={k:raw[k] for k in ('experiment','environment') if raw.get(k)}
    planned=[];skipped=[]
    for key in q['metrics']+q['measures']:
        source=key in {'recorded_reward','recorded_success','actions'}
        spec=catalog().get(key)
        if spec:source='source' in registered()[spec['operation']]['observer_input']['accepted']
        selected='source' if source else observer
        if not selected or selected=='source' and not source:
            skipped.append({'measure':key,'reason':'Select a semantic observation protocol with compatible evidence'});continue
        item=dict(name=spec['label'] if spec else DEFINITIONS[key][0],kind='analysis' if spec else 'metric',observer=selected,group='Behavior' if spec or not source else 'Training')
        item.update({'analysis':{'measure':key}} if spec else {'metric':key})
        if population:item['population']=population
        planned.append(monitoring.validate(item))
    created=[];existing=monitoring.definitions(store)
    def identity(d):return {k:v for k,v in d.items() if k not in {'id','enabled','name','group','schema'}}
    for item in planned:
        m=next((d for d in existing if identity(d)==identity(item)),None)
        if m is None:m=monitoring.create(store,item);existing.append(m)
        created.append(m['id'])
        bind(store,{'question_id':q['id'],'monitor_id':m['id']})
    return {'monitor_ids':created,'skipped':skipped,'inference_calls':0}
