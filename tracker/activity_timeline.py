"""Source-order activity lanes, preserving gaps, overlap and observer identity.

This is a descriptive projection of already validated activity packets. It does
not run inference, bridge unknown units, or interpret an activity as a strategy.
"""
from collections import Counter, defaultdict

from .schema import digest, InputError

VERSION = 'activity-timeline/1'
DEFINITION = ('Each column is one eligible source unit, in recorded order within one actor and unit kind. '
              'Windows contain consecutive units, including unknowns; they are not time durations or phases. '
              'Model spans and dispatches have separate denominators. Tool enumeration does not establish execution order. '
              'Cells retain raw selected options; evidence/link limitations affect availability only. '
              'Counts overlap and do not establish accuracy, progress, causation or a training shift.')


def _state(unit, field):
    if not unit['current_packet']:
        return {'value': None, 'availability': unit['status'], 'reason': 'No current exact-packet observation.'}
    answer = unit['observation'].get(field)
    if not answer:
        return {'value': None, 'availability': 'not_requested', 'reason': 'No recorded field decision.'}
    value = answer.get('value')
    if answer.get('evidence_gate'):
        available, reason = 'evidence_limited', answer['evidence_gate']
    elif answer.get('status') != 'decided' or value not in {'present', 'absent'}:
        available, reason = 'unresolved', 'The supplied unresolved option won, or no usable membership was recorded.'
    elif field in unit['unresolved_activities']:
        available, reason = 'link_limited', 'Required relationship evidence is unavailable; the raw membership remains selected.'
    else:
        available, reason = 'available', None
    return {'value': value, 'availability': available, 'reason': reason}


def build(annotated, taxonomy, measurement, *, window_size=20):
    if isinstance(window_size, bool) or not isinstance(window_size, int) or not 1 <= window_size <= 100:
        raise InputError('Activity windows require 1–100 source units')
    profiles, grouped = {}, defaultdict(list)
    for unit in annotated:
        if not unit['eligible'] or unit['kind'] not in {'model_span', 'action_dispatch'}:
            continue
        profile_id = None
        if unit['current_packet']:
            p = unit['observation']['_provenance']
            profile = {**measurement, **{k: p[k] for k in ('model', 'harness', 'selection_policy')}}
            profile_id = digest(profile)
            profiles[profile_id] = profile
        grouped[(unit['trajectory_id'], unit['kind'])].append({
            **{k: unit[k] for k in ('id', 'event_id', 'event_index', 'start', 'end')},
            'profile_id': profile_id, 'states': {field: _state(unit, field) for field in taxonomy}})
    streams = []
    for (actor, kind), rows in grouped.items():
        rows.sort(key=lambda u: (u['event_index'], u['start'], u['end'], u['id']))
        available_profiles = list(dict.fromkeys(u['profile_id'] for u in rows if u['profile_id'])) or [None]
        views = []
        for profile_id in available_profiles:
            windows = []
            for start in range(0, len(rows), window_size):
                selected = rows[start:start+window_size]
                counts = {}
                for field in taxonomy:
                    values, unknown_reasons, raw = Counter(), Counter(), Counter()
                    for row in selected:
                        state = row['states'][field]
                        availability = 'other_profile' if row['profile_id'] and row['profile_id'] != profile_id else state['availability']
                        if availability == 'available':
                            values[state['value']] += 1
                        else:
                            values['unknown'] += 1; unknown_reasons[availability] += 1
                        # A different observer's winner is not this profile's observation.
                        raw[state['value'] if row['profile_id'] == profile_id and state['value'] else 'unobserved'] += 1
                    counts[field] = {k: values[k] for k in ('present', 'absent', 'unknown')}
                    counts[field].update(denominator=len(selected), unknown_reasons=dict(unknown_reasons), selected_options=dict(raw))
                windows.append({'start': start, 'end': start+len(selected), 'fields': counts})
            views.append({'profile_id': profile_id, 'windows': windows})
        streams.append({'trajectory_id': actor, 'kind': kind, 'units': rows, 'views': views})
    return {'version': VERSION, 'window_size': window_size, 'field_order': list(taxonomy), 'definition': DEFINITION,
            'profiles': profiles, 'streams': streams}
