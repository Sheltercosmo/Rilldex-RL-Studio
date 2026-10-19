"""Declared Plan structure and observed stage work in one source-bound projection."""
from collections import Counter
from copy import deepcopy
from .schema import InputError,digest
from .capabilities import links, batch_key
from .execution_reports import bound_responses
from .plan_stage_material import dependencies as material_dependencies, VERSION as MATERIAL_VERSION

VERSION='plan-execution-projection/1'
ROLES={'prepares_plan_step':'prepares','attempts_plan_step':'attempts','checks_plan_step':'checks'}
LIMITS=('Declared stage order and observed dispatch order are distinct. Stage membership comes from saved '
        'correspondence selections. Unassigned actions are not deviations. Output material is not verified '
        'completion. Stage re-entry is a recorded correspondence, not proof of a mental return to a Plan.')


def build(run,document):
    if document['source_hash']!=digest(run):raise InputError('Plan projection source differs')
    units={u['id']:u for u in document['units']};events={e['id']:e for e in run['events']}
    reports={r['response_event_id']:i for i,r in enumerate(document.get('execution_reports',{}).get('observations',[]))}
    material=document.get('plan_stage_material')
    if material and (material.get('schema')!=MATERIAL_VERSION or material.get('source_hash')!=digest(run) or
                     material.get('dependencies_hash')!=digest(material_dependencies(document))):
        raise InputError('Plan material dependencies differ')
    materials=(material or {}).get('observations',[])
    responses={}
    for action,response in bound_responses(run):responses.setdefault(action['id'],[]).append(response)
    response_units={u['source']['event_id']:u['id'] for u in units.values() if u['kind']=='feedback'}
    action_units={}
    for u in units.values():
        if u['kind']=='action':action_units.setdefault(u['source']['event_id'],[]).append(u['id'])
    batch_sizes=links(run)['batch_sizes']
    def ordered(ids):return sorted(set(ids),key=lambda uid:(events[units[uid]['source']['event_id']]['index'],units[uid]['source']['start']))
    result={'schema':VERSION,'source_hash':digest(run),'plans':[],'limits':LIMITS}
    for plan in (u for u in units.values() if u.get('plan_structure')):
        structure=plan['plan_structure'];pe=events[plan['source']['event_id']]
        steps={s['id']:s for s in structure['steps']};bindings={};stage_rows=[]
        for index,relation in enumerate(document['relations']):
            if relation['type'] not in ROLES or relation['to']!=plan['id']:continue
            action=units.get(relation['from']);sid=relation.get('plan_step_id')
            if not action or action['kind']!='action' or sid not in steps:raise InputError('Invalid Plan stage binding')
            ae=events[action['source']['event_id']]
            if (action['actor'],action['trajectory_id'])!=(plan['actor'],plan['trajectory_id']) or (pe['index'],plan['source']['end'])>(ae['index'],action['source']['start']):
                raise InputError('Plan correspondence crosses participant or source cutoff')
            binding={'unit_id':action['id'],'stage_id':sid,'role':ROLES[relation['type']],'relation_index':index}
            bindings.setdefault(ae['id'],[]).append(binding)
        for stage in structure['steps']:
            selected=[b for bs in bindings.values() for b in bs if b['stage_id']==stage['id']]
            action_ids=ordered(b['unit_id'] for b in selected)
            feedback_ids=[];evidence_events=[]
            for aid in action_ids:
                event_id=units[aid]['source']['event_id']
                roles=sorted({b['role'] for b in selected if b['unit_id']==aid})
                for feedback in responses.get(event_id,[]):
                    fid=response_units.get(feedback['id'])
                    if fid:feedback_ids.append(fid)
                    entries=[i for i,r in enumerate(materials) if (r['plan_unit_id'],r['stage_id'],r['action_unit_id'],r['response_event_id'])==(plan['id'],stage['id'],aid,feedback['id'])]
                    if len(entries)>1:raise InputError('Duplicate stage material observation')
                    evidence_events.append({'action_unit_id':aid,'response_unit_id':fid,'response_event_id':feedback['id'],
                        'roles':roles,'material_index':entries[0] if entries else None,
                        'executor_report_index':reports.get(feedback['id'])})
            related=set([plan['id'],*action_ids,*feedback_ids])
            for r in document['relations']:
                if r['type']=='recorded_with' and r['to'] in action_ids:related.add(r['from'])
                if r['type']=='assesses' and r['to'] in feedback_ids:related.add(r['from'])
            stage_rows.append({'id':'plan-stage-'+digest([plan['id'],stage['id']])[:20],
                'stage_id':stage['id'],'text':stage['text'],'target':stage['target'],'evidence':deepcopy(stage['evidence']),
                'action_unit_ids':action_ids,'focus_unit_ids':ordered(related),'bindings':selected,'response_evidence':evidence_events,
                'role_counts':{role:len({b['unit_id'] for b in selected if b['role']==role}) for role in ROLES.values()},
                'material_counts':dict(Counter(materials[e['material_index']]['form'] if e['material_index'] is not None else 'uninspected' for e in evidence_events if set(e['roles'])&{'attempts','checks'})),
                'completion':'not_established'})
        timeline=[];transitions=[];phase_runs=[]
        if bindings:
            first=min(events[eid]['index'] for eid in bindings);last=max(events[eid]['index'] for eid in bindings)
            scope=[e for e in run['events'] if e['kind']=='action' and not e.get('copied_context') and
                   (e['actor'],e['trajectory_id'])==(plan['actor'],plan['trajectory_id']) and first<=e['index']<=last]
            previous=None;seen_stages=set();gap=[]
            for position,action in enumerate(sorted(scope,key=lambda e:e['index'])):
                bs=bindings.get(action['id'],[]);sids=sorted({b['stage_id'] for b in bs})
                parallel=batch_sizes.get(batch_key(action),0)>1 or action.get('batch_size',0)>1
                row={'position':position+1,'action_event_id':action['id'],'action_unit_ids':action_units.get(action['id'],[]),
                     'stage_ids':sids,'bindings':deepcopy(bs),'order_ambiguous':parallel,
                     'status':'assigned' if len(sids)==1 else 'multiple_stages' if sids else 'unassigned'}
                timeline.append(row)
                signature=(tuple(sids),tuple(sorted({b['role'] for b in bs})),row['status'])
                if not phase_runs or signature!=phase_runs[-1]['_signature']:
                    phase_runs.append({'_signature':signature,'stage_ids':sids,'roles':list(signature[1]),'status':row['status'],
                        'positions':[],'action_unit_ids':[],'action_event_ids':[]})
                phase_runs[-1]['positions'].append(position+1);phase_runs[-1]['action_unit_ids'].extend(row['action_unit_ids']);phase_runs[-1]['action_event_ids'].append(action['id'])
                if len(sids)!=1:
                    gap.append(row)
                    if len(sids)>1:previous=None
                    continue
                current=sids[0]
                if previous and previous['stage_ids']!=sids:
                    prior=previous['stage_ids'][0]
                    before=[i for i,m in enumerate(materials) if m['plan_unit_id']==plan['id'] and m['stage_id']==prior and
                            events[m['response_event_id']]['index']<action['index']]
                    transitions.append({'from_stage_id':prior,'to_stage_id':current,
                        'from_action_event_id':previous['action_event_id'],'to_action_event_id':action['id'],
                        'from_unit_ids':previous['action_unit_ids'],'to_unit_ids':row['action_unit_ids'],
                        'gap_action_event_ids':[g['action_event_id'] for g in gap],
                        'order_status':'not_established' if parallel or previous['order_ambiguous'] or any(g['order_ambiguous'] for g in gap) else 'source_order',
                        'reentry':current in seen_stages,'prior_stage_material_before_entry':before,
                        'cutoff':{'event_id':action['id'],'end':len(action['text'])}})
                previous=row;seen_stages.add(current);gap=[]
        for phase in phase_runs:phase.pop('_signature')
        if document.get('work_results'):
            # Scope judgments are response-time evidence. Never fill an earlier
            # transition with a later outcome or make fulfillment persistent.
            work_rows=[r for r in document['work_results']['observations'] if r['scope_kind']=='plan_stage' and r['scope_unit_id']==plan['id']]
            for stage in stage_rows:
                stage['work_result_history']=[deepcopy(r) for r in work_rows if r['plan_step_id']==stage['stage_id']]
            for transition in transitions:
                at=events[transition['to_action_event_id']]['index']
                prior=[r for r in work_rows if r['plan_step_id']==transition['from_stage_id'] and events[r['response_event_id']]['index']<at]
                transition['prior_stage_result_at_entry']=deepcopy(max(prior,key=lambda r:events[r['response_event_id']]['index'])) if prior else None
        result['plans'].append({'plan_unit_id':plan['id'],'text':plan['content']['summary']['text'],
            'source':deepcopy(plan['source']),'stages':stage_rows,'declared_links':deepcopy(structure['links']),
            'completion_criterion':deepcopy(structure['completion_criterion']),
            'dispatch_timeline':timeline,'phases':phase_runs,'stage_transitions':transitions,
            'counts':{'bound_actions':len(bindings),'unassigned_actions':sum(r['status']=='unassigned' for r in timeline),
                      'multiple_stage_actions':sum(r['status']=='multiple_stages' for r in timeline),
                      'stage_changes':sum(t['order_status']=='source_order' for t in transitions),
                      'stage_reentries':sum(t['order_status']=='source_order' and t['reentry'] for t in transitions)}})
    result['counts']={'plans':len(result['plans']),'stages':sum(len(p['stages']) for p in result['plans'])}
    return result


def project(bundle,run):
    if not bundle.get('available'):return bundle
    result=deepcopy(bundle);result['document']['plan_execution']=build(run,bundle['document'])
    if result.get('observer'):
        from .semantic_catalog import export_payload
        result['export_digest']=digest(export_payload(result))
    return result
