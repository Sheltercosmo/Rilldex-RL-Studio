"""Persistent requested-work histories over saved versions and action links.

This adds no classifier: record identity, changes and correspondence come from
audited dependencies. A shared enclosing scope never spreads an action across
all its work items. Version changes are not completion or goal-change events.
"""
from copy import deepcopy
from .schema import InputError,digest
from .semantic_extraction import checked_span
from .work_correspondence import source_order

VERSION='requested-work-lineage/1'
TYPES={'prepares_requested_work','attempts_requested_work','checks_requested_work'}


def build(run,document):
    work=document.get('requested_work')
    result={'schema':VERSION,'available':bool(work and work.get('status')=='complete'),
            'records':[],'scope_updates':[],
            'limits':'History of selected requested terms and dispatch correspondence, not unfinished work, active intention, completion, strategy, or independent accuracy.'}
    if not result['available']:
        result['reason']='Selected requested-work versions are unavailable; organized Plans and source context remain separate.'
        return result
    units={u['id']:u for u in document['units']}
    if len(units)!=len(document['units']):raise InputError('Lineage requires unique source units')
    def order(uid):return source_order(run,units[uid]['source'])
    def key(record):return record['trajectory_id'],record['actor'],record['id']
    context=document.get('work_context',{})
    frames={f['id']:f for f in context.get('frames',[])}
    selected_frames={fid for row in context.get('observations',[]) if row['status']=='selected' for fid in row['frame_ids']}
    changes=sorted(enumerate(work['changes']),key=lambda item:(order(item[1]['source_unit_id']),item[0]))
    records={};versions={}
    for _,change in changes:
        uid=change['source_unit_id'];unit=units[uid];after=change['after'];before=change['before'];rk=key(after)
        if (after['source_unit_id']!=uid or after['actor']!=unit['actor'] or after['trajectory_id']!=unit['trajectory_id']):
            raise InputError('Lineage update attribution differs from source')
        for ref in after['evidence']:checked_span(run,ref,unit['source'])
        lineage=records.get(rk)
        if lineage is None:
            if before is not None or change['operation']!='introduce':raise InputError('Lineage must begin with introduction')
            lineage={'id':'lineage-'+digest(rk)[:20],'record_id':after['id'],'actor':after['actor'],
                'trajectory_id':after['trajectory_id'],'kind':after['kind'],'versions':[],
                'dispatch_correspondences':[]}
            records[rk]=lineage
        elif not before or lineage['versions'][-1]['record']!=before:
            raise InputError('Lineage before-version differs from the preceding selected record')
        if after['version_id'] in versions:raise InputError('Duplicate lineage version')
        frame_ids=[fid for fid,f in frames.items() if uid in f['unit_ids'] and
                   f['source']['event_id']==unit['source']['event_id'] and
                   f['source']['start']<=unit['source']['start'] and unit['source']['end']<=f['source']['end']]
        value={'version_id':after['version_id'],'previous_version_id':before['version_id'] if before else None,
               'operation':change['operation'],'source_unit_id':uid,'source':deepcopy(unit['source']),
               'record':deepcopy(after),'context_frame_ids':frame_ids,
               'selected_as_context':any(fid in selected_frames for fid in frame_ids),
               'retired_clauses':deepcopy(change.get('retired_clauses',[]))}
        lineage['versions'].append(value);versions[after['version_id']]=(lineage,value)
    if {key(r):r for r in work['records']}!={k:v['versions'][-1]['record'] for k,v in records.items()}:
        raise InputError('Lineage final versions differ from selected requested state')
    identities=set()
    for relation in document['relations']:
        if relation['type'] not in TYPES:continue
        vid=relation.get('requested_work_version_id')
        if vid not in versions:raise InputError('Action correspondence has no selected work version')
        lineage,version=versions[vid];action=units.get(relation['from']);record=version['record']
        if (not action or action['kind']!='action' or action['trajectory_id']!=record['trajectory_id']
                or relation.get('requested_work_id')!=record['id'] or relation['to']!=version['source_unit_id']):
            raise InputError('Lineage correspondence has a wrong source, record or trajectory')
        origin=order(version['source_unit_id']);dispatch=order(action['id'])
        if not (origin[0]<dispatch[0] or origin[0]==dispatch[0] and origin[2]<=dispatch[1]):
            raise InputError('Future requested version in action correspondence')
        prior=[v for v in lineage['versions'] if order(v['source_unit_id'])[0]<dispatch[0] or
               order(v['source_unit_id'])[0]==dispatch[0] and order(v['source_unit_id'])[2]<=dispatch[1]]
        if prior[-1]['version_id']!=vid:raise InputError('Action correspondence is bound to superseded requested terms')
        identity=(action['id'],vid,relation['type'])
        if identity in identities:continue
        identities.add(identity)
        reviews=[]
        for note in document.get('review_notes',[]):
            reference=note.get('relation_ref')
            if reference and all(relation.get(k)==v for k,v in reference.items()):reviews.append(deepcopy(note))
        lineage['dispatch_correspondences'].append({'action_unit_id':action['id'],
            'version_id':vid,'relation':deepcopy(relation),'reviews':reviews})
    for lineage in records.values():
        last=lineage['versions'][-1];record=last['record'];end=source_order(run,last['source'])
        later=[e['id'] for e in run['events'] if e['trajectory_id']==record['trajectory_id'] and
               e['actor']=='agent' and e['kind']=='action' and
               (e['index']>end[0] or e['index']==end[0] and len(e.get('text',''))>end[2])]
        lineage.update(text=record['text'],latest_status=record['status'],
            later_recorded_dispatch_event_ids=later,
            counts={'versions':len(lineage['versions']),
                    'linked_dispatches':len({c['action_unit_id'] for c in lineage['dispatch_correspondences']}),
                    **{label:len({c['action_unit_id'] for c in lineage['dispatch_correspondences'] if c['relation']['type']==role})
                       for label,role in [('preparation_dispatches','prepares_requested_work'),('attempt_dispatches','attempts_requested_work'),('checking_dispatches','checks_requested_work')]},
                    'reviewed_correspondences':sum(bool(c['reviews']) for c in lineage['dispatch_correspondences'])})
        lineage['dispatch_correspondences'].sort(key=lambda row:order(row['action_unit_id']))
    for fid,frame in frames.items():
        edits=[{'lineage_id':r['id'],'record_id':r['record_id'],'kind':r['kind'],
                'version_id':v['version_id'],'operation':v['operation'],'source_unit_id':v['source_unit_id'],
                'previous_version_id':v['previous_version_id']}
               for r in records.values() for v in r['versions'] if fid in v['context_frame_ids']]
        result['scope_updates'].append({'frame_id':fid,'changes':edits})
    result['records']=list(records.values())
    result['dependencies']={'source_hash':digest(run),'requested_work_hash':digest(work),
        'work_context_hash':digest(context),
        'correspondence_hash':digest([r for r in document['relations'] if r['type'] in TYPES])}
    result['counts']={'work_records':sum(r['kind']=='work' for r in records.values()),
        'condition_records':sum(r['kind']=='condition' for r in records.values()),
        'version_changes':len(changes),
        'unique_linked_dispatches':len({c['action_unit_id'] for r in records.values() for c in r['dispatch_correspondences']})}
    return result
