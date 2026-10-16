"""Recorded prefix experiments, joined to independent training samples.

No generation, judge inference, loss modification or causal credit assignment.
Designs are immutable; sample/score arrivals change only their live projection.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math

from .schema import InputError, digest, dumps
from .training_recipes import fields, text

VERSION = 'continuation-studies/1'
PROJECTION = 'continuation-comparison/1'
ARMS = ('before', 'after')


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS continuation_studies (
        producer TEXT NOT NULL, experiment TEXT NOT NULL, study_id TEXT NOT NULL,
        document TEXT NOT NULL, received_at TEXT NOT NULL,
        PRIMARY KEY(producer,experiment,study_id))''')


def integer(value, name, minimum=0):
    if type(value) is not int or not minimum <= value < 2**53:
        raise InputError(name + ' must be a bounded nonnegative integer')


def reference(value):
    fields(value, {'producer', 'id'})
    for k, v in value.items(): text(v, k)


def validate_membership(value):
    fields(value, {'study', 'arm', 'draw_id', 'settings_digest', 'budget_definition', 'state_id'})
    reference(value['study'])
    if value['arm'] not in ARMS: raise InputError('Continuation arm must be before or after')
    for k in ('draw_id', 'settings_digest', 'budget_definition'): text(value[k], k)
    if value['state_id'] is not None: text(value['state_id'], 'state_id')


def validate(packet):
    fields(packet, {'schema', 'producer', 'experiment', 'studies'})
    if packet['schema'] != VERSION: raise InputError('Use continuation-studies/1')
    text(packet['producer'], 'producer'); text(packet['experiment'], 'experiment')
    if not isinstance(packet['studies'], list) or not 1 <= len(packet['studies']) <= 100:
        raise InputError('Supply 1–100 continuation studies')
    seen = set()
    for s in packet['studies']:
        fields(s, {'id', 'label', 'basis', 'master', 'task_id', 'policy_version', 'tokenizer_id',
                   'settings_digest', 'budget_definition', 'environment', 'environment_version',
                   'environment_kind', 'verifier', 'selection', 'independent_draws', 'arms'},
               {'step', 'step_basis', 'confirmation_of'})
        for k in ('id', 'label', 'basis', 'task_id', 'policy_version', 'tokenizer_id',
                  'settings_digest', 'budget_definition', 'environment', 'environment_version'):
            text(s[k], k)
        if s['id'] in seen: raise InputError('Duplicate continuation study ID')
        seen.add(s['id']); reference(s['master'])
        if s['environment_kind'] not in ('text', 'sandbox'): raise InputError('Declare text or sandbox environment')
        if type(s['independent_draws']) is not bool: raise InputError('Declare independent_draws as boolean')
        if s['selection'] not in ('prospective', 'retrospective', 'unknown'):
            raise InputError('Window selection must be prospective, retrospective or unknown')
        if 'confirmation_of' in s:
            reference(s['confirmation_of'])
            if s['selection'] != 'prospective': raise InputError('Confirmation needs a prospectively fixed window')
            if s['confirmation_of'] == {'producer': packet['producer'], 'id': s['id']}:
                raise InputError('A study cannot confirm itself')
        if ('step' in s) != ('step_basis' in s): raise InputError('Study step requires step_basis')
        if 'step' in s: integer(s['step'], 'step'); text(s['step_basis'], 'step_basis')
        fields(s['verifier'], {'producer', 'component', 'definition'})
        for k, v in s['verifier'].items(): text(v, 'verifier '+k)
        fields(s['arms'], set(ARMS))
        members = {dumps(s['master'])}
        for arm in ARMS:
            a = s['arms'][arm]
            fields(a, {'prefix_tokens', 'prefix_digest', 'state_id', 'samples'})
            integer(a['prefix_tokens'], 'prefix_tokens', 1); text(a['prefix_digest'], 'prefix_digest')
            if s['environment_kind'] == 'sandbox': text(a['state_id'], 'sandbox state_id')
            elif a['state_id'] is not None: raise InputError('Text studies have null state_id')
            if not isinstance(a['samples'], list) or not 1 <= len(a['samples']) <= 256:
                raise InputError('Each arm needs 1–256 planned sample identities')
            for ref in a['samples']:
                reference(ref); key = dumps(ref)
                if key in members: raise InputError('Samples must be distinct from the master and both arms')
                members.add(key)
        if s['arms']['before']['prefix_tokens'] >= s['arms']['after']['prefix_tokens']:
            raise InputError('After prefix must extend before prefix')
    dumps(packet)
    return packet


def receive(store, packet):
    from .store import ReviewConflict
    validate(packet); inserted = 0
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for s in packet['studies']:
            key = (packet['producer'], packet['experiment'], s['id'])
            old = c.execute('SELECT document FROM continuation_studies WHERE producer=? AND experiment=? AND study_id=?', key).fetchone()
            if old and json.loads(old[0]) != s: raise ReviewConflict('Continuation study is immutable; use a new ID for a changed design')
            inserted += c.execute('INSERT OR IGNORE INTO continuation_studies VALUES (?,?,?,?,?)',
                (*key, dumps(s), datetime.now(timezone.utc).isoformat())).rowcount
    return {'id': 'continuation-packet-'+digest(packet), 'revision': 0, 'inserted': inserted, 'studies': len(packet['studies'])}


def wilson(successes, count):
    if not count: return None
    z = 1.959963984540054; p = successes / count; den = 1 + z*z/count
    center = (p + z*z/(2*count))/den
    width = z*math.sqrt(p*(1-p)/count + z*z/(4*count*count))/den
    return [max(0., center-width), min(1., center+width)]


def difference_interval(before, after):
    """Newcombe independent-proportion interval, Wilson without continuity correction."""
    b, a = before['rate'], after['rate']; bl, bu = before['interval']; al, au = after['interval']
    return [max(-1., a-b-math.hypot(a-al, bu-b)), min(1., a-b+math.hypot(au-a, b-bl))]


def _sample(c, experiment, ref, verifier, *, master=False):
    rows = c.execute('''SELECT t.producer,t.record_id,t.revision,t.document FROM training_sample_records t
        WHERE experiment=? AND sample_producer=? AND sample_id=? AND revision=(
          SELECT max(p.revision) FROM training_sample_records p WHERE p.producer=t.producer
          AND p.experiment=t.experiment AND p.record_id=t.record_id) ORDER BY t.producer,t.record_id''',
        (experiment, ref['producer'], ref['id'])).fetchall()
    records = [dict(json.loads(r['document']), record_producer=r['producer']) for r in rows]
    declarations = [r for r in records if r['kind'] == 'sample']
    result = {'sample': ref, 'status': 'missing_sample' if not declarations else 'conflicting_sample',
              'run_id': None, 'outcome': None, 'generated_tokens': None, 'training_stages': [],
              'records': [{'producer': r['producer'], 'id': r['record_id'], 'revision': r['revision'],
                           'digest': digest(json.loads(r['document']))} for r in rows]}
    if len(declarations) != 1: return result
    d = declarations[0]['data']; tc = d.get('token_context'); result['status'] = 'declared'
    result['context'] = {k: d.get(k) for k in ('task_id', 'policy_version', 'environment', 'environment_version', 'continuation')}
    gc = d.get('generation_context')
    if tc or gc:
        g = {**(tc['generation'] if tc else {}), **(gc or {})}; result.update(tokenizer_id=gc['tokenizer_id'] if gc else tc['tokenizer_id'], prefix_digest=digest(g['input_ids']),
            prefix_tokens=len(g['input_ids']), generated_tokens=len(g['output_ids']),
            mixed_policy_versions=len(set(g.get('policy_versions', [])) - {-1}) > 1)
        if master: result['tokens'] = g['input_ids'] + g['output_ids']; result['prompt_tokens'] = len(g['input_ids'])
    mapping = d.get('source')
    if mapping:
        row = c.execute('''SELECT r.id,r.document FROM rollout_revisions v JOIN runs r ON r.id=v.run_id
            WHERE v.producer=? AND v.rollout_id=? AND v.revision=?''',
            (mapping['producer'], mapping['rollout_id'], mapping['revision'])).fetchone()
        if row:
            from .training_samples import binding_status
            run = json.loads(row['document'])
            if run['metadata'].get('experiment', experiment) == experiment and binding_status(run, mapping) != 'invalid_source_spans':
                result['run_id'] = row['id']
    scores = [r for r in records if r['kind'] == 'score' and r['record_producer'] == verifier['producer']
              and all(r['data'][k] == verifier[k] for k in ('component', 'definition'))]
    result['score_status'] = 'missing_score' if not scores else 'conflicting_score'
    if len(scores) == 1:
        score = scores[0]['data']; result['score_status'] = score['status']
        if score['status'] == 'scored':
            if score['value'] in (0, 1): result['outcome'] = int(score['value'])
            else: result['score_status'] = 'nonbinary_score'
    result['training_stages'] = sorted({r['data']['stage'] for r in records if r['kind'] == 'use'})
    return result


def project(c, producer, experiment, design):
    s = design; master = _sample(c, experiment, s['master'], s['verifier'], master=True)
    master_tokens = master.pop('tokens', None); issues = []
    context_keys = ('task_id', 'policy_version', 'environment', 'environment_version')
    if master_tokens is None: issues.append('Master token sequence is unavailable')
    elif master.get('tokenizer_id') != s['tokenizer_id']: issues.append('Master tokenizer differs')
    elif master.get('mixed_policy_versions'): issues.append('Master records mixed generation policies')
    elif any(master['context'].get(k) != s[k] for k in context_keys): issues.append('Master context differs')
    elif s['arms']['before']['prefix_tokens'] < master['prompt_tokens']: issues.append('Before gate is inside the original prompt')
    else:
        for arm, gate in s['arms'].items():
            n = gate['prefix_tokens']
            if n > len(master_tokens) or digest(master_tokens[:n]) != gate['prefix_digest']:
                issues.append(arm.title()+' gate does not match the master token prefix')
    prefix_verified = not issues
    planned = {dumps(ref) for a in ARMS for ref in s['arms'][a]['samples']}
    declared = {dumps({'producer': r['sample_producer'], 'id': r['sample_id']}) for r in c.execute('''
        SELECT sample_producer,sample_id FROM training_sample_records WHERE experiment=? AND kind='sample'
        AND json_extract(document,'$.data.continuation.study.producer')=?
        AND json_extract(document,'$.data.continuation.study.id')=?''', (experiment, producer, s['id']))}
    unplanned = [json.loads(ref) for ref in sorted(declared-planned)]
    arms = {}; all_draws = []
    for name in ARMS:
        gate = s['arms'][name]; cases = []
        for ref in gate['samples']:
            row = _sample(c, experiment, ref, s['verifier']); problems = []
            if row['status'] != 'declared': problems.append(row['status'])
            else:
                ctx = row['context']; membership = ctx['continuation']
                if any(ctx.get(k) != s[k] for k in context_keys): problems.append('context_mismatch')
                if row.get('tokenizer_id') != s['tokenizer_id']: problems.append('tokenizer_missing_or_mismatch')
                if row.get('mixed_policy_versions'): problems.append('mixed_generation_policies')
                if row.get('prefix_digest') != gate['prefix_digest'] or row.get('prefix_tokens') != gate['prefix_tokens']:
                    problems.append('prefix_missing_or_mismatch')
                expected = {'study': {'producer': producer, 'id': s['id']}, 'arm': name,
                            'settings_digest': s['settings_digest'], 'budget_definition': s['budget_definition'], 'state_id': gate['state_id']}
                if not membership or any(membership.get(k) != v for k, v in expected.items()):
                    problems.append('sampling_declaration_mismatch')
                else: all_draws.append(membership['draw_id'])
                if row['outcome'] is None: problems.append(row['score_status'])
            row['issues'] = problems; row['eligible'] = not problems; cases.append(row)
        eligible = [r for r in cases if r['eligible']]; n = len(eligible); k = sum(r['outcome'] for r in eligible)
        arms[name] = {'expected': len(cases), 'observed': n, 'successes': k, 'rate': k/n if n else None,
                      'interval': wilson(k, n) if s['independent_draws'] and n == len(cases) else None,
                      'complete': n == len(cases), 'cases': cases,
                      'generated_tokens': sum(r['generated_tokens'] for r in cases if r['generated_tokens'] is not None),
                      'cost_coverage': sum(r['generated_tokens'] is not None for r in cases),
                      'issues': dict(Counter(p for r in cases for p in r['issues']))}
    if len(set(all_draws)) != len(all_draws): issues.append('Repeated draw identities; independence cannot be assumed')
    if not all(a['complete'] for a in arms.values()): issues.append('Planned continuation outcomes are incomplete or incompatible')
    confirmation_status = None
    if 'confirmation_of' in s:
        ref = s['confirmation_of']
        row = c.execute('SELECT document FROM continuation_studies WHERE producer=? AND experiment=? AND study_id=?',
                        (ref['producer'], experiment, ref['id'])).fetchone()
        confirmation_status = 'design_missing'
        if row:
            prior = json.loads(row[0]); unchanged = all(prior[k] == s[k] for k in ('master', *context_keys, 'tokenizer_id', 'settings_digest', 'budget_definition', 'verifier'))
            unchanged = unchanged and all({k:v for k,v in prior['arms'][a].items() if k != 'samples'} == {k:v for k,v in s['arms'][a].items() if k != 'samples'} for a in ARMS)
            previous = {dumps(ref) for a in ARMS for ref in prior['arms'][a]['samples']}
            fresh = not any(dumps(ref) in previous for a in ARMS for ref in s['arms'][a]['samples'])
            previous_draws = set(); previous_draws_complete = True
            for arm in ARMS:
                for sample in prior['arms'][arm]['samples']:
                    retained = _sample(c, experiment, sample, prior['verifier'])
                    member = retained.get('context', {}).get('continuation')
                    if member and member['study'] == ref and member['arm'] == arm: previous_draws.add(member['draw_id'])
                    else: previous_draws_complete = False
            fresh = fresh and not previous_draws.intersection(all_draws)
            confirmation_status = 'fresh_identities_same_design' if unchanged and fresh and previous_draws_complete else 'discovery_draws_unavailable' if not previous_draws_complete else 'design_changed_or_samples_reused'
        if confirmation_status != 'fresh_identities_same_design': issues.append('Confirmation design is missing, changed or reuses samples')
    available = not issues
    delta = arms['after']['rate'] - arms['before']['rate'] if available else None
    interval = difference_interval(arms['before'], arms['after']) if available and s['independent_draws'] else None
    if issues:
        for a in arms.values(): a['interval'] = None
    value = {'schema': PROJECTION, 'producer': producer, 'experiment': experiment, 'design': s,
             'master': master, 'arms': arms, 'prefix_verified': prefix_verified, 'span_tokens': s['arms']['after']['prefix_tokens']-s['arms']['before']['prefix_tokens'],
             'difference': delta, 'interval': interval, 'issues': issues, 'confirmation_status': confirmation_status,
             'unplanned_samples': unplanned,
             'interpretation': 'Observed success-rate difference for these recorded prefixes and sampling settings. Conditional on the selected window; not causal token credit or verified training improvement.',
             'interval_method': 'Nominal 95% Newcombe-Wilson, independent Bernoulli draws declared by producer; no multiple-window or adaptive-stopping adjustment.'}
    value['snapshot_id'] = 'continuation-snapshot-'+digest(value)
    return value


def snapshot(store, *, experiment=None, environment=None, limit=20, offset=0):
    integer(limit, 'limit', 1); integer(offset, 'offset')
    if limit > 50: raise InputError('At most 50 studies per page')
    where = []; args = []
    if experiment: where.append('experiment=?'); args.append(experiment)
    if environment: where.append("json_extract(document,'$.environment')=?"); args.append(environment)
    clause = ' WHERE '+' AND '.join(where) if where else ''
    with store.connect() as c:
        c.execute('BEGIN')
        total = c.execute('SELECT count(*) FROM continuation_studies'+clause, args).fetchone()[0]
        rows = c.execute('SELECT * FROM continuation_studies'+clause+' ORDER BY rowid DESC LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
        studies = [project(c, r['producer'], r['experiment'], json.loads(r['document'])) for r in rows]
    return {'schema': PROJECTION, 'total': total, 'offset': offset, 'limit': limit, 'studies': studies,
            'revision': digest(studies), 'inference_calls': 0}
