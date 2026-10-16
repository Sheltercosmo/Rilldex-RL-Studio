"""Recorded requested state at dispatch; availability is not applicability.

Reuses saved correspondence judgments. This deterministic projection neither
selects a purpose nor adjudicates conditions, authorization or goal deviation.
"""
from copy import deepcopy
from .schema import InputError, digest
from .semantic_extraction import checked_span
from .work_correspondence import VERSION as CORRESPONDENCE_VERSION, ROLES, EXPLANATIONS, references

VERSION = 'request-dispatch-context/1'
LIMIT = ('Requested records available in the saved source prefix. Work-role judgments are inherited '
         'observations, not condition satisfaction, active intention, authorization, deviation or success. '
         'A missing or none correspondence does not establish unrelated work.')


def build(run, document):
    from .request_changes import changes
    changes(run, document)
    work=document['requested_work'];units={u['id']:u for u in document['units']}
    events={e['id']:e for e in run['events']}
    def position(u):
        event=checked_span(run,u['source'])
        if event['actor']!=u['actor'] or event['trajectory_id']!=u['trajectory_id'] or event.get('copied_context'):
            raise InputError('Dispatch context source attribution differs')
        return event['index'],u['source']['start'],u['source']['end']
    actions=sorted((u for u in units.values() if u['kind']=='action'),key=position)
    seen=set()
    for action in actions:
        event=events[action['source']['event_id']]
        if action['actor']!='agent' or event['kind']!='action' or event['id'] in seen:
            raise InputError('Dispatch context needs one agent action unit per source dispatch')
        seen.add(event['id'])
    cor=document.get('work_correspondence');saved={}
    if cor:
        if (cor['schema']!=CORRESPONDENCE_VERSION or cor['source_hash']!=digest(run) or cor['run_id']!=run['id']
                or cor['requested_work_hash']!=digest(work) or cor['extraction_hash']!=work.get('extraction_hash')):
            raise InputError('Correspondence dependencies differ from requested state')
        saved={r['action_unit_id']:r for r in cor['actions']}
        if len(saved)!=len(cor['actions']) or set(saved)!={a['id'] for a in actions}:
            raise InputError('Correspondence action coverage differs')
        exported=[r for r in document.get('relations',[]) if r['type'] in {k+'_requested_work' for k in EXPLANATIONS}]
        if sorted(map(digest,exported))!=sorted(map(digest,cor['relations'])):
            raise InputError('Exported work links differ from correspondence observations')
    result=[];used=[]
    for action in actions:
        cutoff=position(action)
        prior=[(position(units[s['unit_id']]),s) for s in work['steps']
               if units[s['unit_id']]['trajectory_id']==action['trajectory_id']
               and (position(units[s['unit_id']])[0],position(units[s['unit_id']])[2])<=cutoff[:2]]
        step=max(prior,key=lambda p:p[0])[1] if prior else None
        state=deepcopy(step['state_after'] if step else []);state_hash=digest(state)
        for ref in references(state):checked_span(run,ref,action['source'])
        row=saved.get(action['id']);pool={r['version_id']:r for r in state if r['kind']=='work'}
        if row:
            if (row['source_state_unit_id']!=(step['unit_id'] if step else None) or row['state_at_dispatch']!=state
                    or row['requested_state_hash']!=state_hash or row['candidate_count']!=len(pool)):
                raise InputError('Correspondence uses a different or later requested snapshot')
            if (set(row['choices'])!=set(pool) or any(v not in ROLES for v in row['choices'].values())
                    or row['status']!=('inspected' if pool else 'no_prior_selected_requested_work')):
                raise InputError('Incomplete or invalid correspondence choices')
            if pool and (not row['requests'] or any(not isinstance(k,str) or not k for k in row['requests'])
                         or len(set(row['requests']))!=len(row['requests'])):
                raise InputError('Inspected correspondence needs distinct decision references')
        links=[]
        for record in state:
            choice=row['choices'].get(record['version_id']) if row else None
            if choice not in EXPLANATIONS:continue
            matches=[r for r in cor['relations'] if r['from']==action['id'] and r['requested_work_version_id']==record['version_id']]
            if len(matches)!=1:raise InputError('Positive correspondence needs exactly one saved version link')
            rel=matches[0]
            expected={'to':record['source_unit_id'],'type':choice+'_requested_work','harness':CORRESPONDENCE_VERSION,'basis':'jev_raw_argmax',
                      'requested_work_id':record['id'],'requested_work_text':record['text'],
                      'requested_status_at_dispatch':record['status'],'requested_state_hash':state_hash,
                      'cutoff':{'event_id':action['source']['event_id'],'end':action['source']['end']}}
            if any(rel.get(k)!=v for k,v in expected.items()) or rel.get('request_hash') not in row['requests']:
                raise InputError('Work correspondence version, role or cutoff differs')
            for ref in rel['evidence']:checked_span(run,ref,action['source'])
            links.append(deepcopy(rel));used.append(digest(rel))
        result.append({'action_unit_id':action['id'],'event_id':action['source']['event_id'],
                       'trajectory_id':action['trajectory_id'],'cutoff':deepcopy(action['source']),
                       'source_state_unit_id':step['unit_id'] if step else None,'requested_state_hash':state_hash,
                       'records':state,'correspondence_status':row['status'] if row else 'uninspected',
                       'choices':deepcopy(row['choices']) if row else {},'requests':deepcopy(row['requests']) if row else [],
                       'links':links})
    if cor and sorted(used)!=sorted(map(digest,cor['relations'])):
        raise InputError('Correspondence contains an extra, negative or unbound relation')
    recorded=[e['id'] for e in run['events'] if e['actor']=='agent' and e['kind']=='action' and not e.get('copied_context')]
    return {'schema':VERSION,'source_hash':digest(run),'requested_work_hash':digest(work),
            'correspondence_hash':digest(cor) if cor else None,'actions':result,
            'unrepresented_action_event_ids':[eid for eid in recorded if eid not in seen],
            'counts':{'recorded_actions':len(recorded),'represented_actions':len(result),
                      'actions_with_reviewed_correspondence':sum(a['correspondence_status']=='inspected' for a in result),
                      'positive_work_links':len(used)},'limits':LIMIT}


