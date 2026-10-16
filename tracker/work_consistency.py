"""Qualify macro observations against contradictions in the saved graph.

This is retrospective evidence qualification, not semantic repair or an accuracy
certificate. The unqualified projection remains reproducible without the policy.
"""
from collections import Counter
from copy import deepcopy
from .schema import InputError
from . import work_scope_audit

POLICY = 'exclude-disputed-work/1'
LIMIT = ('Saved whole-work assignments that contradict compatible pair observations are disputed. '
    'Affected switch opportunities are unknown, not failures or non-returns. Counts with disputed '
    'visits are withheld. The check is retrospective and does not establish independent accuracy; '
    'missing or incomparable pair evidence is not a successful validation.')


def validate(value):
    if value != POLICY: raise InputError('Unknown work-consistency policy')
    return value


def qualify(graph, value):
    """Keep original witnesses and groups; qualify only their interpretation."""
    audit = work_scope_audit.project(graph)
    document = ((graph.get('semantic_context') or {}).get('work_subjects') or {}).get('document') or {}
    memberships = {r['unit_id']:r.get('subject_id') for r in document.get('bindings', []) if r['status']=='bound'}
    def conflicts(row):
        subjects = {memberships.get(uid) for uid in row['node_ids']} - {None}
        return [c for c in audit['conflicts'] if subjects & {b['binding']['subject_id'] for b in c['bindings']}]
    def attach(row):
        cases = conflicts(row)
        if cases:
            row['work_conflicts'] = deepcopy(cases)
        return cases
    for row in value['records']:
        if attach(row):
            row['unqualified_category'] = row['category']
            row['category'] = 'disputed'
    for row in value['switches']:
        if attach(row):
            row['unqualified_value'] = row['value']
            row['value'] = None
            row['status'] = 'disputed_work_identity'
    n = sum(r['value'] is True for r in value['switches'])
    d = sum(r['value'] is not None for r in value['switches'])
    value['metrics'] = dict(value=n/d if d else None, numerator=n, denominator=d,
        opportunities=len(value['switches']), unknown=len(value['switches'])-d)
    value['counts'] = dict(Counter(r['category'] for r in value['records']))
    value['coverage'] = {**value['coverage'], 'work_consistency_state':audit['state'],
        'checked_work_pairs':audit.get('counts', {}).get('checked_pairs', 0),
        'work_scope_conflicts':len(audit['conflicts']),
        'disputed_work_visits':sum(bool(r.get('work_conflicts')) for r in value['records']),
        'disputed_work_switches':sum(bool(r.get('work_conflicts')) for r in value['switches'])}
    value['scope_consistency'] = POLICY
    value['work_consistency'] = dict(policy=POLICY, audit_id=audit['id'], state=audit['state'],
        conflicts=deepcopy(audit['conflicts']), checked_pairs=audit.get('counts', {}).get('checked_pairs', 0),
        scope=audit['scope'])
    value['limits'] += ' ' + LIMIT
    return value
