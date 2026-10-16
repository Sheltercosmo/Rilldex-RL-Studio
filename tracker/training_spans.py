"""Exact token-to-source joins over a pinned graph, never semantic attribution.

The producer supplies code-point spans for native target tokens. We validate the
source identity again at read time. A token crossing unit boundaries is withheld,
not fractionally assigned or attached to the nearest unit.
"""
from collections import Counter, defaultdict
import json
import math
import heapq

from .schema import InputError, digest

VERSION = 'training-token-source/1'
PROJECTION = 'training-unit-exposure/1'


def unavailable(reason):
    return {'schema': VERSION, 'status': 'unavailable', 'reason': reason}


def authored(event):
    return (event['actor'] == 'agent' and not event.get('copied_context')
            and event.get('agent_visibility') != 'not_established'
            and not event['kind'].startswith('external_')
            and event['kind'] not in {'context', 'feedback'})


def validate(value, length):
    if not isinstance(value, dict) or value.get('schema') != VERSION:
        raise InputError('Token source needs training-token-source/1')
    if value.get('status') == 'unavailable':
        if set(value) != {'schema', 'status', 'reason'} or not isinstance(value['reason'], str) or not 1 <= len(value['reason']) <= 500:
            raise InputError('Unavailable token source needs one bounded reason')
        return value
    if set(value) != {'schema', 'status', 'basis', 'source_hash', 'spans'} or value['status'] != 'mapped':
        raise InputError('Mapped token source needs basis, source hash and aligned spans')
    for key in ('basis', 'source_hash'):
        if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 500:
            raise InputError('Token source '+key+' must be bounded text')
    if not isinstance(value['spans'], list) or len(value['spans']) != length:
        raise InputError('Token source spans must align with native target tokens')
    for span in value['spans']:
        if span is None:
            continue  # Explicitly unmapped, including non-text special tokens.
        if not isinstance(span, dict) or set(span) != {'event_id', 'start', 'end'}:
            raise InputError('A token source span needs event_id, start and end')
        if not isinstance(span['event_id'], str) or not 1 <= len(span['event_id']) <= 500:
            raise InputError('Invalid token source event')
        if type(span['start']) is not int or type(span['end']) is not int or not 0 <= span['start'] < span['end']:
            raise InputError('Token source offsets must be positive-width Unicode code-point intervals')
    return value


def from_tokenizer(tokenizer, target_ids, run, event_id):
    """Conservative fast-tokenizer bridge; no model calls or fuzzy alignment.

    Both decoding and re-encoding must match. Special IDs have no text mapping.
    Native generation is unaffected when normalization makes this unavailable.
    """
    event = next((e for e in run['events'] if e['id'] == event_id), None)
    if event is None or not authored(event):
        return unavailable('A unique model-authored source event is not available')
    if not getattr(tokenizer, 'is_fast', False):
        return unavailable('The tokenizer does not provide validated text offsets')
    text = event['text']
    try:
        if tokenizer.decode(target_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False) != text:
            return unavailable('Native target decoding differs from recorded source text')
        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        special = set(tokenizer.all_special_ids)
        ordinary = [t for t in target_ids if t not in special]
        if list(encoded['input_ids']) != ordinary or any(t in special for t in encoded['input_ids']):
            return unavailable('Source re-encoding differs from native non-special target IDs')
        offsets = list(encoded['offset_mapping'])
        if len(offsets) != len(ordinary) or any(type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text) for a,b in offsets):
            return unavailable('Tokenizer offsets cannot be represented as positive-width code-point spans')
        spans = []; cursor = 0
        for token in target_ids:
            if token in special:
                spans.append(None)
            else:
                a,b = offsets[cursor]; cursor += 1
                spans.append({'event_id': event_id, 'start': a, 'end': b})
        return validate({'schema': VERSION, 'status': 'mapped',
            'basis': 'Exact decode and native non-special ID round-trip; fast-tokenizer Unicode code-point offsets; special tokens unmapped',
            'source_hash': digest(run), 'spans': spans}, len(target_ids))
    except (TypeError, ValueError, KeyError, NotImplementedError):
        return unavailable('The tokenizer cannot provide an exact native-ID/source-text mapping')


def _summary(indices, signal):
    selected = [i for i in indices if signal['loss_mask'][i]]
    values = [signal['d_loss_d_logp'][i] for i in selected]
    try: magnitude = math.fsum(abs(v) for v in values)
    except OverflowError: magnitude = None
    return {'mapped_tokens': len(indices), 'eligible_tokens': len(selected),
        'nonzero_derivatives': sum(v != 0 for v in values), 'zero_derivatives': sum(v == 0 for v in values),
        'mean_absolute_derivative': magnitude/len(values) if values and magnitude is not None else None}


