"""Bounded, exact-source training evidence for an investigation.

This is a provenance lookup, not gradient attribution. It does not run a model,
scan semantic text, or substitute the newest source for a reviewed revision.
"""
from collections import Counter, defaultdict
import json

from .schema import InputError, digest
from . import training_samples, training_selection

VERSION = 'source-training-exposure/1'
MAX_SAMPLES = 200
MAX_RECORDS = 2000
MAX_RECORD_CHARS = 2_000_000
BOUNDARY = ('Producer-recorded membership only. Missing records do not establish rejection or non-use. '
            'A source link does not establish that the evaluated artifact, reward, or specific behavior '
            'was part of the loss. Earlier-turn samples can share a whole-episode evaluation. '
            'Backward and optimizer receipts are separate stages, not additive updates; even a positive '
            'loss mask does not establish a nonzero gradient or parameter effect.')
OMIT = ('token_context', 'generation_context', 'policy_gradient', 'regression', 'value_observation')
TABLES = (('training-records/1', 'training_records', 'rollout_id'),
          (training_samples.VERSION, training_samples.TABLE, 'sample_id'))


def _candidates(c, table, column, independent, run_id, experiment):
    mapping = ("t.sample_producer=v.producer AND t.rollout_id=v.rollout_id AND "
               "json_extract(t.document,'$.evidence.source_revision')=v.revision")
    if independent:
        mapping = ("json_extract(t.document,'$.data.source.producer')=v.producer AND "
                   "json_extract(t.document,'$.data.source.rollout_id')=v.rollout_id AND "
                   "json_extract(t.document,'$.data.source.revision')=v.revision")
    query = (f'SELECT DISTINCT t.experiment,t.sample_producer,t.{column} '
             f'FROM rollout_revisions v CROSS JOIN {table} t '
             f"WHERE v.run_id=? AND {mapping} AND t.kind='sample' "
             + ('AND t.experiment=? ' if experiment is not None else '')
             + f'ORDER BY t.experiment,t.sample_producer,t.{column} LIMIT ?')
    args = [run_id] + ([experiment] if experiment is not None else []) + [MAX_SAMPLES + 1]
    return [tuple(r) for r in c.execute(query, args)]


def _records(c, table, column, identity, budget):
    # Project away tensors in SQLite; this lookup must not materialize the full
    # token ledger. Native record identities still reference those retained facts.
    paths = ','.join("'$.data." + key + "'" for key in OMIT)
    omitted = ','.join("json_type(t.document,'$.data." + key + "') IS NOT NULL" for key in OMIT)
    expression = f'json_remove(t.document,{paths})'
    query = f'''SELECT t.producer,t.record_id,t.revision,t.received_at,
        length({expression}) size,
        CASE WHEN length({expression})<=? THEN {expression} ELSE NULL END document,
        {omitted}
      FROM {table} t WHERE t.experiment=? AND t.sample_producer=? AND t.{column}=?
      AND NOT EXISTS(SELECT 1 FROM {table} newer WHERE newer.producer=t.producer
        AND newer.experiment=t.experiment AND newer.record_id=t.record_id AND newer.revision>t.revision)
      ORDER BY t.kind,t.producer,t.record_id LIMIT ?'''
    rows = []; size = 0
    for r in c.execute(query, [budget['chars'], *identity, budget['records'] + 1]):
        if len(rows) >= budget['records']: return None, 'record_limit'
        size += r['size']
        if r['document'] is None or size > budget['chars']: return None, 'record_size_limit'
        rows.append(r)
    budget['chars'] -= size
    budget['records'] -= len(rows)
    result = []
    for r in rows:
        doc = json.loads(r['document'])
        result.append(dict(doc, record_producer=r['producer'], received_at=r['received_at'],
                           omitted_data_fields=[key for i, key in enumerate(OMIT) if r[6+i]]))
    return result, None


def _sample(c, table, column, schema, identity, run, budget):
    exp, producer, sample_id = identity
    row = dict(sample_identity_schema=schema, experiment=exp, producer=producer, sample_id=sample_id)
    records, issue = _records(c, table, column, identity, budget)
    if issue: return dict(row, binding=issue, records=[], records_complete=False)
    declarations = [r for r in records if r['kind'] == 'sample']
    # Load *all* declarations for the sample, including a conflicting declaration
    # that maps elsewhere. Filtering declarations to this source would hide it.
    binding = 'conflicting_declarations' if len(declarations) != 1 else 'episode_reference'
    if len(declarations) == 1:
        data = declarations[0]['data']
        row.update(split=data['split'], display_name=data.get('display_name', sample_id))
        if run.get('metadata', {}).get('experiment') not in (None, exp): binding = 'experiment_conflict'
        elif schema == training_samples.VERSION:
            binding = training_samples.binding_status(run, data['source'])
    # Retain coordinates and canonical-text digests without duplicating source
    # text in saved findings, including declarations excluded for conflicts.
    for record in declarations:
        source = record['data'].get('source', {})
        if 'spans' in source:
            source['spans'] = [dict({k:v for k,v in s.items() if k != 'text'},
                                   text_digest=digest(s['text'])) for s in source['spans']]
    bound = binding in {'episode_reference', 'exact_source_spans'}
    uses = [r['data'] for r in records if r['kind'] == 'use']
    row.update(binding=binding, bound=bound, records=records, records_complete=True,
               use_counts=dict(Counter(u['stage'] for u in uses)),
               backward_mask_counts=dict(Counter('positive' if u.get('loss_tokens', 0)>0 else
                    'zero' if 'loss_tokens' in u else 'unrecorded'
                    for u in uses if u['stage']=='backward_completed')),
               scores=[dict(producer=r['record_producer'], id=r['id'], revision=r['revision'], **r['data'])
                       for r in records if r['kind']=='score'])
    row['filters'] = [dict(option, **training_selection.decision(row, option))
                      for option in training_selection.options([row])]
    return row


