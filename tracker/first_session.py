"""Installed, repeatable example and evidence-backed entry points. No inference."""
from urllib.parse import urlencode

EXPERIMENT = 'Rilldex example · retry and recovery'
PRODUCER = 'rilldex-example-v1'


def example(store):
    from rilldex import TrainerTelemetry, chat_document
    from . import execution_records, monitoring
    messages = [
        dict(role='user', content='Fix parse_count so surrounding whitespace is accepted. Run the parser test.'),
        dict(role='assistant', content='The input contains whitespace. Inspect the parser and its test.',
             tool_calls=[dict(id='read', type='function', function=dict(name='read_file', arguments='{"path":"parser.py"}'))]),
        dict(role='tool', tool_call_id='read', content='def parse_count(text):\n    if not text.isdigit(): raise ValueError(text)\n    return int(text)'),
        dict(role='assistant', content='Strip whitespace before checking the digits.',
             tool_calls=[dict(id='edit', type='function', function=dict(name='edit_file', arguments='{"path":"parser.py","change":"text = text.strip()"}'))]),
        dict(role='tool', tool_call_id='edit', content='Updated parser.py: text = text.strip() before the isdigit check.'),
        dict(role='assistant', tool_calls=[dict(id='test1', type='function', function=dict(name='run_tests', arguments='{"command":"pytest tests/test_parser.py"}'))]),
        dict(role='tool', tool_call_id='test1', content='Infrastructure error: worker disconnected before tests started. No test result.'),
        dict(role='assistant', content='The test worker disconnected. Retry the same test on the replacement worker.',
             tool_calls=[dict(id='test2', type='function', function=dict(name='run_tests', arguments='{"command":"pytest tests/test_parser.py"}'))]),
        dict(role='tool', tool_call_id='test2', content='4 tests passed. Exit code 0.'),
        dict(role='assistant', content='The parser now accepts surrounding whitespace. The parser test suite passed.'),
    ]
    receipt = store.ingest(dict(producer=PRODUCER, rollout_id='parser-recovery', revision=0, state='complete',
        document=chat_document(messages, reward=1, success=True),
        metadata=dict(experiment=EXPERIMENT, environment='software', task_id='Parser whitespace',
                      training_step=12, training_step_basis='authored example learner update', split='train', synthetic=True)))
    logger = TrainerTelemetry(store, producer=PRODUCER, experiment=EXPERIMENT,
        framework='custom', framework_version='example-v1', objective='illustration', session='example',
        definitions={'reward': dict(label='Example reward', group='reward', unit='score', reduction='one example rollout',
                                   definition='Authored synthetic result; not measured training performance.')})
    logger.log({'reward': 1}, step=12, record_id='update-12')
    records = []
    for identifier, start, end, state, kind, extra in [
        ('test-first', 0, 8, 'failed', 'verification', {}),
        ('test-retry', 10, 15, 'completed', 'verification', {'retry_of':dict(producer=PRODUCER,id='test-first')}),
        ('learner-12', 17, 20, 'completed', 'learner_update', {'telemetry':[dict(producer=PRODUCER,id='update-12')]})]:
        records.append(dict(id=identifier, revision=0, state=state, kind=kind,
            rollout=dict(producer=PRODUCER,id='parser-recovery'), source_revision=0,
            context=dict(worker='Learner' if kind=='learner_update' else 'Test worker'),
            timing=dict(clock='example/shared-seconds',start=start,end=end),
            evidence='Authored example timing; not measured execution.', **extra))
    execution_records.receive(store, dict(schema=execution_records.TIMELINE_VERSION,
        producer=PRODUCER, experiment=EXPERIMENT, records=records))
    monitoring.seed(store)
    return dict(experiment=EXPERIMENT, run_id=receipt['id'], synthetic=True,
                url='/?'+urlencode(dict(experiment=EXPERIMENT)), inference_calls=0)


