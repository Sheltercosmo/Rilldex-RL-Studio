"""Deterministic, source-bound joins from a dispatch to its latest prior lookup.

Queries are explicit researcher configuration, not interpretations of natural
language requirements. Results concern recorded arguments and returned data.
"""
from copy import deepcopy
import json
import re
from .schema import InputError,digest
from .capabilities import links, recorded_scope, batch_key

VERSION='history-evidence-query/1'
GRAPH_VERSION='history-evidence-graph/2'


def tokens(pointer):
    if not isinstance(pointer,str) or (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])',pointer):
        raise InputError('Expected a JSON pointer, optionally with wildcard segments')
    return [] if pointer=='' else [p.replace('~1','/').replace('~0','~') for p in pointer[1:].split('/')]


def select(value,pointer):
    """Return exact decoded JSON paths and whether all requested branches exist."""
    rows=[{'pointer':'','value':value}];complete=True
    for token in tokens(pointer):
        next_rows=[]
        for row in rows:
            obj=row['value']
            if token=='*':
                children=list(obj.items()) if isinstance(obj,dict) else list(enumerate(obj)) if isinstance(obj,list) else None
                if children is None:complete=False;continue
            elif isinstance(obj,dict) and token in obj:children=[(token,obj[token])]
            elif isinstance(obj,list) and re.fullmatch(r'0|[1-9][0-9]*',token) and int(token)<len(obj):children=[(token,obj[int(token)])]
            else:complete=False;continue
            for key,item in children:
                part=str(key).replace('~','~0').replace('/','~1')
                next_rows.append({'pointer':row['pointer']+'/'+part,'value':item})
        rows=next_rows
    return rows,complete


def validate(query):
    if not isinstance(query,dict) or set(query)!={'schema','name','target','history','rows','key','checks','quantifier','invalidate_on'} or query['schema']!=VERSION:
        raise InputError('Invalid history-evidence query')
    if not isinstance(query['name'],str) or not query['name'].strip():raise InputError('Query name required')
    if not isinstance(query['target'],dict) or set(query['target'])!={'tools','values'}:raise InputError('Target tools and value pointer required')
    if not isinstance(query['history'],dict) or set(query['history'])!={'tools','bindings','result_bindings'}:raise InputError('History tools and explicit call/result scope bindings required')
    for tools in [query['target']['tools'],query['history']['tools'],query['invalidate_on']]:
        if not isinstance(tools,list) or any(not isinstance(t,str) or not t for t in tools) or len(set(tools))!=len(tools):raise InputError('Invalid tool selector')
    if not query['target']['tools'] or not query['history']['tools']:raise InputError('Explicit tool selectors required')
    if query['quantifier'] not in {'any','all'}:raise InputError('Quantifier must be any or all')
    for pointer in [query['target']['values'],query['rows'],query['key']]:tokens(pointer)
    bindings=query['history']['bindings'];checks=query['checks']
    if not isinstance(bindings,list) or not bindings:raise InputError('At least one exact scope binding is required')
    for binding in bindings:
        if not isinstance(binding,dict) or set(binding)!={'target','history'}:raise InputError('Invalid history scope binding')
        for pointer in binding.values():
            if '*' in tokens(pointer):raise InputError('Scope bindings must be single-valued')
    if not isinstance(query['history']['result_bindings'],list):raise InputError('Explicit result scope bindings required')
    for binding in query['history']['result_bindings']:
        if not isinstance(binding,dict) or set(binding)!={'target','result'}:raise InputError('Invalid returned scope binding')
        for pointer in binding.values():
            if '*' in tokens(pointer):raise InputError('Returned scope bindings must be single-valued')
    if not isinstance(checks,list) or not checks:raise InputError('At least one explicit returned-value check required')
    for check in checks:
        if not isinstance(check,dict) or set(check)!={'pointer','equals'}:raise InputError('Only exact returned-value equality is supported')
        if '*' in tokens(check['pointer']):raise InputError('Row checks must be single-valued')
        digest(check['equals'])
    if '*' in tokens(query['key']):raise InputError('Row identity must be single-valued')
    return query