def snapshot(store, *, run_id, source_hash=None, experiment=None):
    if not isinstance(run_id, str) or not run_id.strip(): raise InputError('Choose a rollout')
    if experiment is not None and (not isinstance(experiment, str) or not experiment.strip()):
        raise InputError('Experiment must be a nonempty name')
    with store.read_snapshot() as saved, saved.connect() as c:
        stored = c.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()
        if not stored: raise InputError('Rollout source is unavailable')
        run = json.loads(stored[0]); actual = digest(run)
        if source_hash is not None and source_hash != actual:
            raise InputError('Training lookup requires the exact reviewed source hash')
        available = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        aliases = [dict(r) for r in c.execute('SELECT producer,rollout_id,revision FROM rollout_revisions '
                    'WHERE run_id=? ORDER BY producer,rollout_id,revision LIMIT 1001', (run_id,))]
        candidates = []; tables = []
        for schema, table, column in TABLES:
            if table not in available: continue
            tables.append(schema)
            for identity in _candidates(c, table, column, schema==training_samples.VERSION, run_id, experiment):
                candidates.append((schema, table, column, identity))
        candidates.sort(key=lambda r:(r[0],r[3]))
        budget = dict(chars=MAX_RECORD_CHARS, records=MAX_RECORDS)
        samples = [_sample(c, table, column, schema, identity, run, budget)
                   for schema, table, column, identity in candidates[:MAX_SAMPLES]]
    bound = [r for r in samples if r.get('bound')]
    cohorts = defaultdict(list)
    for r in bound: cohorts[(r['sample_identity_schema'],r['experiment'],r['split'])].append(r)
    summary = []
    for (schema, exp, split), rows in sorted(cohorts.items()):
        summary.append(dict(schema=schema, experiment=exp, split=split, bound_samples=len(rows),
            samples_with_backward=sum(bool(r['use_counts'].get('backward_completed')) for r in rows),
            samples_with_optimizer=sum(bool(r['use_counts'].get('optimizer_step_completed')) for r in rows),
            samples_with_positive_backward_mask=sum(bool(r['backward_mask_counts'].get('positive')) for r in rows),
            backward_receipts=sum(r['use_counts'].get('backward_completed',0) for r in rows),
            optimizer_receipts=sum(r['use_counts'].get('optimizer_step_completed',0) for r in rows)))
    incomplete = len(candidates)>MAX_SAMPLES or any(not r['records_complete'] for r in samples)
    content = dict(schema=VERSION, run_id=run_id, source_hash=actual, experiment=experiment,
        source_aliases=aliases[:1000], source_aliases_complete=len(aliases)<=1000,
        available_ledgers=tables, samples=samples, cohorts=summary,
        completeness=dict(complete=not incomplete, sample_limit=MAX_SAMPLES, record_limit=MAX_RECORDS,
            projected_char_limit=MAX_RECORD_CHARS, sample_limit_reached=len(candidates)>MAX_SAMPLES,
            excluded_bindings=dict(Counter(r['binding'] for r in samples if not r.get('bound')))),
        counts=dict(returned_samples=len(samples), bound_samples=len(bound)),
        coverage_scope='Only declarations explicitly pinned to this exact source. Unmapped samples and orphan use records cannot be attributed to it.',
        boundary=BOUNDARY, inference_calls=0)
    return dict(snapshot_id='training-exposure-'+digest(content), **content)


def reference(doc):
    return dict(kind='training_exposure', **{k:doc[k] for k in ('run_id','source_hash','experiment','snapshot_id')})


def resolve(store, ref):
    if not isinstance(ref,dict) or set(ref)!={'kind','run_id','source_hash','experiment','snapshot_id'}:
        raise InputError('Use the exact training exposure reference')
    if ref['kind']!='training_exposure': raise InputError('Expected training exposure reference')
    result = snapshot(store, run_id=ref['run_id'], source_hash=ref['source_hash'], experiment=ref['experiment'])
    if ref['snapshot_id'] != result['snapshot_id']:
        raise InputError('Training evidence changed. Reload and review before attaching.')
    return dict(kind='training_exposure', id=result['snapshot_id'], title='Selection & training use',
                run_id=result['run_id'], snapshot=result)