def readiness(store, *, experiment=None, environment=None, run_ids=None, graphs=None):
    """Describe available inputs, not scientific validity or adapter quality."""
    from .monitoring import population, scoped
    from . import graph_store
    runs = scoped(population(store), experiment, environment)
    if run_ids is not None:
        wanted=set(run_ids); runs=[r for r in runs if r['id'] in wanted]
    ids={r['id'] for r in runs}
    coordinates=sum(type(r['metadata'].get('training_step')) is int and bool(r['metadata'].get('experiment')) and bool(r['metadata'].get('training_step_basis')) for r in runs)
    # Reuse the same saved graph inventory as the overview, including archived
    # observations whose original worker directory is no longer available.
    if graphs is None:graphs=graph_store.catalog(store)['graphs']
    from . import map_selection
    maps=[g for g in graphs if g['run_id'] in ids and map_selection.semantic(g)]
    semantic={g['run_id'] for g in maps}
    with store.connect() as c:
        conditions=[];args=[]
        if experiment:conditions.append('experiment=?');args.append(experiment)
        if run_ids is not None:
            experiments=sorted({r['metadata']['experiment'] for r in runs if r['metadata'].get('experiment')})
            conditions.append('experiment IN ('+','.join('?' for _ in experiments)+')' if experiments else '0')
            args.extend(experiments)
        where=' WHERE '+' AND '.join(conditions) if conditions else ''
        telemetry_where=where
        execution_where=where
        if environment:
            telemetry_where+=(' AND ' if where else ' WHERE ')+"json_extract(document,'$.environment')=?"
            execution_where+=(' AND ' if where else ' WHERE ')+"json_extract(document,'$.context.environment')=?"
            args.append(environment)
        telemetry=c.execute('SELECT count(*) FROM trainer_telemetry'+telemetry_where,args).fetchone()[0]
        execution=c.execute('SELECT count(*) FROM execution_records'+execution_where,args).fetchone()[0]
        total=c.execute('SELECT count(*) FROM runs').fetchone()[0]
        facts=c.execute('SELECT (SELECT count(*) FROM trainer_telemetry)+(SELECT count(*) FROM execution_records)+(SELECT count(*) FROM training_records)+(SELECT count(*) FROM training_sample_records)').fetchone()[0]
    def row(identifier,label,count,missing,url,detail):
        needs={'source':'needs_source','training':'needs_metadata','semantic':'awaiting_annotations','telemetry':'needs_telemetry','execution':'needs_timing'}
        return dict(id=identifier,label=label,state='available' if count else needs[identifier],
                    count=count,detail=detail if count else missing,url=url)
    scope_values={k:v for k,v in dict(experiment=experiment,environment=environment).items() if v}
    if run_ids is not None and runs and len({r['metadata'].get('experiment') for r in runs})==1 and runs[0]['metadata'].get('experiment'):
        scope_values['experiment']=runs[0]['metadata']['experiment']
    scope='?'+urlencode(scope_values) if scope_values else ''
    views='&' if scope else '?'
    features=[
        row('source','Source inspection',len(runs),'Import a rollout or connect an output directory.','/runs'+scope,
            f'{len(runs)} rollouts available to inspect.'),
        row('training','Rollout trends',coordinates,'Add experiment, training_step and training_step_basis metadata to place rollouts on the training axis.',
            '/'+scope+views+'view=measures',f'{coordinates} / {len(runs)} rollouts have training coordinates.'),
        row('semantic','Semantic maps',len(semantic),'Run a bounded model pilot for activities and relationships.',
            '/connections#model-section',f'{len(semantic)} / {len(runs)} rollouts have saved semantic observations. Coverage varies by layer.'),
        row('telemetry','Trainer signals',telemetry,'Connect your trainer logger to capture native signals.',
            '/'+scope+views+'view=health',f'{telemetry} recorded trainer logs. Definitions come from the trainer.'),
        row('execution','Execution timeline',execution,'Capture operation start/end times and a shared clock.',
            '/'+scope+views+'view=execution',f'{execution} execution records. Timing coverage depends on the source.'),
    ]
    if len(runs)==1:
        features[0]['url']='/semantic-map?'+urlencode(dict(run=runs[0]['id'],observer='source',level='units'))
        features[2]['url']='/connections?'+urlencode(dict(model_run=runs[0]['id']))+'#model-section'
    if maps:
        selected=map_selection.default(maps)
        features[2]['url']='/semantic-map?'+urlencode(dict(run=selected['run_id'],observer=selected['observer'],graph=selected['id'],level='units'))
    example_run=next((r['id'] for r in runs if r['metadata'].get('experiment')==EXPERIMENT and r['metadata'].get('synthetic')),None)
    return dict(schema='feature-readiness/1', empty=total+facts==0, features=features,
                rollouts=len(runs), inference_calls=0, example=experiment==EXPERIMENT and bool(example_run),example_run=example_run)
