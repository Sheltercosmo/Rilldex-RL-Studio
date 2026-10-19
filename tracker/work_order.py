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

    def is_ordered(self, event_id):
        event=self.events[event_id]
        return (event.get('order_known') is not False and
                (event.get('batch_size') or 0)<=1 and len(self.groups.get(event_id,[]))<=1)

    def recurrences(self, points):
        """Classify observed identities without imposing order on dispatch members.

        Adjacency and recurrence are separate: a valid immediate edge may follow
        an unresolved earlier occurrence. A complete parallel group may support
        a bracketed return, but never edges between its unordered members.
        """
        routes, seen, ordered = defaultdict(list), defaultdict(dict), defaultdict(dict)
        rows = []
        for point in sorted(points, key=lambda p: self.events[p['event_id']]['index']):
            event = self.events[point['event_id']]
            lane = (event['trajectory_id'], event.get('context_id'))
            route = routes[lane]
            point = {**point, 'order_known': self.is_ordered(point['event_id'])}
            route.append(point)
            index, gid = len(route)-1, point['group_id']
            previous = route[index-1] if index else None
            before = (previous if previous and previous['order_known'] and point['order_known']
                      and previous['group_id'] and previous['identity_status'] not in
                      {'source_gap', 'unreviewed', 'unresolved'} else None)
            _, proof = self.classify(route, index, index)
            if not gid or point['identity_status'] in {'source_gap', 'unreviewed', 'unresolved'}:
                kind, before = 'unresolved', None
            elif not point['order_known']:
                kind = 'unordered'
            elif gid in seen[lane]:
                # Prefer the last ordered endpoint. Intermediate appearances of
                # this identity inside a complete dispatch do not erase it.
                start = ordered[lane].get(gid, seen[lane][gid])
                kind, proof = self.classify(route, start, index)
                if kind == 'interrupted': kind = 'reobserved'
            else:
                kind = 'switch' if before else 'first'
            rows.append({**point, 'kind': kind, 'order_evidence': proof,
                         'previous_event_id': before['event_id'] if before else None,
                         'previous_group_id': before['group_id'] if before else None})
            if gid and kind != 'unresolved':
                seen[lane][gid] = index
                if point['order_known']: ordered[lane][gid] = index
        return rows

    def classify(self, route, start, end):
        old,current = route[start],route[end]
        proof = {'policy':VERSION, 'status':'ordered', 'parallel_groups':[], 'blockers':[],
                 'endpoint_unit_ids':[old['unit_id'],current['unit_id']]}
        segment = route[start:end+1]
        if not old['order_known'] or not current['order_known']:
            proof['blockers'].append('Endpoint order is not established.')
        if any(p['identity_status'] in {'source_gap','unreviewed','unresolved'} for p in segment):
            proof['blockers'].append('Intervening work coverage is incomplete.')
        if any(self.events[p['event_id']].get('order_known') is False for p in segment):
            proof['blockers'].append('Source order is explicitly unestablished.')
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
