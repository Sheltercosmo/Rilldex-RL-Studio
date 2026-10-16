"""Compare captured dispatch fields, without inferring a change of strategy.

Callers supply the relationship that makes a pair worth comparing. Equality of
these records never implies equality of files, environment, state or effects.
"""
from .schema import digest, dumps
from .work_order import Evidence

VERSION = 'recorded-action-comparison/1'
MAX_BYTES = 524288
MAX_CHANGES = 64
MAX_DEPTH = 32
PREVIEW = 360
LIMIT = ('Compares captured dispatch fields only. Unchanged calls can operate on changed files or '
    'environment state. Text-only exports do not establish native argument equality. '
    'Intervening work is context, not evidence of a causal repair or a new strategy.')


def source(graph, node_id):
    nodes = {n['id']:n for n in graph['nodes']}
    node = nodes.get(node_id)
    if not node: return None
    if node['kind'] == 'unit':
        ref = node['properties'].get('source', {})
        eid = 'event:'+str(ref.get('event_id'))
        if not any(e['type']=='grounded_in' and e['source']==node_id and e['target']==eid for e in graph['edges']):
            return None
        parent = nodes.get(eid)
        if not parent: return None
        text = parent['properties'].get('text','')
        a,b = ref.get('start'),ref.get('end')
        if (type(a) is not int or type(b) is not int or not 0<=a<b<=len(text)
                or text[a:b]!=ref.get('text') or node['trajectory_id']!=parent['trajectory_id']
                or node['properties'].get('actor')!=parent['properties'].get('actor')):
            return None
        node = parent
    if node['kind']!='event' or node['properties'].get('kind')!='action': return None
    p = node['properties']
    if p.get('copied_context'): return None
    return {**p,'index':node['event_index'],'trajectory_id':node['trajectory_id'],'node_id':node['id']}


def descriptor(value, present=True):
    if not present: return dict(present=False)
    display = value if isinstance(value,str) else dumps(value)
    return dict(present=True,type=type(value).__name__,preview=display[:PREVIEW],
        characters=len(display),truncated=len(display)>PREVIEW,value_hash=digest(value))


def changed_span(before, after):
    """One exact contiguous differing span; not a semantic edit explanation."""
    start=0;limit=min(len(before),len(after))
    while start<limit and before[start]==after[start]:start+=1
    tail=0
    while tail<limit-start and before[len(before)-tail-1]==after[len(after)-tail-1]:tail+=1
    a_end=len(before)-tail;b_end=len(after)-tail
    return dict(before_start=start,before_end=a_end,after_start=start,after_end=b_end,
        before=descriptor(before[start:a_end]),after=descriptor(after[start:b_end]))


def difference(before, after):
    changes=[];truncated=False
    def visit(a,b,path,depth=0,has_a=True,has_b=True):
        nonlocal truncated
        if has_a and has_b and dumps(a)==dumps(b):return
        if len(changes)>=MAX_CHANGES:truncated=True;return
        if has_a and has_b and isinstance(a,dict) and isinstance(b,dict) and depth<MAX_DEPTH:
            for key in sorted(set(a)|set(b)):
                pointer=path+'/'+key.replace('~','~0').replace('/','~1')
                visit(a.get(key),b.get(key),pointer,depth+1,key in a,key in b)
            return
        row=dict(path=path,kind='added' if not has_a else 'removed' if not has_b else 'changed',
            before=descriptor(a,has_a),after=descriptor(b,has_b))
        if has_a and has_b and isinstance(a,str) and isinstance(b,str):row['text_span']=changed_span(a,b)
        changes.append(row)
    visit(before,after,'')
    return changes,truncated


def recorded_fields(event):
    from .tool_contracts import arguments
    if (not isinstance(event.get('arguments'),dict) or event.get('arguments_available') is False
            or event.get('argument_status')=='invalid_json_object'
            or not isinstance(event.get('tool'),str) or not event['tool']):return None
    try:
        captured=arguments(event.get('raw_arguments',event['arguments']))
        if dumps(captured)!=dumps(event['arguments']):return None
    except (ValueError,RecursionError):return None
    return dict(tool=event['tool'],arguments=captured)


def compare(graph, previous_id, current_id):
    previous,current=source(graph,previous_id),source(graph,current_id)
    value=dict(schema=VERSION,graph_id=graph['id'],previous_node_id=previous_id,current_node_id=current_id,
        status='unavailable',basis=None,ordering='unestablished',changes=[],changes_truncated=False,reason=None,limits=LIMIT)
    def finish():return dict(id='action-comparison-'+digest(value),**value)
    if previous is None or current is None:
        value['reason']='Exact action-to-source binding is unavailable.';return finish()
    value['sources']=[dict(node_id=n['node_id'],event_id=n['id'],event_index=n['index'],
        source_pointer=n.get('source_pointer'),content_hash=digest(n.get('text',''))) for n in (previous,current)]
    if any(previous.get(k)!=current.get(k) for k in ('actor','trajectory_id','context_id')):
        value['reason']='Actions have different actors or source contexts.';return finish()
    if previous['index']>=current['index']:
        value['reason']='An earlier source position is not established.';return finish()
    events={n['properties']['id']:{**n['properties'],'index':n['event_index'],'trajectory_id':n['trajectory_id']}
        for n in graph['nodes'] if n['kind']=='event'}
    groups=Evidence(events).groups
    if current['id'] in groups.get(previous['id'],[]):
        value['reason']='Sibling dispatches have no recorded mutual order.';return finish()
    value['ordering']='source_order'
    a,b=recorded_fields(previous),recorded_fields(current)
    if a is not None and b is not None:
        value['basis']='recorded_fields'
    elif all(isinstance(n.get('text'),str) and n['text'].strip() for n in (previous,current)):
        a,b=({'text':n['text']} for n in (previous,current))
        value['basis']='recorded_text'
        value['basis_note']='Structured inputs are unavailable or ambiguous on at least one endpoint; only recorded action text is compared.'
    else:
        value['reason']='Comparable recorded fields or action text are unavailable.';return finish()
    if max(len(dumps(v).encode('utf-8')) for v in (a,b))>MAX_BYTES:
        value['reason']='Recorded inputs exceed the bounded comparison size.';return finish()
    value['status']='unchanged' if dumps(a)==dumps(b) else 'changed'
    value['changes'],value['changes_truncated']=difference(a,b)
    value['captured_hashes']=[digest(a),digest(b)]
    return finish()
