"""Retrieve recorded behavior opportunities from a frozen investigation.

No fresh graph selection, inference or remeasurement. A case is an opportunity,
not another rollout; missing relations never become a negative observation.
"""
from collections import Counter, defaultdict
from copy import deepcopy

from . import failure_investigations, graph_store
from .schema import InputError, digest

VERSION = 'investigation-cases/1'
FAMILIES = {
    'recurrence': {'key':'episodes', 'schema':'work-episodes/4', 'legacy_schemas':('work-episodes/3',), 'items':'episodes',
        'label':'Returns and repeated work',
        'statuses':{'continued':'Consecutive same-work recurrence', 'returned':'Return after other work',
                    'interrupted':'Recurrence across an observation gap'}},
    'recovery': {'key':'recovery', 'schema':'recovery-windows/1', 'items':'records',
        'label':'Comparable recovery checks',
        'statuses':{'recovered':'Recorded recovery', 'not_recovered_in_window':'Not recovered in the observed window',
                    'unknown':'Unknown or incomplete follow-up'}},
}


def population(doc):
    if doc['schema'] == 'training-investigation/1':
        return {s['run_id']:'focus' for s in doc['selected_samples'] if s.get('run_id')}
    return {r['id']:'focus' if r.get('focus') else 'reference' for r in doc['snapshot']['rows']
            if r.get('focus') or r.get('reference')}


def material(doc, family, cohort='all'):
    spec=FAMILIES[family]; sources=population(doc)
    if cohort!='all': sources={k:v for k,v in sources.items() if v==cohort}
    wrapper=(doc['snapshot'].get('process') or {}).get(spec['key'])
    coverage={'scope_rollouts':len(sources), 'projected_rollouts':0, 'rollouts_with_cases':0,
              'missing_projection_rollouts':len(sources), 'ambiguous_projection_rollouts':0,
              'recorded_actions':0, 'represented_actions':0, 'first_or_unresolved_actions':0,
              'identity_reviewed_actions':0, 'recorded_checks':0, 'captured_checks':0}
    if not wrapper or wrapper.get('schema') not in (spec['schema'],*spec.get('legacy_schemas',())):
        return [],coverage,'not_recorded',[]
    groups=defaultdict(dict)
    for record in wrapper['records']:
        if record['run_id'] in sources:
            # Repeated identical output does not create another source. Conflicting
            # outputs for a source are withheld; never choose a newer annotation.
            groups[record['run_id']][digest(record)]=record
    cases=[];limits=[]
    for run_id,variants in groups.items():
        if len(variants)!=1:
            coverage['ambiguous_projection_rollouts']+=1;continue
        record=next(iter(variants.values()))
        if record.get('schema')!=wrapper['schema']:continue
        coverage['projected_rollouts']+=1
        if family=='recurrence':
            c=record['counts']
            for target,source in [('recorded_actions','recorded_actions'),('represented_actions','represented_actions'),
                ('first_or_unresolved_actions','first_or_unresolved'),('identity_reviewed_actions','identity_reviewed')]:
                coverage[target]+=c.get(source,0)
        else:
            c=record['coverage']
            coverage['recorded_checks']+=c.get('recorded_checks',0);coverage['captured_checks']+=c.get('captured_checks',0)
        graph=record['graph_id'];items={r['id']:r for r in record[spec['items']]}
        if items:coverage['rollouts_with_cases']+=1
        limits.extend(record.get('limits',[]))
        for item in items.values():
            status=item['category'] if family=='recurrence' else item['status']
            if status not in spec['statuses']:raise InputError('Unsupported saved case category')
            feedback=bool(item['assessment_unit_ids']) if family=='recurrence' else bool(item['feedback_reference_edge_ids'])
            cases.append({'id':item['id'], 'family':family, 'run_id':run_id, 'graph_id':graph,
                'observer':record.get('observer'), 'source_hash':record['source_hash'], 'cohort':sources[run_id],
                'projection_id':record.get('id'), 'projection_schema':record['schema'],
                'target':item['target'] if family=='recurrence' else item['criterion_id'],
                'status':status, 'status_label':spec['statuses'][status], 'recorded_feedback_reference':feedback,
                'location':f"Actions {item['start_position']} → {item['end_position']}" if family=='recurrence' else f"Failed check {item['failure_action_id']} · {len(item['attempts'])} follow-up checks",
                'case':item})
    coverage['missing_projection_rollouts']=len(sources)-coverage['projected_rollouts']
    return cases,coverage,'available',list(dict.fromkeys(limits))