def materialize(run, document, graph):
    """Extend a graph which already contains all requested version objects."""
    result=build(run,document);nodes={n['id']:n for n in graph['nodes']};edges={e['id']:e for e in graph['edges']}
    def edge(source,target,kind,properties):
        if source not in nodes or target not in nodes:raise InputError('Missing request context endpoint')
        value={'source':source,'target':target,'type':kind,'properties':properties};key='edge-'+digest(value)
        edges[key]={'id':key,**value}
    for row in result['actions']:
        state_id='requested-state:'+digest([row['trajectory_id'],row['source_state_unit_id'],row['requested_state_hash']])
        owner=nodes.get(row['source_state_unit_id'])
        nodes[state_id]={'id':state_id,'kind':'requested_state','activity':None,'trajectory_id':row['trajectory_id'],
                         'event_index':owner['event_index'] if owner else None,
                         'properties':{'state_hash':row['requested_state_hash'],'source_unit_id':row['source_state_unit_id'],
                                       'version_ids':[r['version_id'] for r in row['records']]}}
        edge(row['action_unit_id'],state_id,'request_context_at_dispatch',
             {k:deepcopy(row[k]) for k in ['cutoff','correspondence_status','choices','requests']})
        for record in row['records']:
            edge(state_id,'requested-version:'+record['version_id'],'contains_requested_version',{'basis':'saved prior request state'})
        for rel in row['links']:
            edge(row['action_unit_id'],'requested-version:'+rel['requested_work_version_id'],'corresponds_to_requested_version',
                 {'role':rel['type'].removesuffix('_requested_work'),'recorded_relation':rel,'basis':'existing correspondence observation'})
    graph['nodes']=list(nodes.values());graph['edges']=list(edges.values())
    graph['semantic_context']['request_dispatch']={k:v for k,v in result.items() if k!='actions'}
    return result
