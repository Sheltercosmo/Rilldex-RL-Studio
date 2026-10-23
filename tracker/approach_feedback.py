"""Join saved executor diagnostics to repeated work; never infer recovery."""
from .execution_reports import VERSION as REPORT_VERSION

VERSION='approach-feedback/2+'+REPORT_VERSION
LABELS={
    'reported_again':'Error reported again',
    'no_reported_error':'Later response inspected: no error reported',
    'followup_unknown':'Earlier error; later report unresolved',
    'no_prior_error':'Earlier response inspected: no error reported',
    'unknown':'Earlier report unresolved',
}
LIMIT='Executor reports can describe handled or component errors. No error reported is not successful execution or verified recovery. The pair is the next recorded same-work recurrence, not necessarily the same acceptance check.'


def resolver(graph):
    saved=(graph.get('semantic_context') or {}).get('execution_reports') or {}
    rows={};supported=saved.get('schema')==REPORT_VERSION and saved.get('source_hash')==graph['source_hash'] and saved.get('run_id')==graph['run_id']
    for row in saved.get('observations',[]) if supported else []:
        rows.setdefault((row['action_event_id'],row['response_event_id']),[]).append(row)
    nodes={n['id']:n for n in graph['nodes']}
    units={};grounded={(e['source'],e['target']) for e in graph['edges'] if e['type']=='grounded_in'}
    for node in graph['nodes']:
        p=node['properties'];ref=p.get('source') or {};source=nodes.get('event:'+str(ref.get('event_id')))
        a,b=ref.get('start'),ref.get('end')
        if (node['kind']=='unit' and p.get('kind')=='feedback' and source and node['trajectory_id']==source['trajectory_id'] and (node['id'],source['id']) in grounded
            and type(a) is int and type(b) is int and 0<=a<b<=len(source['properties'].get('text',''))
            and ref.get('text')==source['properties']['text'][a:b]):
            units.setdefault(source['id'],[]).append((a,b,node['id']))
    def side(uid,context):
        action=nodes[uid]['properties']['source']['event_id'];observations=[];reasons=[]
        if context['status']!='available':reasons.extend(context['reasons'])
        for record in context['records']:
            candidates=rows.get((action,record['event_id']),[])
            row=candidates[0] if len(candidates)==1 else None
            status=(row['error'] if row and (row['error']=='reported' or row.get('complete_readable_response') is True) else 'unresolved')
            if status not in {'reported','not_reported'}:status='unresolved'
            observations.append(dict(event_id=record['event_id'],node_id=record['node_id'],status=status,
                unit_ids=[u[2] for u in sorted(units.get(record['node_id'],[]))],
                request=row.get('request_hash') if row else None,report_version=saved.get('schema') if row else None))
        if not supported:reasons.append('No retained execution-report inspection for this graph')
        if not observations or any(o['status']=='unresolved' for o in observations):reasons.append('One or more response reports are uninspected or unresolved')
        # A positive reports an observed error even if another response is uninspected.
        # Absence requires every bound response to be inspected in full.
        status=('unresolved' if context['status']!='available' else 'reported' if any(o['status']=='reported' for o in observations)
                else 'not_reported' if observations and all(o['status']=='not_reported' for o in observations) else 'unresolved')
        return dict(status=status,observations=observations,reasons=reasons)
    def resolve(episode,context):
        before=side(episode['previous_unit_id'],context['previous']);after=side(episode['current_unit_id'],context['current'])
        category=('unknown' if before['status']=='unresolved' else 'no_prior_error' if before['status']=='not_reported'
                  else {'reported':'reported_again','not_reported':'no_reported_error','unresolved':'followup_unknown'}[after['status']])
        return dict(schema=VERSION,category=category,label=LABELS[category],previous=before,current=after,limit=LIMIT)
    return resolve