def search(store, identifier, *, family='recurrence', cohort='all', status='all', feedback='all', q='', limit=20, offset=0):
    if not isinstance(family,str) or family not in FAMILIES:raise InputError('Unknown case family')
    if not isinstance(cohort,str) or cohort not in {'all','focus','reference'}:raise InputError('Unknown case cohort')
    if not isinstance(status,str) or status not in {'all',*FAMILIES[family]['statuses']}:raise InputError('Unknown case status')
    if not isinstance(feedback,str) or feedback not in {'all','recorded','unestablished'}:raise InputError('Unknown feedback filter')
    if not isinstance(q,str) or len(q)>240:raise InputError('Search at most 240 characters')
    if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:raise InputError('Invalid case page')
    doc=failure_investigations.read(store,identifier)
    rows,coverage,availability,limits=material(doc,family,cohort)
    facets=dict(Counter(r['status'] for r in rows));query=q.strip().casefold()
    matches=[r for r in rows if (status=='all' or r['status']==status)
             and (feedback=='all' or r['recorded_feedback_reference']==(feedback=='recorded'))
             and (not query or query in r['target'].casefold())]
    return {'schema':VERSION,'investigation_id':identifier,'family':family,'availability':availability,
        'filters':{'cohort':cohort,'status':status,'feedback':feedback,'q':q}, 'coverage':coverage,
        'total_cases':len(rows),'matched_cases':len(matches),'matched_rollouts':len({r['run_id'] for r in matches}),
        'facets':facets,'statuses':FAMILIES[family]['statuses'],'limit':limit,'offset':offset,
        'cases':[{k:deepcopy(v) for k,v in r.items() if k!='case'} for r in matches[offset:offset+limit]],
        'feedback_definition':'Saved assessment of earlier feedback' if family=='recurrence' else 'Saved feedback reference before the recovery cutoff',
        'limits':limits,'inference_calls':0,
        'interpretation':'Recorded cases in the pinned comparison. Several cases can belong to one rollout. An unestablished feedback reference is not evidence of ignored feedback. Cases do not establish exploration, deviation or causal recovery.'}


def resolve(store, reference):
    if set(reference)!={'kind','investigation_id','family','case_id'}:raise InputError('Invalid behavior-case reference')
    for key in ('investigation_id','case_id'):
        if not isinstance(reference[key],str) or not reference[key] or len(reference[key])>120:raise InputError('Invalid case identity')
    family=reference['family']
    if not isinstance(family,str) or family not in FAMILIES:raise InputError('Unknown case family')
    try:doc=failure_investigations.read(store,reference['investigation_id'])
    except KeyError as e:raise InputError('Saved case comparison not found') from e
    rows,coverage,availability,limits=material(doc,family)
    row=next((r for r in rows if r['id']==reference['case_id']),None)
    if row is None:raise InputError('Case is unavailable or outside this saved comparison')
    # Retrieve review context from the exact immutable graph, never its latest version.
    try:graph=graph_store.read(store,row['graph_id'])
    except KeyError:review={'status':'graph_unavailable','notes':[]}
    else:
        if graph['run_id']!=row['run_id'] or graph['source_hash']!=row['source_hash']:
            raise InputError('Case graph does not match the saved source')
        review={'status':'retained','graph_id':graph['id'],
                'notes':deepcopy((graph.get('semantic_context') or {}).get('review_notes',[]))}
    return {'kind':'behavior_case','id':row['id'], 'investigation_id':doc['id'], 'investigation_title':doc['title'],
            'title':row['target'],'family':family,'record':deepcopy(row),'coverage':coverage,'limits':limits,
            'annotation_review':review}