def one(value,pointer):
    rows,complete=select(value,pointer)
    return rows[0] if complete and len(rows)==1 else None


def eq(a,b):
    return digest(a)==digest(b)  # JSON identity: true is not the number 1.


def combine(values,quantifier):
    if not values:return None
    if quantifier=='any':return True if True in values else None if None in values else False
    return False if False in values else None if None in values else True


def _json(text):
    def object_pairs(pairs):
        obj={}
        for key,value in pairs:
            if key in obj:raise ValueError('Duplicate JSON key')
            obj[key]=value
        return obj
    def invalid(_):raise ValueError('Non-finite JSON value')
    return json.loads(text,object_pairs_hook=object_pairs,parse_constant=invalid)


def fact(event,kind,pointer,value):
    row={'event_id':event['id'],'source_pointer':event['source_pointer'],'event_text_hash':digest(event['text']),
         'kind':kind,'json_pointer':pointer,'value':deepcopy(value)}
    return {'id':'evidence-fact-'+digest(row),**row}


def evaluate(run,query):
    validate(query);events=sorted(run['events'],key=lambda e:e['index']);linked=links(run)
    if len({e['id'] for e in events})!=len(events) or len({e['index'] for e in events})!=len(events):raise InputError('Source event order/identity is ambiguous')
    def visible(e):return not e.get('copied_context') and e.get('agent_visibility')!='not_established' and not e['kind'].startswith('external_')
    def arguments(e):return e.get('arguments') if e.get('arguments_available') is not False and isinstance(e.get('arguments'),dict) else None
    def concurrent(e):return e.get('batch_size',0)>1 or linked['batch_sizes'].get(batch_key(e),0)>1
    def matches(target,prior):
        a,b=arguments(target),arguments(prior)
        if a is None or b is None:return None,[]
        values=[];facts=[]
        for binding in query['history']['bindings']:
            lhs=one(a,binding['target']);rhs=one(b,binding['history'])
            if lhs is None or rhs is None:values.append(None);continue
            values.append(eq(lhs['value'],rhs['value']))
            facts.extend([fact(target,'argument',lhs['pointer'],lhs['value']),fact(prior,'argument',rhs['pointer'],rhs['value'])])
        return combine(values,'all'),facts
    observations=[]
    for target in events:
        if target['kind']!='action' or not visible(target) or target.get('tool') not in query['target']['tools']:continue
        row={'action_id':target['id'],'trajectory_id':target['trajectory_id'],'value':None,'reason':'uninspected',
             'history_action_id':None,'result_event_id':None,'superseded_history_action_ids':[],
             'items':[],'facts':[],'witness_edges':[],'invalidating_action_ids':[], 'action_result_link':None}
        observations.append(row)
        args=arguments(target)
        if args is None:row['reason']='native_arguments_unavailable';continue
        if concurrent(target):row['reason']='target_order_ambiguous';continue
        selected,complete=select(args,query['target']['values'])
        if not complete or not selected:row['reason']='target_values_missing';continue
        history=[]
        for prior in events:
            if prior['index']>=target['index']:break
            if prior['kind']!='action' or recorded_scope(prior)!=recorded_scope(target) or not visible(prior) or prior.get('tool') not in query['history']['tools']:continue
            match,binding_facts=matches(target,prior)
            if match is not False:history.append((prior,match,binding_facts))
        if not history:row['reason']='no_prior_matching_lookup';continue
        prior,match,binding_facts=history[-1];row['history_action_id']=prior['id']
        row['superseded_history_action_ids']=[p['id'] for p,m,_ in history[:-1] if m is True]
        if match is None:row['reason']='latest_lookup_scope_unknown';continue
        if concurrent(prior):row['reason']='history_order_ambiguous';continue
        replies=[e for e in linked['by_action'].get(prior['id'],[]) if e['index']<target['index'] and visible(e)]
        if len(replies)!=1:row['reason']='latest_lookup_result_missing_or_multiple';continue
        reply=replies[0];row['result_event_id']=reply['id']
        row['action_result_link']=deepcopy(next(r for r in linked['records'] if r['action_id']==prior['id'] and r['feedback_id']==reply['id']))
        if reply.get('actor')!='environment' or reply.get('media') or reply.get('subagent_refs'):
            row['reason']='lookup_result_not_plain_environment_data';continue
        for change in events:
            if not reply['index']<change['index']<target['index'] or recorded_scope(change)!=recorded_scope(target):continue
            if change['kind']=='action' and visible(change) and change.get('tool') in query['invalidate_on'] and matches(target,change)[0] is not False:
                row['invalidating_action_ids'].append(change['id'])
        if row['invalidating_action_ids']:row['reason']='lookup_invalidated_before_dispatch';continue
        try:data=_json(reply['text'])
        except (ValueError,TypeError,RecursionError):row['reason']='lookup_result_not_unambiguous_json';continue
        returned_scope=[];scope_facts=[]
        for binding in query['history']['result_bindings']:
            lhs=one(args,binding['target']);rhs=one(data,binding['result'])
            returned_scope.append(None if lhs is None or rhs is None else eq(lhs['value'],rhs['value']))
            if lhs is not None and rhs is not None:
                scope_facts.extend([fact(target,'argument',lhs['pointer'],lhs['value']),fact(reply,'returned_json',rhs['pointer'],rhs['value'])])
        if returned_scope and combine(returned_scope,'all') is not True:
            row['reason']='returned_scope_mismatch_or_missing';continue
        records,all_rows=select(data,query['rows'])
        if not all_rows or not records:row['reason']='lookup_rows_missing';continue
        row['facts'].extend(binding_facts+scope_facts)
        for pair in [binding_facts,scope_facts]:
            for index in range(0,len(pair),2):
                row['witness_edges'].append({'source':pair[index]['id'],'target':pair[index+1]['id'],'type':'same_recorded_scope_value'})
        identities=[(record,one(record['value'],query['key'])) for record in records]
        for selected_value in selected:
            item={'target_pointer':selected_value['pointer'],'target_value':deepcopy(selected_value['value']),
                  'value':None,'reason':'identity_not_found','checks':[]}
            row['items'].append(item)
            candidates=[(r,k) for r,k in identities if k is not None and eq(k['value'],selected_value['value'])]
            if len(candidates)!=1:
                if len(candidates)>1:item['reason']='duplicate_returned_identity'
                continue
            record,key=candidates[0]
            tf=fact(target,'argument',selected_value['pointer'],selected_value['value'])
            rf=fact(reply,'returned_json',record['pointer']+key['pointer'],key['value']);row['facts'].extend([tf,rf])
            row['witness_edges'].append({'source':tf['id'],'target':rf['id'],'type':'same_recorded_json_value'})
            for check in query['checks']:
                observed=one(record['value'],check['pointer']);passed=None if observed is None else eq(observed['value'],check['equals'])
                check_row={'pointer':record['pointer']+check['pointer'],'expected':deepcopy(check['equals']),'value':passed,'fact_id':None}
                if observed is not None:
                    cf=fact(reply,'returned_json',record['pointer']+observed['pointer'],observed['value']);row['facts'].append(cf);check_row['fact_id']=cf['id']
                    row['witness_edges'].append({'source':rf['id'],'target':cf['id'],'type':'attribute_in_same_returned_record'})
                item['checks'].append(check_row)
            item['value']=combine([c['value'] for c in item['checks']],'all');item['reason']='recorded_attribute_comparison' if item['value'] is not None else 'required_attribute_missing'
        row['value']=combine([i['value'] for i in row['items']],query['quantifier']);row['reason']='recorded_value_join' if row['value'] is not None else 'incomplete_recorded_evidence'
        row['facts']=list({f['id']:f for f in row['facts']}.values())
    known=[r for r in observations if r['value'] is not None]
    value={'schema':VERSION,'run_id':run['id'],'source_hash':digest(run),'query':deepcopy(query),'query_hash':digest(query),
           'observations':observations,'metrics':{'opportunities':len(observations),'denominator':len(known),
               'numerator':sum(r['value'] is True for r in known),'unknown':len(observations)-len(known),
               'value':sum(r['value'] is True for r in known)/len(known) if known else None},
           'limits':'Explicit query over native arguments and the latest matching prior lookup. No natural-language interpretation, actual-effect, authorization-validity or task-success claim. Unlisted state mutations may not be captured.'}
    return {'id':'history-evidence-'+digest(value),**value}


