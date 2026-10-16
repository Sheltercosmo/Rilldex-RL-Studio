"""Immutable recipe declarations and evidence-scoped measurement applicability.

Declarations describe the producer's recipe, not independently verified native
execution. They never manufacture teacher signals, token credit or gradients.
"""
import json
from datetime import datetime, timezone

from .schema import InputError, digest, dumps

VERSION = 'training-recipes/1'


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS training_recipes (
        producer TEXT NOT NULL, experiment TEXT NOT NULL, recipe_id TEXT NOT NULL,
        revision INTEGER NOT NULL, document TEXT NOT NULL, received_at TEXT NOT NULL,
        PRIMARY KEY(producer,experiment,recipe_id,revision))''')


def text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise InputError(name + ' must contain 1–500 characters')


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise InputError('Recipe object requires ' + ', '.join(sorted(required)))


def validate_reference(value):
    fields(value, {'producer', 'id', 'revision'})
    text(value['producer'], 'recipe producer'); text(value['id'], 'recipe id')
    if type(value['revision']) is not int or not 0 <= value['revision'] < 2**63:
        raise InputError('Recipe revision must be a nonnegative integer')


def validate(packet):
    fields(packet, {'schema', 'producer', 'experiment', 'recipes'})
    if packet['schema'] != VERSION: raise InputError('Use training-recipes/1')
    text(packet['producer'], 'producer'); text(packet['experiment'], 'experiment')
    if not isinstance(packet['recipes'], list) or not 1 <= len(packet['recipes']) <= 100:
        raise InputError('Supply 1–100 recipe declarations')
    seen = set()
    for r in packet['recipes']:
        fields(r, {'id', 'revision', 'label', 'implementation', 'config_digest', 'basis',
                   'components_complete', 'components', 'context'}, {'setup'})
        if 'setup' in r:
            validate_setup(r['setup'])
        validate_reference({'producer': packet['producer'], 'id': r['id'], 'revision': r['revision']})
        identity = (r['id'], r['revision'])
        if identity in seen: raise InputError('Duplicate recipe identity in packet')
        seen.add(identity)
        for k in ('label', 'config_digest', 'basis'): text(r[k], k)
        fields(r['implementation'], {'name', 'revision'})
        for k, v in r['implementation'].items(): text(v, 'implementation ' + k)
        if type(r['components_complete']) is not bool: raise InputError('Declare components_complete as boolean')
        fields(r['context'], set(), {'phase', 'domain', 'effort', 'budget_definition', 'scheduling', 'trajectory_policy'})
        for k, v in r['context'].items(): text(v, k)
        if not isinstance(r['components'], list) or not 1 <= len(r['components']) <= 32:
            raise InputError('Supply 1–32 named objective components')
        ids = set()
        for part in r['components']:
            fields(part, {'id', 'label', 'supervision', 'credit', 'objective'}, {'provider'})
            for k in ('id', 'label', 'supervision'): text(part[k], 'component ' + k)
            if part['id'] in ids: raise InputError('Component ids must be unique within a recipe')
            ids.add(part['id'])
            fields(part['credit'], {'kind', 'unit'})
            fields(part['objective'], {'definition', 'unit', 'weighting', 'reduction'}, {'probability_basis'})
            for obj in (part['credit'], part['objective']):
                for k, v in obj.items(): text(v, k)
            if 'provider' in part:
                fields(part['provider'], {'producer', 'id', 'revision'})
                for k, v in part['provider'].items(): text(v, 'provider ' + k)
    dumps(packet)
    return packet


def validate_setup(setup):
    from .training_setup import SUPPORTED_VERSIONS, FIELDS, selected_settings
    if isinstance(setup,dict) and setup.get('schema') == 'trl-a2po-setup/1':
        from . import trl_a2po_setup
        fields(setup, {'schema','framework','trainer','version','settings'})
        if setup['framework'] != 'trl' or setup['trainer'] != 'a2po': raise InputError('A*-PO setup must identify TRL and A2POTrainer')
        text(setup['version'], 'training setup version')
        if not isinstance(setup['settings'],dict) or setup['settings'].keys()-set(trl_a2po_setup.FIELDS): raise InputError('Unrecognized A*-PO setup fields')
        trl_a2po_setup.inspect({'config':setup['settings'],'version':setup['version'],'resolved':True})
        return
    fields(setup, {'schema', 'framework', 'version', 'settings'})
    if setup['schema'] not in SUPPORTED_VERSIONS or not isinstance(setup['framework'], str) or setup['framework'] not in FIELDS:
        raise InputError('Unrecognized training setup schema or framework')
    text(setup['version'], 'training setup version')
    if not isinstance(setup['settings'], dict) or setup['settings'].keys() - set(FIELDS[setup['framework']]) - {'critic.enabled'}:
        raise InputError('Training setup settings must use recognized fields')
    nested = {}
    for path, value in setup['settings'].items():
        if path == 'critic.enabled':
            if type(value) is not bool: raise InputError('critic.enabled must be boolean')
            continue
        target = nested
        parts = path.split('.')
        for part in parts[:-1]: target = target.setdefault(part, {})
        target[parts[-1]] = value
    selected_settings(setup['framework'], nested)


def receive(store, packet):
    from .store import ReviewConflict
    validate(packet)
    inserted = 0
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for r in packet['recipes']:
            key = (packet['producer'], packet['experiment'], r['id'], r['revision'])
            prior = c.execute('SELECT document FROM training_recipes WHERE producer=? AND experiment=? AND recipe_id=? AND revision=?', key).fetchone()
            if prior and json.loads(prior[0]) != r:
                raise ReviewConflict('Recipe identity conflicts with retained evidence; use a new revision')
            inserted += c.execute('INSERT OR IGNORE INTO training_recipes VALUES (?,?,?,?,?,?)',
                                  (*key, dumps(r), datetime.now(timezone.utc).isoformat())).rowcount
    return {'id': 'recipe-packet-' + digest(packet), 'revision': 0,
            'inserted': inserted, 'recipes': len(packet['recipes'])}


def records(c, experiment=None):
    return [{'producer': row['producer'], 'experiment': row['experiment'], **json.loads(row['document'])}
            for row in c.execute('SELECT * FROM training_recipes WHERE (? IS NULL OR experiment=?) ORDER BY experiment,producer,recipe_id,revision',
                                 (experiment, experiment))]


def snapshot(store, experiment=None):
    with store.connect() as c: retained = records(c, experiment)
    return {'schema': VERSION, 'recipes': retained, 'snapshot_id': 'recipes-' + digest(retained)}


def resolve(retained, experiment, reference):
    if reference is None:
        return {'status': 'not_recorded', 'reference': None, 'manifest': None}
    manifest = next((r for r in retained if r['experiment'] == experiment
                     and all(r[k] == reference[k] for k in ('producer', 'id', 'revision'))), None)
    return {'status': 'recorded' if manifest else 'not_delivered', 'reference': reference, 'manifest': manifest}


def applicability(context, predicate, known):
    manifest = context['manifest']
    if not manifest: return 'unknown'
    if any(predicate(c) for c in manifest['components']): return 'applicable'
    if manifest['components_complete'] and all(known(c) for c in manifest['components']):
        return 'not_applicable'
    return 'unknown'


CREDIT = {'group_relative', 'hierarchical_group_relative', 'cached_baseline', 'critic', 'return', 'token_distribution', 'direct', 'none'}
SIGNAL = {'reward', 'teacher', 'self_teacher', 'supervised'}


def capabilities(context, *, rewards=(), uses=()):
    """Existing metrics may be captured; future native operators stay unsupported.

    Coverage is about this evidence slice, not the training run as a whole.
    Applicability only reflects the pinned producer declaration.
    """
    result = []
    def add(identifier, label, predicate, known, requirement, *, supported=False, captured=False, coverage=None):
        app = applicability(context, predicate, known)
        state = ('not_applicable' if app == 'not_applicable' else 'unknown' if app == 'unknown'
                 else 'unsupported' if not supported else 'captured' if captured else 'missing')
        result.append({'id': identifier, 'label': label, 'applicability': app, 'state': state,
                       'requirement': requirement, 'coverage': coverage})
    group_count = sum(r['constant_groups']['denominator'] for r in rewards)
    add('group_contrast', 'Reward variation within prompt groups', lambda c: c['credit']['kind'] == 'group_relative',
        lambda c: c['credit']['kind'] in CREDIT,
        'Complete native groups and scored components; descriptive contrast does not prove combined-objective credit.',
        supported=True, captured=group_count > 0,
        coverage={'eligible_group_component_pairs': group_count})
    scalar = sum('advantage' in r['data'] and r['data'].get('loss_tokens', 0) > 0 for r in uses)
    add('scalar_credit', 'Recorded sample advantages',
        lambda c: c['credit']['kind'] in {'group_relative', 'critic', 'return', 'cached_baseline'} and c['credit']['unit'] in {'sample', 'sequence'},
        lambda c: c['credit']['kind'] in CREDIT and c['credit']['unit'] in {'sample', 'sequence', 'token', 'turn', 'vocabulary'},
        'Positive-mask use receipts with a native scalar advantage; component attribution remains unrecorded.',
        supported=True, captured=scalar > 0, coverage={'eligible_use_receipts': scalar})
    add('teacher_signal', 'Distributional teacher supervision', lambda c: c['supervision'] in {'teacher', 'self_teacher'},
        lambda c: c['supervision'] in SIGNAL,
        'Full-vocabulary or top-k teacher distributions with support/tail semantics remain pending. Prepared sampled-token observations are available separately.')
    from .value_observations import summarize as summarize_values
    values = summarize_values(uses, context)
    value_positions = sum(s['eligible_positions'] for s in values['series'])
    add('critic_credit', 'Value predictions and returns', lambda c: c['credit']['kind'] == 'critic',
        lambda c: c['credit']['kind'] in CREDIT,
        'Aligned native values, return targets and their own mask, with baseline/value-fit role and token/turn/state positions. These do not establish action credit.',
        supported=True, captured=value_positions > 0,
        coverage={'eligible_positions':value_positions, 'unbound_uses':values['unbound_uses']})
    weights = {c['objective']['weighting'] for c in (context['manifest'] or {}).get('components', [])}
    weight_label = ({'hard_gate':'Clipped update contribution', 'capped':'Capped importance weights',
                     'smooth':'Smooth update weights'}.get(next(iter(weights))) if len(weights) == 1 else None)
    add('objective_exposure', weight_label or 'Update weights by behavior', lambda c: c['objective']['weighting'] in {'hard_gate', 'capped', 'smooth'},
        lambda c: c['objective']['weighting'] in {'hard_gate', 'capped', 'smooth', 'none', 'regression'},
        'Native effective coefficients, exact reduction and source-token alignment. Capped, gated and smooth weights stay distinct; operator pending.')
    from .regression_signals import summarize as summarize_regression
    regression = summarize_regression(uses, context)
    add('regression', 'Prediction and target', lambda c:c['objective']['weighting']=='regression',
        lambda c:c['objective']['weighting'] in {'hard_gate','capped','smooth','none','regression'},
        'Sample-level prediction and target bound to the actual objective and confirmed use. Token-level value targets require separate capture.',
        supported=True, captured=regression['eligible_uses']>0,
        coverage={'eligible_use_receipts':regression['eligible_uses'],'unbound_uses':regression['unbound_uses']})
    from .policy_gradients import summarize
    gradient = summarize(uses, context)
    if gradient['observed_uses']:
        result.append({'id':'policy_gradient','label':'Observed policy-loss derivatives','applicability':'applicable',
            'state':'captured' if gradient['compatible_definitions'] and gradient['observed_uses']>gradient['unbound_uses'] else 'missing',
            'requirement':'Native derivative at target log probabilities; includes reduction/backward scaling. Does not establish semantic-unit credit or parameter changes.',
            'coverage':{'observed_uses':gradient['observed_uses'],'unbound_uses':gradient['unbound_uses'],'missing_uses':gradient['missing_uses']}})
    return result
