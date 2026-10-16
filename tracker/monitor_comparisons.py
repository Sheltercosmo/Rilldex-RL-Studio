"""Immutable, cohort-aware window comparisons of saved monitor receipts.

No inference, causal attribution or implicit success threshold. One WAL snapshot
binds the population, observation identities and receipts. Late data belongs to
a new comparison; it never rewrites a researcher's earlier result.
"""
from collections import Counter
import json
import math

from . import monitoring as m
from . import population_readiness
from . import execution_records
from . import generation_cohorts
from . import comparison_lineage, training_lineage
from .schema import InputError, digest, dumps

VERSION = 'monitor-comparison/4'
MAX_ROWS = 100000


def window(value, name):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(n) is not int or n < 0 for n in value) or value[0] > value[1]):
        raise InputError(name+' must be [first_step, last_step], inclusive nonnegative integers')
    return list(value)


def summarize(points, aggregation):
    known = [p for p in points if type(p.get('value')) in (int, float) and math.isfinite(p['value'])]
    ratio = aggregation in {'anchor_ratio', 'opportunity_ratio'}
    numerator = sum(p.get('numerator') or 0 for p in known) if ratio else None
    denominator = sum(p.get('denominator') or 0 for p in known) if ratio else None
    if ratio and any(type(p.get('denominator')) not in (int, float) or p['denominator'] <= 0
                     or type(p.get('numerator')) not in (int, float) for p in known):
        raise InputError('A ratio receipt has no valid numerator/denominator; inspect the measure before comparing')
    value = (numerator / denominator if denominator else None) if ratio else (
        sum(p['value'] for p in known) / len(known) if known else None)
    return dict(value=value, total=len(points), measured=len(known), missing=len(points)-len(known),
        numerator=numerator, denominator=denominator, weight=denominator if ratio else len(known),
        coverage=len(known)/len(points) if points else None,
        readiness=population_readiness.summarize(points),
        statuses=dict(Counter(p['status'] for p in points)),
        opportunities=sum(p.get('opportunities') or 0 for p in points),
        unknown_opportunities=sum(p.get('unknown_opportunities') or 0 for p in points))


def delta(a, b):
    return b-a if a is not None and b is not None else None


def task_mix(a, b, by_id):
    counts = [Counter(by_id[p['run_id']]['metadata'].get('task_id') for p in ps) for ps in (a,b)]
    totals = [len(a),len(b)]
    distance = (sum(abs(counts[0][k]/totals[0]-counts[1][k]/totals[1])
                    for k in counts[0].keys() | counts[1].keys())/2 if all(totals) else None)
    return dict(recorded_task_mix_distance=distance,
                missing_task_ids=[c.get(None,0) for c in counts],
                distinct_tasks=[len(c.keys()-{None}) for c in counts])


def mix_summary(cohorts, aggregation):
    # Only environment strata may vary. Never pool train/eval, generation/use
    # clocks, reward definitions or sampling configurations into a single trend.
    contexts = {dumps({k:v for k,v in row['cohort'].items()
                      if k not in {'environment','environment_version'}}) for row in cohorts}
    if len(contexts) != 1:
        return dict(available=False, reason='Multiple configurations or clocks; compare their cohorts separately.')
    if not cohorts or any(row['baseline']['value'] is None or row['current']['value'] is None for row in cohorts):
        return dict(available=False, reason='Every environment stratum needs measured evidence in both windows.')
    weights = [sum(row[side]['weight'] for row in cohorts) for side in ('baseline','current')]
    a = sum(row['baseline']['value']*row['baseline']['weight'] for row in cohorts)/weights[0]
    b = sum(row['current']['value']*row['current']['weight'] for row in cohorts)/weights[1]
    standardized = sum(row['current']['value']*row['baseline']['weight'] for row in cohorts)/weights[0]
    return dict(available=True, baseline=a, current=b, observed_delta=b-a,
        current_at_baseline_mix=standardized, within_cohort_delta=standardized-a,
        composition_component=b-standardized,
        weighting='decidable opportunities' if aggregation in {'anchor_ratio','opportunity_ratio'} else 'measured rollouts',
        boundary='Descriptive reweighting, not causal attribution. Missing evidence and unrecorded task/configuration changes can still explain differences.')


