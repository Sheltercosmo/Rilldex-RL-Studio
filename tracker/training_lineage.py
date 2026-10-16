"""Immutable producer facts joining training populations to rollout evidence.

Records may arrive before their source or in reverse revision order. Absence
never establishes rejection/non-use. No optimizer facts are inferred from text.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math

from .schema import InputError, digest, dumps
from . import training_samples, training_token_context, training_recipes, teacher_signals, policy_gradients, regression_signals, value_observations

VERSION = 'training-records/1'
KINDS = {'sample', 'score', 'selection', 'use', 'supervision'}


def initialize(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS training_records (
      producer TEXT NOT NULL, experiment TEXT NOT NULL, record_id TEXT NOT NULL,
      revision INTEGER NOT NULL, kind TEXT NOT NULL, sample_producer TEXT NOT NULL,
      rollout_id TEXT NOT NULL, document TEXT NOT NULL, received_at TEXT NOT NULL,
      PRIMARY KEY(producer,experiment,record_id,revision));
    CREATE INDEX IF NOT EXISTS training_sample_join ON training_records(experiment,sample_producer,rollout_id);
    CREATE INDEX IF NOT EXISTS training_source_declaration ON training_records(
      sample_producer,rollout_id,json_extract(document,'$.evidence.source_revision'),experiment)
      WHERE kind='sample';
    ''')
    training_samples.initialize(c)
    training_recipes.initialize(c)
    from .continuation_studies import initialize as initialize_continuations
    initialize_continuations(c)


def text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise InputError(name + ' must be a nonempty string of at most 500 characters')
    return value


def integer(value, name):
    if type(value) is not int or value < 0:
        raise InputError(name + ' must be a nonnegative integer')


def validate(packet):
    if not isinstance(packet, dict) or set(packet) != {'schema', 'producer', 'experiment', 'records'} or packet['schema'] not in {VERSION,training_samples.VERSION}:
        raise InputError('Use training-records/1 or training-records/2 with producer, experiment and records')
    independent=packet['schema']==training_samples.VERSION
    text(packet['producer'], 'producer'); text(packet['experiment'], 'experiment')
    records = packet['records']
    if not isinstance(records, list) or not 1 <= len(records) <= 1000:
        raise InputError('Supply 1–1,000 training records')
    identities = set()
    for r in records:
        if not isinstance(r, dict) or set(r) != {'id', 'revision', 'kind', 'sample', 'evidence', 'data'}:
            raise InputError('A training record needs id, revision, kind, sample, evidence and data')
        text(r['id'], 'record id'); integer(r['revision'], 'revision')
        if (r['id'], r['revision']) in identities: raise InputError('Duplicate record identity in packet')
        identities.add((r['id'], r['revision']))
        if r['kind'] not in KINDS: raise InputError('Unsupported training record kind')
        if r['kind'] in {'sample', 'use', 'supervision'} and r['revision'] != 0:
            raise InputError('Samples, supervision observations and individual uses are immutable revision zero records')
        if r['kind'] == 'supervision' and not independent:
            raise InputError('Supervision requires independent training-records/2 sample identity')
        s = r['sample']
        if not isinstance(s, dict) or set(s) != {'producer', 'id' if independent else 'rollout_id'}:
            raise InputError('Sample reference requires producer and '+('id' if independent else 'rollout_id'))
        for k, v in s.items(): text(v, k)
        e = r['evidence']
        if not isinstance(e, dict) or set(e) - {'basis', 'source_revision'} or 'basis' not in e:
            raise InputError('Evidence requires basis and optional source_revision')
        text(e['basis'], 'evidence basis')
        if 'source_revision' in e: integer(e['source_revision'], 'source_revision')
        if independent and 'source_revision' in e:raise InputError('Version 2 pins its source revision in sample data.source')
        d = r['data']
        if not isinstance(d, dict): raise InputError('Record data must be an object')
        required, optional = {
            'sample': ({'split'}, {'display_name', 'task_id', 'group_id', 'group_size', 'policy_version', 'step', 'step_basis', 'environment', 'environment_version', 'recipe', 'policy_history', 'attempt'}),
            'score': ({'component', 'definition', 'status', 'value'}, {'attempt_outcome'}),
            'selection': ({'filter', 'definition', 'decision', 'batch_id'}, {'reason'}),
            'use': ({'batch_id', 'learner_step', 'stage'}, {'advantage', 'model_tokens', 'loss_tokens', 'recipe', 'policy_gradient', 'learner_policy', 'regression', 'value_observation'}),
            'supervision': ({'recipe', 'component', 'step', 'step_basis', 'stage', 'boundary', 'signal'}, set()),
        }[r['kind']]
        if independent and r['kind']=='sample':optional=optional|{'source','interaction_ids','token_context','episode','continuation','generation_context'}
        if not required <= set(d) or set(d) - required - optional:
            raise InputError('Invalid fields for ' + r['kind'])
        for k in set(d) - {'step', 'group_size', 'value', 'advantage', 'learner_step', 'model_tokens', 'loss_tokens','source','interaction_ids','token_context','episode','recipe','signal','policy_gradient','policy_history','learner_policy','attempt','attempt_outcome','regression','value_observation','continuation','generation_context'}:
            text(d[k], k)
        for k in ('step', 'learner_step', 'model_tokens', 'loss_tokens'):
            if k in d: integer(d[k], k)
        if ('step' in d) != ('step_basis' in d): raise InputError('step and step_basis must be supplied together')
        if 'group_size' in d and (type(d['group_size']) is not int or d['group_size'] < 1 or 'group_id' not in d):
            raise InputError('group_size requires group_id and a positive integer expected membership')
        if r['kind'] == 'sample' and d['split'] not in {'train', 'evaluation'}:
            raise InputError('Sample split must be train or evaluation')
        if independent and r['kind']=='sample':training_samples.validate_mapping(d,text,integer)
        if 'token_context' in d:training_token_context.validate(d['token_context'])
        if 'generation_context' in d:
            training_token_context.validate_generation(d['generation_context'])
            if 'token_context' in d:
                gc=d['generation_context'];tc=d['token_context']
                if gc['tokenizer_id']!=tc['tokenizer_id'] or any(gc[k]!=tc['generation'][k] for k in ('input_ids','output_ids')):
                    raise InputError('Generation-only and generation/export token records disagree')
                for k in ('policy_versions','logprobs'):
                    if k in gc and k in tc['generation'] and gc[k]!=tc['generation'][k]:raise InputError('Generation token observations disagree')
        if 'continuation' in d:
            from .continuation_studies import validate_membership
            validate_membership(d['continuation'])
        if 'recipe' in d:training_recipes.validate_reference(d['recipe'])
        if 'attempt' in d:
            from .attempt_chains import validate_attempt
            validate_attempt(d['attempt'])
            if not d.get('task_id'): raise InputError('Recovery attempts require an explicit task_id')
        if 'attempt_outcome' in d:
            from .attempt_chains import validate_outcome
            validate_outcome(d['attempt_outcome'])
            if d['status'] != 'scored' and d['attempt_outcome']['result'] != 'unknown':
                raise InputError('Unavailable/error scores cannot establish an attempt outcome')
        if 'policy_history' in d:
            from .policy_age import validate_history
            validate_history(d['policy_history'])
        if 'learner_policy' in d:
            from .policy_age import validate_clock
            validate_clock(d['learner_policy'])
        if r['kind'] == 'supervision':
            if d['stage'] != 'prepared': raise InputError('Supervision observations currently support only the prepared stage')
            teacher_signals.validate(d['signal'])
        if r['kind'] == 'score':
            if d['status'] not in {'scored', 'unavailable', 'error'}: raise InputError('Invalid score status')
            if d['status'] == 'scored':
                if type(d['value']) not in (float, int) or not math.isfinite(d['value']): raise InputError('Scored value must be finite')
            elif d['value'] is not None: raise InputError('Unavailable/error score must be null')
        if r['kind'] == 'selection' and d['decision'] not in {'admitted', 'rejected', 'unknown'}:
            raise InputError('Invalid selection decision')
        if r['kind'] == 'use':
            if 'value_observation' in d:
                if 'recipe' not in d: raise InputError('Value observations require the actual use recipe')
                value_observations.validate(d['value_observation'])
            if 'regression' in d:
                if 'recipe' not in d: raise InputError('Regression observations require the actual use recipe')
                regression_signals.validate(d['regression'])
            if 'policy_gradient' in d:
                if 'recipe' not in d: raise InputError('Policy gradients require the actual use recipe')
                policy_gradients.validate(d['policy_gradient'])
                if 'model_tokens' in d and d['model_tokens'] != len(d['policy_gradient']['target_tokens']):
                    raise InputError('Policy gradient targets differ from model token count')
                if 'loss_tokens' in d and d['loss_tokens'] != sum(d['policy_gradient']['loss_mask']):
                    raise InputError('Policy gradient mask differs from loss token count')
            if d['stage'] not in {'backward_completed', 'optimizer_step_completed'}: raise InputError('Invalid training use stage')
            if 'advantage' in d and (type(d['advantage']) not in (float, int) or not math.isfinite(d['advantage'])):
                raise InputError('Recorded advantage must be finite')
            if 'loss_tokens' in d and 'model_tokens' in d and d['loss_tokens'] > d['model_tokens']:
                raise InputError('Loss token count exceeds model token count')
    dumps(packet)  # Reject non-JSON and non-finite values before persistence.
    return packet


def receive(store, packet):
    from .store import ReviewConflict
    validate(packet)
    producer, experiment = packet['producer'], packet['experiment']
    independent=packet['schema']==training_samples.VERSION
    table=training_samples.TABLE if independent else 'training_records'
    other='training_records' if independent else training_samples.TABLE
    inserted = 0
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for r in packet['records']:
            if c.execute(f'SELECT 1 FROM {other} WHERE producer=? AND experiment=? AND record_id=?',(producer,experiment,r['id'])).fetchone():
                raise ReviewConflict('Record identity already belongs to a different training schema')
            prior = c.execute(f'SELECT document FROM {table} WHERE producer=? AND experiment=? AND record_id=?',
                              (producer, experiment, r['id'])).fetchall()
            for p in prior:
                old = json.loads(p[0])
                stable = (old['kind'], old['sample']) == (r['kind'], r['sample'])
                keys = {'score': ('component', 'definition'), 'selection': ('filter', 'definition', 'batch_id')}.get(r['kind'], ())
                stable = stable and all(old['data'][k] == r['data'][k] for k in keys)
                if not stable or old['revision'] == r['revision'] and old != r:
                    raise ReviewConflict('Training record identity conflicts with retained evidence')
            inserted += c.execute(f'INSERT OR IGNORE INTO {table} VALUES (?,?,?,?,?,?,?,?,?)',
                (producer, experiment, r['id'], r['revision'], r['kind'], r['sample']['producer'],
                 r['sample']['id' if independent else 'rollout_id'], dumps(r), datetime.now(timezone.utc).isoformat())).rowcount
    return {'id': 'training-packet-' + digest(packet), 'revision': 0, 'inserted': inserted, 'records': len(packet['records'])}


def revision(c):
    legacy=tuple(c.execute('SELECT count(*),max(rowid) FROM training_records').fetchone())
    independent=tuple(c.execute('SELECT count(*),max(rowid) FROM training_sample_records').fetchone()) if c.execute("SELECT 1 FROM sqlite_master WHERE name='training_sample_records'").fetchone() else (0,None)
    recipes=tuple(c.execute('SELECT count(*),max(rowid) FROM training_recipes').fetchone()) if c.execute("SELECT 1 FROM sqlite_master WHERE name='training_recipes'").fetchone() else (0,None)
    continuation=tuple(c.execute('SELECT count(*),max(rowid) FROM continuation_studies').fetchone()) if c.execute("SELECT 1 FROM sqlite_master WHERE name='continuation_studies'").fetchone() else (0,None)
    if continuation[0]:return digest([legacy,independent,recipes,continuation])
    return digest([legacy,independent,recipes]) if recipes[0] else digest([legacy,independent]) if independent[0] else digest(legacy)


def snapshot(store, *, experiment=None, environment=None, monitor=None, selection=None):
    """Latest facts by explicit producer record revision, never arrival order.

    Population flags mean observed membership in that stage, not a monotonic
    funnel. Different filters/batches remain separate in each row's records.
    """
    from .monitoring import definitions, values, aggregation, in_population
    from . import training_selection
    with store.connect() as c:
        # Readiness composes this reader inside one query-only snapshot. Reuse
        # that transaction instead of starting a nested SQLite transaction.
        if not c.in_transaction: c.execute('BEGIN')
        rows = [{**dict(r),'identity_schema':VERSION} for r in c.execute('''SELECT * FROM training_records t WHERE revision=(SELECT max(revision)
            FROM training_records p WHERE p.producer=t.producer AND p.experiment=t.experiment AND p.record_id=t.record_id)
            ORDER BY experiment,sample_producer,rollout_id,kind,producer,record_id''').fetchall()]
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='training_sample_records'").fetchone():
            rows += [{**dict(r),'rollout_id':r['sample_id'],'identity_schema':training_samples.VERSION} for r in c.execute('''
                SELECT * FROM training_sample_records t WHERE revision=(SELECT max(revision) FROM training_sample_records p
                WHERE p.producer=t.producer AND p.experiment=t.experiment AND p.record_id=t.record_id)
                ORDER BY experiment,sample_producer,sample_id,kind,producer,record_id''')]
        sources = {(r['producer'], r['rollout_id'], r['revision']): dict(r) for r in c.execute('''SELECT v.producer,v.rollout_id,v.revision,v.run_id,
            json_extract(r.document,'$.metadata.experiment') experiment,
            json_extract(r.document,'$.metadata') metadata FROM rollout_revisions v JOIN runs r ON r.id=v.run_id''')}
        rev = revision(c)
        recipes = training_recipes.records(c, experiment)
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r['identity_schema'],r['experiment'], r['sample_producer'], r['rollout_id'])].append({
            **json.loads(r['document']), 'record_producer': r['producer'], 'received_at': r['received_at'],
            **({'record_schema':training_samples.VERSION} if r['identity_schema']==training_samples.VERSION else {})})
    result = []; orphan = 0; conflicting = 0; source_cache={}
    for (identity_schema,exp, producer, sample_id), records in buckets.items():
        if experiment and exp != experiment: continue
        samples = [r for r in records if r['kind'] == 'sample']
        if not samples: orphan += 1; continue
        # Multiple declarations cannot silently choose one producer's truth.
        if len(samples) != 1: conflicting += 1; continue
        s = samples[0]; d = s['data']
        if environment and d.get('environment') != environment: continue
        independent=identity_schema==training_samples.VERSION
        mapping=d.get('source') if independent else dict(producer=producer,rollout_id=sample_id,revision=s['evidence'].get('source_revision'))
        rollout=mapping.get('rollout_id') if mapping else None
        source = sources.get((mapping['producer'],rollout,mapping.get('revision'))) if mapping else None
        join_status = 'matched' if source else ('source_not_delivered' if mapping and mapping.get('revision') is not None else 'source_revision_not_declared')
        if independent and not mapping:join_status='source_not_declared'
        if source and source['experiment'] is not None and source['experiment'] != exp:
            source = None; join_status = 'experiment_conflict'
        mapping_status=None
        if source and independent:
            if source['run_id'] not in source_cache:
                with store.connect() as c:
                    source_cache[source['run_id']]=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(source['run_id'],)).fetchone()[0])
            mapping_status=training_samples.binding_status(source_cache[source['run_id']],mapping)
            if mapping_status=='invalid_source_spans':source=None;join_status=mapping_status
        retained_signal = None
        if source and independent:
            from .retained_rl_signals import for_sample
            retained_signal = for_sample(source_cache[source['run_id']], sample_id, d)
        score = [r for r in records if r['kind'] == 'score']
        selection_records = [r for r in records if r['kind'] == 'selection']
        uses = [r for r in records if r['kind'] == 'use']
        flags = {'generated': True, 'scored': any(r['data']['status'] == 'scored' for r in score),
                 'admitted': any(r['data']['decision'] == 'admitted' for r in selection_records),
                 'backward': any(r['data']['stage'] == 'backward_completed' for r in uses),
                 'positive_mask_backward': any(r['data']['stage'] == 'backward_completed' and r['data'].get('loss_tokens', 0) > 0 for r in uses),
                 'optimizer': any(r['data']['stage'] == 'optimizer_step_completed' for r in uses)}
        availability = {'generated': True, 'scored': bool(score), 'admitted': bool(selection_records),
            'backward': flags['backward'], 'optimizer': flags['optimizer'],
            'positive_mask_backward': any(r['data']['stage']=='backward_completed' and 'loss_tokens' in r['data'] for r in uses)}
        result.append({'experiment': exp, 'producer': producer, 'rollout_id': rollout, **{k:v for k,v in d.items() if k not in {'token_context','generation_context'}},
            **({'retained_rl_signal':retained_signal} if retained_signal is not None else {}),
            **({'token_context_summary':training_token_context.summarize(d['token_context'])} if 'token_context' in d else {}),
            **({'generation_context_summary':training_token_context.generation_summary(d['generation_context'])} if 'generation_context' in d else {}),
            **({'sample_id':sample_id,'sample_identity_schema':identity_schema,'source_mapping_status':mapping_status,
                'measurement_grain':'source_rollout_context'} if independent else {}),
            'run_id': source['run_id'] if source else None, 'join_status': join_status,
            'populations': flags, 'availability': availability, 'records': records,
            'use_count': len(uses), 'use_counts': dict(Counter(r['data']['stage'] for r in uses)),
            'score_state': 'recorded' if score else 'unknown',
            'selection_state': 'recorded' if selection_records else 'unknown', 'use_state': 'recorded' if uses else 'unknown'})
    options = definitions(store)
    selected = next((m for m in options if m['id'] == monitor), None)
    if monitor and selected is None: raise InputError('Unknown monitor')
    measures = values(store, monitor, {r['run_id'] for r in result if r['run_id']}) if monitor else {}
    metadata={s['run_id']:json.loads(s['metadata']) for s in sources.values()}
    for r in result:
        r['monitor_population']=('included' if not selected or not selected.get('population') else
            'unknown' if r['run_id'] not in metadata else
            'included' if in_population(selected,{'metadata':metadata[r['run_id']]}) else 'excluded')
        r['measurement']=measures.get(r['run_id']) if r['monitor_population']=='included' else None
    filter_options = training_selection.options(result)
    selected_filter = next((f for f in filter_options if f['id'] == selection), None)
    if selection and not selected_filter: raise InputError('Unknown filter in this population; select a recorded producer/filter/definition')
    groups = defaultdict(list)
    has_recipe = any('recipe' in r for r in result)
    for r in result:
        cohort = {k: r.get(k) for k in ('experiment', 'split', 'environment', 'environment_version', 'step_basis')}
        if has_recipe:cohort['recipe']=r.get('recipe')
        if r.get('sample_identity_schema'):cohort['sample_identity_schema']=r['sample_identity_schema']
        groups[dumps(cohort)].append(r)
    cohorts = []
    for key, items in groups.items():
        counts = {p: sum(r['populations'][p] for r in items) for p in ('generated', 'scored', 'admitted', 'backward', 'positive_mask_backward', 'optimizer')}
        bins = []
        for step in sorted({r['step'] for r in items if 'step' in r}):
            points = [r for r in items if r.get('step') == step]
            bins.append({'step': step, 'counts': {p: sum(r['populations'][p] for r in points) for p in counts},
                'availability': {p:any(r['availability'][p] for r in points) for p in counts}})
        comparisons = {}
        for p in counts:
            eligible = [r for r in items if r['populations'][p] and r['monitor_population']=='included']
            observed = [r['measurement']['value'] for r in eligible if r['measurement'] and r['measurement']['status'] == 'available' and r['measurement']['value'] is not None]
            comparisons[p] = {'population': len(eligible), 'measured': len(observed),
                'mean_per_rollout': sum(observed)/len(observed) if observed else None}
            if 'sample_identity_schema' in json.loads(key):
                comparisons[p]=training_selection.summary(eligible,bool(selected and aggregation(selected)=='opportunity_ratio'),source_weighted=True)
        cohorts.append({'cohort': json.loads(key), 'counts': counts, 'bins': bins, 'comparison': comparisons,
            'monitor_population':dict(Counter(r['monitor_population'] for r in items)),
            'selection_comparison': training_selection.project([r for r in items if r['monitor_population']=='included'], selected_filter,
                opportunity_ratio=bool(selected and aggregation(selected)=='opportunity_ratio')) if selected_filter else None,
            'availability': {p:any(r['availability'][p] for r in items) for p in counts},
            'groups': len({r['group_id'] for r in items if r.get('group_id')}),
            'missing_group': sum('group_id' not in r for r in items),
            'missing_step': sum('step' not in r for r in items),
            'missing_source': sum(r['run_id'] is None for r in items),
            'unknown_selection': sum(r['selection_state'] == 'unknown' for r in items),
            'unknown_use': sum(r['use_state'] == 'unknown' for r in items)})
    cohorts.sort(key=lambda c:(c['cohort']['experiment'],c['cohort']['split']!='train',dumps(c['cohort'])))
    document = {'schema': 'training-population/2' if any(r.get('sample_identity_schema') for r in result) else VERSION, 'revision': rev, 'cohorts': cohorts, 'samples': result,
        'orphan_samples': orphan, 'conflicting_samples': conflicting, 'monitor': selected,
        'selection': selected_filter, 'selection_options': filter_options,
        'view_revision': digest([rev, monitor, selection, [(r['producer'], r['sample_id'] if r.get('sample_identity_schema') else r['rollout_id'], r['run_id'], (r.get('measurement') or {}).get('id')) for r in result]]),
        'monitor_options': [{'id': m['id'], 'name': m['name'], 'observer': m['observer']} for m in options],
        'scope': 'Explicit producer sample declarations only. Stage counts are observed membership, not a drop-off funnel. No record means unknown; scored means at least one scored component; admitted means at least one recorded admission. Backward completion does not prove an optimizer update. Optimizer records establish batch membership, not nonzero loss, gradient or per-sample parameter effect. Backward and optimizer records are separate evidence stages, not additive training uses. Means weight each measured rollout once, not each opportunity or repeated use.'}
    if any(r.get('sample_identity_schema') for r in result):
        document['scope'] += ' Independent sample cohorts count samples at training stages. Behavior means and opportunity totals weight each bound source rollout once per population and describe whole-source context, not the selected spans or trained tokens. Independent and legacy identity contracts remain separate cohorts.'
    refs = {(r['experiment'], dumps(record['data']['recipe'])) for r in result for record in r['records'] if 'recipe' in record['data']}
    if refs:
        document['recipes'] = [r for r in recipes if (r['experiment'], dumps({k:r[k] for k in ('producer','id','revision')})) in refs]
        document['scope'] += ' Recipe references pin exact producer declarations. Generation and training-use recipes are independent; missing use context is never inherited from generation.'
    # This binds the complete displayed evidence, not just the event-stream
    # revision used for refresh hints. A save cannot substitute newer values.
    return {**document, 'snapshot_id': 'training-population-' + digest(document)}
