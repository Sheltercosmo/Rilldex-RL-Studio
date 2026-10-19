"""Source ordering for annotated-unit comparisons, independent of graph layout."""
from .work_order import Evidence

VERSION='graph-unit-order/1'


class Ordering:
    def __init__(self,graph):
        self.events={n['properties']['id']:n['properties'] for n in graph['nodes']
                     if n['kind']=='event' and 'id' in n['properties']}
        native={key:value for key,value in self.events.items() if 'kind' in value and 'trajectory_id' in value}
        self.native=Evidence(native)

    def source(self,node):
        p=node['properties']
        return self.events.get(p.get('source',{}).get('event_id'),p)

    def event_id(self,node):
        return node['properties'].get('source',{}).get('event_id') or (node['properties'].get('id') if node['kind']=='event' else None)

    def scope(self,node):
        return node.get('trajectory_id'),self.source(node).get('context_id')

    def projection(self,graph):
        """Small source facts for the renderer; no inferred semantic edges."""
        rows={}
        for n in graph['nodes']:
            if n['kind'] not in {'event','unit'}:continue
            span=n['properties'].get('source',{})
            rows[n['id']]=dict(scope=list(self.scope(n)),event_id=self.event_id(n),
                index=n.get('event_index'),start=span.get('start',0),
                end=len(n['properties'].get('text','')) if n['kind']=='event' else span.get('end'),
                hidden=self.hidden(n),reason=self.reason(n))
        return dict(version=VERSION,nodes=rows)

    @staticmethod
    def key(node):
        return (node['event_index'],node['properties'].get('source',{}).get('start',0),node['id'])

    def hidden(self,node):
        p=self.source(node)
        return bool(p.get('copied_context') or p.get('agent_visible') is False or
                    p.get('agent_visibility')=='not_established' or p.get('kind','').startswith('external_'))

    def parallel_siblings(self,left,right):
        a,b=self.event_id(left),self.event_id(right)
        group=self.native.groups.get(a,[])
        return a!=b and len(group)>1 and b in group

    def reason(self,node):
        if self.hidden(node):return 'unavailable_source'
        if self.source(node).get('order_known') is False:return 'unresolved_source_order'
        eid=self.event_id(node)
        if eid in self.native.events and not self.native.is_ordered(eid):return 'parallel_dispatch'
        if node.get('event_index') is None:return 'missing_source_index'
        return None

    def before(self,left,right,*,at_end=False):
        """None means established source order, never execution or causality."""
        if self.scope(left)!=self.scope(right):return 'different_context_or_trajectory'
        if self.hidden(left) or self.hidden(right):return 'unavailable_source'
        le,re=self.event_id(left),self.event_id(right)
        if le is not None and le==re:
            # A source span can be ordered inside one expression even when that
            # expression's position among parallel records is not established.
            a=left['properties'].get('source',{});b=right['properties'].get('source',{})
            lo=a.get('end');hi=b.get('end' if at_end else 'start')
            if left['kind']=='event':lo=len(left['properties'].get('text',''))
            if right['kind']=='event':hi=len(right['properties'].get('text','')) if at_end else 0
            return None if type(lo) is int and type(hi) is int and lo<=hi else 'overlapping_or_missing_spans'
        reason=self.reason(left) or self.reason(right)
        if reason:return reason
        return None if left['event_index']<right['event_index'] else 'overlapping_or_missing_spans'

    def prefix(self,anchor,candidates):
        """Stop at the first unknown adjacency; do not bridge past it."""
        previous=anchor;retained=[]
        for candidate in candidates:
            reason=self.before(previous,candidate)
            if reason:return retained,dict(from_unit=previous['id'],to_unit=candidate['id'],reason=reason)
            retained.append(candidate);previous=candidate
        reason=self.reason(anchor) if not candidates else None
        return retained,(dict(from_unit=anchor['id'],to_unit=None,reason=reason) if reason else None)