def project(run, graph, signal):
    """Partition tokens once among exact semantic units; preserve all gaps."""
    from .policy_gradients import validate as validate_signal
    from .graph_store import validate as validate_graph
    validate_signal(signal); validate_graph(graph)
    if graph['run_id'] != run['id'] or graph['source_hash'] != digest(run):
        raise InputError('Training span projection requires the exact source graph')
    base = {'schema': PROJECTION, 'run_id': run['id'], 'graph_id': graph['id'],
        'source_hash': digest(run), 'annotation_hash': graph.get('annotation_hash'),
        'total_tokens': len(signal['target_tokens']), 'eligible_tokens': sum(signal['loss_mask']),
        'units': [], 'activities': [], 'events': [], 'coverage': {},
        'meaning': 'Token membership in saved source units, with the observed policy-loss derivative. No causal credit, parameter-change attribution or new semantic classification. Crossing/overlapping units are withheld.'}
    mapping = signal.get('source_alignment')
    if mapping is None or mapping['status'] != 'mapped':
        return {**base, 'status': 'unavailable', 'reason': mapping['reason'] if mapping else 'Token source mapping was not recorded'}
    if mapping['source_hash'] != digest(run):
        return {**base, 'status': 'source_mismatch', 'reason': 'Token mapping and pinned sample source have different immutable hashes'}
    events = {e['id']: e for e in run['events']}
    for span in mapping['spans']:
        if span is not None and (span['event_id'] not in events or span['end'] > len(events[span['event_id']]['text'])):
            return {**base, 'status': 'invalid_source_spans', 'reason': 'A token mapping points outside its pinned source'}
    candidates = defaultdict(list)
    for node in graph['nodes']:
        if node['kind'] != 'unit': continue
        source = node['properties'].get('source', {})
        e = events.get(source.get('event_id'))
        a,b = source.get('start'), source.get('end')
        if e is None or type(a) is not int or type(b) is not int or not 0 <= a < b <= len(e['text']) or source.get('text') != e['text'][a:b]:
            return {**base, 'status': 'invalid_unit_spans', 'reason': 'A saved unit does not match its pinned source interval'}
        candidates[e['id']].append(node)
    groups = defaultdict(list); source_groups = defaultdict(list); statuses = Counter(); eligible_statuses = Counter()
    # Sweep source positions. Native training tokens may be packed/reordered;
    # this ordering is for the join only and never changes the native arrays.
    for eid in candidates:
        candidates[eid].sort(key=lambda n: n['properties']['source']['start'])
    token_order = sorted(enumerate(mapping['spans']), key=lambda item: (item[1]['event_id'],item[1]['start'],item[1]['end']) if item[1] else ('',-1,-1))
    active = {}; ends = []; cursor = 0; current_event = None
    for i, span in token_order:
        state = 'unmapped_token'
        if span is not None:
            e = events[span['event_id']]; source_groups[e['id']].append(i)
            if not authored(e):
                state = 'non_agent_source'
            else:
                if current_event != e['id']:
                    active = {}; ends = []; cursor = 0; current_event = e['id']
                nodes = candidates[e['id']]
                while cursor < len(nodes) and nodes[cursor]['properties']['source']['start'] < span['end']:
                    n = nodes[cursor]; active[n['id']] = n
                    heapq.heappush(ends,(n['properties']['source']['end'],n['id'])); cursor += 1
                while ends and ends[0][0] <= span['start']:
                    active.pop(heapq.heappop(ends)[1],None)
                intersects = [n for n in active.values() if n['properties']['source']['start'] < span['end']]
                inside = [n for n in intersects if n['properties']['source']['start'] <= span['start'] and n['properties']['source']['end'] >= span['end']]
                if len(intersects) == 1 and len(inside) == 1:
                    groups[inside[0]['id']].append(i); state = 'unit_assigned'
                elif len(intersects) > 1:
                    state = 'boundary_or_overlap'
                elif intersects:
                    state = 'boundary_or_overlap'
                else:
                    state = 'unannotated_source'
        statuses[state] += 1
        if signal['loss_mask'][i]: eligible_statuses[state] += 1
    activity_groups = defaultdict(list)
    for node in graph['nodes']:
        if node['kind'] != 'unit': continue
        indices = groups[node['id']]
        source = node['properties']['source']
        row = {'id': node['id'], 'activity': node.get('activity'), 'source': source, **_summary(indices, signal)}
        base['units'].append(row)
        activity_groups[node.get('activity') or 'unlabeled'].extend(indices)
    base['activities'] = [{'activity': k, **_summary(v, signal)} for k,v in sorted(activity_groups.items())]
    base['events'] = [{'event_id': k, 'source_pointer': events[k]['source_pointer'], **_summary(v, signal)} for k,v in source_groups.items()]
    base['coverage'] = {'all_tokens': dict(statuses), 'eligible_tokens': dict(eligible_statuses)}
    return {**base, 'status': 'mapped', 'basis': mapping['basis']}


