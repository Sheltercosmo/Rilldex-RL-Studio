"""Review binary code monitors against frozen inputs, without showing their outputs.

One case is one rollout. Sampling includes negative and unresolved results; it
does not turn a source-bound result or a developer judgment into ground truth.
"""
from copy import deepcopy
import json

from .schema import InputError, digest
from . import monitor_evidence, monitoring


def require(condition, message):
    if not condition: raise InputError(message)


def supported(definition):
    return (definition['kind'] == 'custom' and definition['custom']['aggregation'] == 'incidence' or
            definition['kind'] == 'metric' and definition.get('metric','').startswith('diagnostic_'))


def question(definition):
    if definition['kind']=='custom':return definition['custom']['description']
    from .rollout_metrics import DEFINITIONS
    return DEFINITIONS[definition['metric']][1]


def frame_row(receipt, measurement_id):
    value = receipt['measurement']
    require('value-'+digest({k:v for k,v in value.items() if k not in {'id','created_at'}}) == measurement_id,
            'Measurement identity differs')
    state = ((value.get('details') or {}).get('detector') or {}).get('status')
    require(value['value'] is None or value['value'] in (0,1), 'A binary review requires 0, 1 or an unavailable result')
    prediction = None if value['value'] is None else bool(value['value'])
    item = dict(measurement_id=measurement_id, run_id=receipt['run']['id'],
                case_id='rollout', case_hash=digest(value), prediction=prediction,
                predicted_scope='outside' if state == 'not_applicable' else 'unresolved' if prediction is None else 'inside')
    item['id'] = 'review-case-' + digest(item)
    return item


def create(store, definition, ids, size, seed, version):
    with store.read_snapshot() as saved:
        with saved.connect() as c:
            selected = {r[0]:json.loads(r[1]) for r in c.execute('SELECT id,document FROM runs') if r[0] in set(ids)}
        require(set(ids) <= set(selected), 'Unknown rollout in review cohort')
        require(all(monitoring.in_population(definition, r) for r in selected.values()), 'Rollout outside the monitor population')
        current = [r for r in monitoring.population(saved) if r['id'] in selected]
        values = monitoring.current_values(saved, {**definition, 'id':'monitor-'+digest(definition)}, current)
        with saved.connect() as c:
            dates = dict(c.execute('''SELECT v.id,v.created_at FROM monitor_latest l JOIN monitor_values v ON v.id=l.value_id
                WHERE l.monitor_id=?''',('monitor-'+digest(definition),)))
        frame = []
        for rid in sorted(ids):
            value = values.get(rid)
            if not value or not value.get('id') or not value.get('input_id'): continue
            receipt = {'run':selected[rid], 'measurement':{**value, 'created_at':dates[value['id']]}}
            frame.append(frame_row(receipt, value['id']))
        require(frame, 'No current saved results in this cohort; run the code monitor first')
        frame.sort(key=lambda r:r['id'])
        picked = sorted(frame, key=lambda r:(digest([seed,r['id']]),r['id']))[:size]
        # Reconstruct expensive graph and input receipts only for sampled cases.
        for row in picked:
            receipt = monitor_evidence.read(saved,row['measurement_id'])
            require(frame_row(receipt,row['measurement_id']) == row and receipt['freshness']['current_input'],
                    'Review result differs from current evidence')
    return dict(schema=version, review_kind='rollout_condition', condition_question=question(definition), monitor_id='monitor-'+digest(definition), monitor=definition,
        run_ids=sorted(ids), measurement_ids=sorted(r['measurement_id'] for r in frame),
        runs_without_case_frame=sorted(set(ids)-{r['run_id'] for r in frame}), frame=frame, frame_hash=digest(frame),
        sample_ids=[r['id'] for r in picked], evidence_scopes={r['id']:None for r in picked}, requested_size=size, seed=seed,
        selection='Uniform deterministic hash ordering over current saved rollout results in the supplied cohort, regardless of outcome.',
        limits='One case per rollout with a current saved result. Missing results are excluded and counted. '
               'Agreement is conditional on decidable judgments; this is not population-wide accuracy. Reviewer independence is self-declared.')


def packet(receipt, row):
    require(frame_row(receipt,row['measurement_id']) == row, 'Review result differs from frozen evidence')
    source = [{k:deepcopy(e[k]) for k in ('id','index','actor','kind','text','trajectory_id','context_id',
              'source_pointer','agent_visibility','copied_context','tool','arguments') if k in e} for e in receipt['run']['events']]
    # No result-selected excerpts: reviewers see the complete saved source.
    return source, set(), []


def inputs(store, receipt):
    from .reward_detectors import lookup, MISSING
    from .monitor_evaluation_inputs import pinned
    if receipt['monitor']['kind']!='custom':
        return dict(declared_inputs=[],evaluator_inputs={},evaluator_reports=[],
                    monitor_configuration={k:receipt['monitor'][k] for k in ('metric','observer')})
    spec = receipt['monitor']['custom']; record = receipt['input_record']; run = receipt['run']
    detector = spec.get('config',{}).get('reward_detector')
    declared = []
    if detector:
        paths={'@reward_definition':detector['definition_path'],**detector['inputs']}
        for name,path in paths.items():
            value = lookup(run,path)
            declared.append(dict(name=name,pointer=path,present=value is not MISSING,
                                 **({'value':deepcopy(value)} if value is not MISSING else {})))
    selected = pinned(store,spec,run['id'],receipt['measurement']['source_hash'],record['dependencies'])
    reports = {r['id']:r for rows in selected.values() for r in rows}
    return dict(declared_inputs=declared, evaluator_inputs={k:[r['id'] for r in rows] for k,rows in selected.items()},
        evaluator_reports=[reports[k] for k in sorted(reports)],
        monitor_configuration=deepcopy(spec.get('config',{})))


def citation(ref, data):
    """Additional citation types, validated against original inputs, never result details."""
    if set(ref) == {'input_name'}:
        item = next((r for r in data['declared_inputs'] if r['name'] == ref['input_name']),None)
        require(item is not None, 'Input citation is outside the declared review inputs')
        return {**ref, 'input':deepcopy(item)}
    if set(ref) == {'evaluation_id'}:
        item = next((r for r in data['evaluator_reports'] if r['id'] == ref['evaluation_id']),None)
        require(item is not None, 'Evaluator citation is outside the pinned review inputs')
        return {**ref, 'report_hash':digest(item)}
    if set(ref) == {'evaluator_input'}:
        name = ref['evaluator_input']
        require(isinstance(name,str) and name in data['evaluator_inputs'], 'Evaluator selection is outside the declared review inputs')
        return {**ref, 'evaluation_ids':data['evaluator_inputs'][name]}
    raise InputError('Cite a source span, declared input, evaluator report or evaluator input selection')