def graph(run,result):
    """Persistable property graph containing the complete source and evidence joins."""
    from . import graph_store
    actual=deepcopy(result);actual.pop('graph_id',None)
    if evaluate(run,result['query'])!=actual:raise InputError('History evidence differs from source replay')
    g=graph_store.build(run)
    # Inapplicable rollouts retain the existing source graph. A monitor must not
    # duplicate an entire trace merely to record zero selected opportunities.
    if not result['observations']:return g
    nodes={n['id']:n for n in g['nodes']};edges={e['id']:e for e in g['edges']}
    events={e['id']:e for e in run['events']}
    def node(key,kind,properties,eid=None):
        e=events.get(eid,{})
        value={'id':key,'kind':kind,'activity':None,'trajectory_id':e.get('trajectory_id'),'event_index':e.get('index'),'properties':deepcopy(properties)}
        if key in nodes and nodes[key]!=value:raise InputError('Conflicting evidence graph node')
        nodes[key]=value
    def edge(a,b,kind):
        if a not in nodes or b not in nodes:raise InputError('Unbound evidence graph endpoint')
        value={'source':a,'target':b,'type':kind,'properties':{'basis':'explicit structured-source query','query_hash':result['query_hash'],'version':VERSION}}
        key='edge-'+digest(value);edges[key]={'id':key,**value}
    qid='history-query:'+result['query_hash'];node(qid,'history_evidence_query',result['query'])
    for row in result['observations']:
        oid='history-observation:'+digest([result['id'],row['action_id']]);node(oid,'history_evidence_observation',row,row['action_id'])
        edge(oid,qid,'evaluated_by_query');edge(oid,'event:'+row['action_id'],'observes_dispatch')
        for key,kind in [('history_action_id','uses_latest_matching_lookup'),('result_event_id','uses_recorded_return')]:
            if row[key]:edge(oid,'event:'+row[key],kind)
        for eid in row['superseded_history_action_ids']:edge(oid,'event:'+eid,'supersedes_prior_lookup_for_query')
        for eid in row['invalidating_action_ids']:edge(oid,'event:'+eid,'invalidated_by_recorded_attempt')
        for f in row['facts']:
            node(f['id'],'source_json_fact',f,f['event_id']);edge(f['id'],'event:'+f['event_id'],'sourced_from_event');edge(oid,f['id'],'uses_recorded_fact')
        for witness in row['witness_edges']:edge(witness['source'],witness['target'],witness['type'])
    g.update(observer=VERSION+':'+result['query_hash'],observer_label=result['query']['name'],annotation_hash=digest(actual),
             semantic_context={'schema':VERSION,'notice':result['limits'],'result_id':result['id']},
             nodes=sorted(nodes.values(),key=lambda n:n['id']),edges=sorted(edges.values(),key=lambda e:e['id']),
             counts={'nodes':len(nodes),'edges':len(edges),'unresolved_endpoints':0})
    g.pop('id');return {'id':'graph-'+digest(g),**g}