def inspect_use(store, selector, graph_id):
    """Read one immutable use and its exact sample/source, using indexed keys."""
    from . import training_lineage, training_samples, training_recipes, policy_gradients, graph_store
    if not isinstance(selector, dict) or set(selector) != {'schema', 'producer', 'experiment', 'id'}:
        raise InputError('Training use identity needs schema, producer, experiment and id')
    for key, value in selector.items(): training_lineage.text(value, key)
    if selector['schema'] not in {training_lineage.VERSION, training_samples.VERSION}:
        raise InputError('Unknown training use identity schema')
    independent = selector['schema'] == training_samples.VERSION
    table = 'training_sample_records' if independent else 'training_records'
    sample_key = 'sample_id' if independent else 'rollout_id'
    graph = graph_store.read(store, graph_id)
    result = {'schema': PROJECTION, 'use': selector, 'graph_id': graph_id}
    with store.connect() as c:
        row = c.execute(f'SELECT * FROM {table} WHERE producer=? AND experiment=? AND record_id=? AND revision=0 AND kind=?',
                        (selector['producer'], selector['experiment'], selector['id'], 'use')).fetchone()
        if row is None: raise KeyError('Training use not found')
        use = json.loads(row['document'])
        result.update(stage=use['data']['stage'], learner_step=use['data']['learner_step'])
        samples = c.execute(f'SELECT document FROM {table} WHERE experiment=? AND sample_producer=? AND {sample_key}=? AND kind=?',
                            (selector['experiment'], row['sample_producer'], row[sample_key], 'sample')).fetchall()
        if len(samples) != 1:
            return {**result, 'status': 'sample_unresolved', 'reason': 'The use lacks one unambiguous sample declaration'}
        sample = json.loads(samples[0]['document'])
        mapping = sample['data'].get('source') if independent else {'producer': row['sample_producer'],
            'rollout_id': row[sample_key], 'revision': sample['evidence'].get('source_revision')}
        if not mapping or mapping.get('revision') is None:
            return {**result, 'status': 'source_unresolved', 'reason': 'The sample has no pinned source revision'}
        if not independent and use['evidence'].get('source_revision', mapping['revision']) != mapping['revision']:
            return {**result, 'status': 'source_mismatch', 'reason': 'Use and sample declare different source revisions'}
        source = c.execute('SELECT r.document FROM rollout_revisions v JOIN runs r ON r.id=v.run_id WHERE v.producer=? AND v.rollout_id=? AND v.revision=?',
                            (mapping['producer'], mapping['rollout_id'], mapping['revision'])).fetchone()
        if source is None:
            return {**result, 'status': 'source_unresolved', 'reason': 'The pinned source revision has not arrived'}
        run = json.loads(source[0])
        if run['metadata'].get('experiment', selector['experiment']) != selector['experiment']:
            return {**result, 'status': 'source_mismatch', 'reason': 'Sample and source experiments differ'}
        if independent and training_samples.binding_status(run, mapping) == 'invalid_source_spans':
            return {**result, 'status': 'source_mismatch', 'reason': 'The sample source spans no longer match the pinned source'}
        context = training_recipes.resolve(training_recipes.records(c, selector['experiment']), selector['experiment'], use['data'].get('recipe'))
    result['recipe_context'] = context
    signal = use['data'].get('policy_gradient')
    if signal is None:
        return {**result, 'status': 'unavailable', 'reason': 'Native token derivatives were not recorded for this use'}
    if policy_gradients.binding(signal, context) != 'bound':
        return {**result, 'status': 'component_unresolved', 'reason': 'The derivative component has no resolved training settings'}
    result.update(projection=project(run, graph, signal), status='available')
    result['snapshot_id'] = 'training-spans-'+digest(result)
    return result
