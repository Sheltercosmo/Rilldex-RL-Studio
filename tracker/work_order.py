"""Evidence for recurrence across fully observed, bracketed parallel dispatches.

This is source-contribution order, not execution/completion causality. An
unordered endpoint or incomplete batch remains unresolved. Nothing here infers
work identity, method change, exploration, or successful recovery.
"""
from collections import defaultdict
from .schema import InputError, digest

VERSION = 'bracketed-parallel/1'


def validate(value):
    if value != VERSION: raise InputError('Unknown work recurrence ordering policy')


class Evidence:
    def __init__(self, events):
        self.events = events
        self.groups = {}
        # Parent message or native message index identifies a dispatch group.
        # Both keys may be present. Join overlapping groups without privileging
        # one source representation or treating display positions as identities.
        parent = {eid:eid for eid in events}
        def root(eid):
            while parent[eid] != eid:
                parent[eid] = parent[parent[eid]]; eid = parent[eid]
            return eid
        keyed = {}
        for eid,e in events.items():
            if e['kind'] != 'action': continue
            lane = (e['trajectory_id'], e.get('actor'), e.get('context_id'))
            for field in ('parent_id', 'source_message_index'):
                if e.get(field) in (None, ''): continue
                key = (*lane,field,e[field])
                if key in keyed: parent[root(eid)] = root(keyed[key])
                else: keyed[key] = eid
        components = defaultdict(list)
        for eid,e in events.items():
            if e['kind'] == 'action': components[root(eid)].append(eid)
        for members in components.values():
            group = sorted(members)
            for eid in members: self.groups[eid] = group

    def classify(self, route, start, end):
        old,current = route[start],route[end]
        proof = {'policy':VERSION, 'status':'ordered', 'parallel_groups':[], 'blockers':[],
                 'endpoint_unit_ids':[old['unit_id'],current['unit_id']]}
        segment = route[start:end+1]
        if not old['order_known'] or not current['order_known']:
            proof['blockers'].append('Endpoint order is not established.')
        if any(p['identity_status'] in {'source_gap','unreviewed','unresolved'} for p in segment):
            proof['blockers'].append('Intervening work coverage is incomplete.')
        lo,hi = self.events[old['event_id']]['index'],self.events[current['event_id']]['index']
        by_event = defaultdict(list)
        for p in segment: by_event[p['event_id']].append(p)
        seen = set()
        for p in segment[1:-1]:
            if p['order_known']: continue
            members = self.groups.get(p['event_id'], [p['event_id']])
            key = tuple(members)
            if key in seen: continue
            seen.add(key)
            declared = max(self.events[eid].get('batch_size',0) or 0 for eid in members)
            complete = (len(members) > 1 and len(members) >= declared
                and all(eid in by_event and lo < self.events[eid]['index'] < hi for eid in members))
            if not complete:
                proof['blockers'].append('A parallel dispatch group is incomplete or crosses a recurrence endpoint.')
            proof['parallel_groups'].append({'id':'dispatch-group-'+digest(members), 'event_ids':members,
                'unit_ids':sorted({x['unit_id'] for eid in members for x in by_event[eid] if x['unit_id']}),
                'fully_bracketed':complete, 'mutual_order':'unknown'})
        proof['blockers'] = list(dict.fromkeys(proof['blockers']))
        proof['parallel_groups'].sort(key=lambda x:x['id'])
        if proof['blockers']:
            proof['status'] = 'unresolved'; category = 'interrupted'
        else:
            if proof['parallel_groups']: proof['status'] = 'bracketed_parallel'
            between = segment[1:-1]
            category = ('returned' if any(p['group_id'] and p['group_id'] != current['group_id'] for p in between)
                        else 'resumed' if between else 'continued')
        return category, proof