def capture(store, monitor_id, *, baseline, current, experiment, environment=None):
    baseline, current = window(baseline,'baseline'), window(current,'current')
    if baseline[1] >= current[0]:raise InputError('Baseline must end before the current window starts')
    if not isinstance(experiment,str) or not experiment.strip():raise InputError('Select one experiment before comparing training windows')
    if environment is not None and (not isinstance(environment,str) or not environment.strip()):raise InputError('Environment must be nonempty text or omitted')
    with store.read_snapshot() as saved:
        monitor = next((d for d in m.definitions(saved) if d['id']==monitor_id),None)
        if monitor is None:raise KeyError(monitor_id)
        runs = [r for r in m.scoped(m.population(saved),experiment,environment) if m.in_population(monitor,r)]
        by_id = {r['id']:r for r in runs}
        selected = [r for r in runs if type(r['metadata'].get('training_step')) is int and any(
            lo <= r['metadata']['training_step'] <= hi for lo,hi in (baseline,current))]
        if len(selected)>MAX_ROWS:raise InputError('Comparison exceeds 100,000 rollouts; select smaller windows or one environment')
        rows = m.current_values(saved,monitor,selected)
        chart = m.chart(monitor,selected,rows)
        state = saved.connection.execute("SELECT document FROM monitor_service WHERE id='last_sync'").fetchone()
        sync = json.loads(state[0]) if state else None
        captured_at = m.now()
        executions = execution_records.overview(saved,experiment,environment)
        declarations = generation_cohorts.project(saved,experiment=experiment,environment=environment,
            monitor=monitor_id,windows={'baseline':baseline,'current':current},include_members=True)
        training = comparison_lineage.capture({name:[r['id'] for r in selected
            if lo<=r['metadata']['training_step']<=hi] for name,(lo,hi) in
            [('baseline',baseline),('current',current)]},
            training_lineage.snapshot(saved,experiment=experiment,environment=environment))
        chart_runs={r['id']:r for r in selected};declaration_alignment=[]
        for declaration in declarations['cohorts']:
            bound=[chart_runs[case['run_id']]['metadata'] for case in declaration['members'] if case['run_id'] in chart_runs]
            clocks={(meta.get('training_clock'),meta.get('training_step_basis')) for meta in bound}
            expected=(declaration['coordinate']['clock'],declaration['coordinate']['basis'])
            status=('unverified_clock' if not clocks or any(None in clock for clock in clocks) else
                'matching_clock' if clocks=={expected} else 'mixed_clocks' if expected in clocks else 'different_clock')
            declaration_alignment.append(dict(producer=declaration['producer'],id=declaration['id'],status=status,
                members_in_source_windows=len(bound)))
        # The projector receipt binds its inputs. Comparison-only alignment is
        # part of the enclosing saved comparison, not that projector receipt.
    cohorts = []
    for series in chart['series']:
        points = series['points']
        a,b = [[p for p in points if lo<=p['step']<=hi] for lo,hi in (baseline,current)]
        left,right = summarize(a,chart['aggregation']),summarize(b,chart['aggregation'])
        cohorts.append(dict(id='cohort-'+digest(series['cohort']),cohort=series['cohort'],
            baseline=left,current=right,delta=delta(left['value'],right['value']),
            coverage_change=delta(left['coverage'],right['coverage']),
            task_mix=task_mix(a,b,by_id),points=dict(baseline=a,current=b)))
    core = dict(schema=VERSION,captured_at=captured_at,monitor=monitor,
        scope=dict(experiment=experiment,environment=environment,baseline=baseline,current=current),
        aggregation=chart['aggregation'],unit=chart['unit'],cohorts=cohorts,
        mix=mix_summary(cohorts,chart['aggregation']),last_sync=sync,
        review=generation_cohorts.review(declarations)+population_readiness.review(cohorts),
        execution_context=executions,
        training_lineage=training,
        declared_populations=declarations,
        declared_population_alignment=declaration_alignment,
        population=dict(selected=len(selected),outside_windows=len(runs)-len(selected),
            missing_coordinates=sum(type(r['metadata'].get('training_step')) is not int or r['metadata'].get('training_step',-1)<0 for r in runs)),
        limits=['Uses latest source revisions at capture; incomplete, pending and unknown evidence remains missing.',
            'Differences describe recorded behavior, not statistical significance or causes. Inspect coverage and task mix before interpreting them.',
            'Cohort matching uses recorded fields. Missing metadata does not prove equivalent settings.',
            'Observed-source coverage does not establish population closure. Declared membership, generation state and outcome availability are shown separately when supplied.',
            'Source success, reward, attempted rechecks and semantic revisions retain their separate definitions.'])
    return dict(id='comparison-'+digest(core),**core)


def save(store, monitor_id, **options):
    result = capture(store,monitor_id,**options)
    # The source snapshot is released before the write; it cannot be silently
    # refreshed by a producer arriving between capture and publication.
    with store.connect() as c:
        c.execute('INSERT OR IGNORE INTO monitor_comparisons VALUES (?,?,?)',
                  (result['id'],dumps(result),result['captured_at']))
    return result


def read(store, identifier):
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_schema WHERE name='monitor_comparisons'").fetchone():raise KeyError(identifier)
        row = c.execute('SELECT document FROM monitor_comparisons WHERE id=?',(identifier,)).fetchone()
    if row is None:raise KeyError(identifier)
    result = json.loads(row[0])
    if result.get('schema') not in {'monitor-comparison/1','monitor-comparison/2',VERSION} or result.get('id')!='comparison-'+digest({k:v for k,v in result.items() if k!='id'}):
        raise InputError('Saved comparison integrity check failed')
    return result


def listing(store, experiment=None, observer=None):
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_schema WHERE name='monitor_comparisons'").fetchone():return dict(comparisons=[],limit=100)
        rows=c.execute('''SELECT id,created_at,json_extract(document,'$.monitor.name') name,
            json_extract(document,'$.scope') scope FROM monitor_comparisons
            WHERE (? IS NULL OR json_extract(document,'$.scope.experiment')=?)
              AND (? IS NULL OR json_extract(document,'$.monitor.observer')=?)
            ORDER BY created_at DESC,id LIMIT 100''',(experiment,experiment,observer,observer)).fetchall()
    return dict(comparisons=[dict(id=r['id'],created_at=r['created_at'],name=r['name'],scope=json.loads(r['scope'])) for r in rows],limit=100)
