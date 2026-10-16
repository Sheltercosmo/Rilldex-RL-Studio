"""Matched reward comparisons, independent of the learner's aggregation rule.

Only one selected pair is projected. Native prompt groups are required for
within-group comparisons; neither inferred groups nor learner advantages enter.
"""
from collections import Counter, defaultdict
from fractions import Fraction
import math

from .schema import digest, dumps

VERSION = 'reward-relationships/2'
PATTERNS = ('both_above', 'x_above_y_below', 'x_below_y_above', 'both_below', 'at_mean', 'unavailable')


def _identity(sample):
    return dumps({k: sample.get(k) for k in ('schema', 'producer', 'id')})


def _correlation(groups, *, centered):
    pairs = [p for g in groups for p in g]
    if len(pairs) < 2:
        return {'value': None, 'status': 'insufficient_samples'}
    sx = max(abs(p[0]) for p in pairs) or 1
    sy = max(abs(p[1]) for p in pairs) or 1
    scaled = [[(x/sx, y/sy) for x, y in g] for g in groups]
    if not centered:
        scaled = [[p for g in scaled for p in g]]
    residuals = []
    for group in scaled:
        # Center differences from a real row. A constant group then has exact
        # zero residuals even if repeated rounded x/n values would not sum to x.
        ox, oy = group[0]
        mx = math.fsum((x-ox)/len(group) for x, _ in group)
        my = math.fsum((y-oy)/len(group) for _, y in group)
        residuals.extend(((x-ox)-mx, (y-oy)-my) for x, y in group)
    # Rescale residuals too, so tiny variation around a large offset does not
    # underflow when squared. Constant denominators remain undefined.
    ax = max(abs(x) for x, _ in residuals)
    ay = max(abs(y) for _, y in residuals)
    if not ax or not ay:
        return {'value': None, 'status': 'constant_component'}
    residuals = [(x/ax, y/ay) for x, y in residuals]
    xx = math.fsum(x*x for x, _ in residuals)
    yy = math.fsum(y*y for _, y in residuals)
    xy = math.fsum(x*y for x, y in residuals)
    value = xy/math.sqrt(xx)/math.sqrt(yy)
    return {'value': max(-1., min(1., value)), 'status': 'measured'}


def summarize(rows):
    matched = [r for r in rows if r['matched']]
    groups = defaultdict(list)
    for row in matched:
        if row['group_status'] == 'complete':
            groups[row['group_id']].append((row['x']['value'], row['y']['value']))
    return {
        'samples': len(rows), 'matched_samples': len(matched),
        'missing_either': len(rows)-len(matched),
        'x_states': dict(Counter(r['x']['status'] for r in rows)),
        'y_states': dict(Counter(r['y']['status'] for r in rows)),
        'correlation': _correlation([[(r['x']['value'], r['y']['value']) for r in matched]], centered=False),
        'within_group_correlation': _correlation(list(groups.values()), centered=True),
        'within_group_samples': sum(map(len, groups.values())),
        'complete_groups': len(groups),
        'group_states': dict(Counter({gid: r['group_status'] for r in rows
                                     if (gid := r.get('group_id'))}.values())),
        'missing_group_samples': sum(r.get('group_id') is None for r in rows),
        'patterns': {key: sum(r.get('reward_pattern') == key for r in rows) for key in PATTERNS},
    }


def assign_patterns(records):
    """Classify observed deviations, not preference, advantage or model behavior."""
    groups = defaultdict(list)
    for row in records:
        row['reward_pattern'] = 'unavailable'
        if row['group_status'] == 'complete': groups[row['group_id']].append(row)
    for rows in groups.values():
        sides = []
        for axis in ('x', 'y'):
            # Compare n*x with the sum of the represented scores exactly.
            # Scaling floats can erase small deviations after cancellation,
            # incorrectly turning an above/below observation into a tie.
            values = [Fraction(r[axis]['value']) for r in rows]
            total = sum(values)
            sides.append([1 if v*len(values) > total else -1 if v*len(values) < total else 0
                          for v in values])
        for row, x, y in zip(rows, *sides):
            row['reward_pattern'] = ('at_mean' if x == 0 or y == 0 else
                'both_above' if x > 0 and y > 0 else 'both_below' if x < 0 and y < 0 else
                'x_above_y_below' if x > 0 else 'x_below_y_above')


def project(samples, rewards, scored, sample_ref, *, x=None, y=None):
    components = [{k: r[k] for k in ('id', 'producer', 'component', 'definition')} for r in rewards]
    base = {'schema': VERSION, 'components': components, 'selected': None, 'points': [], 'records': []}
    if len(components) < 2:
        return {**base, 'status': 'needs_two_components'}
    indexed = {c['id']: c for c in components}
    keys = {c['id']: {k: c[k] for k in ('producer', 'component', 'definition')} for c in components}
    scores = {c['id']: [scored(s, keys[c['id']]) for s in samples] for c in components}
    memberships = {key: {i for i, r in enumerate(rows) if r['status'] == 'scored'} for key, rows in scores.items()}
    if x or y:
        if x not in indexed or y not in indexed or x == y:
            return {**base, 'status': 'selection_unavailable', 'requested': {'x': x, 'y': y}}
    else:
        # Prefer useful overlap, with stable identifiers breaking ties. No
        # correlation-driven selection or recipe-dependent sample filtering.
        order = sorted(indexed, key=lambda k: (-len(memberships[k]), k))
        x, y = order[:2]
        for candidate in order:
            peers = sorted((p for p in order if p != candidate),
                           key=lambda p: (-len(memberships[candidate] & memberships[p]), p))
            if memberships[candidate] & memberships[peers[0]]:
                x, y = candidate, peers[0]
                break
    groups = {}
    rx = next(r for r in rewards if r['id'] == x)
    ry = next(r for r in rewards if r['id'] == y)
    gy = {g['group_id']: g for g in ry['groups']}
    for gx in rx['groups']:
        other = gy[gx['group_id']]
        statuses = sorted({g['status'] for g in (gx, other) if g['status'] != 'complete'})
        groups[gx['group_id']] = '+'.join(statuses) if statuses else 'complete'
    records = []
    for i, sample in enumerate(samples):
        a, b = scores[x][i], scores[y][i]
        records.append({**sample_ref(sample), 'step': sample.get('step'), 'task_id': sample.get('task_id'),
            'group_id': sample.get('group_id'), 'group_status': groups.get(sample.get('group_id'), 'not_recorded'),
            'matched': a['status'] == b['status'] == 'scored', 'x': a, 'y': b})
    records.sort(key=_identity)
    assign_patterns(records)
    # A group with conflicting step metadata is excluded globally before the
    # per-step slice. It must never become a seemingly complete local group.
    points = [{'step': step, **summarize([r for r in records if r['step'] == step]),
               'records': [r for r in records if r['step'] == step]}
              for step in sorted({r['step'] for r in records if r['step'] is not None})]
    return {**base, 'status': 'available', 'selected': {'x': indexed[x], 'y': indexed[y]},
        'id': 'reward-pair-' + digest({'x': keys[x], 'y': keys[y]}), **summarize(records),
        'missing_step_samples': sum(r['step'] is None for r in records), 'points': points, 'records': records,
        'boundary': 'Pearson correlation on exactly matched sample scores. Within-group correlation pools '
            'deviations from each complete native prompt-group mean, without variance normalization. '
            'Unequal reward scales and group sizes affect this descriptive statistic. No reward weights, '
            'advantage estimator, objective direction, gradient conflict or causal learning effect is inferred.'}
