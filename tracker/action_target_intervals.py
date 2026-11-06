"""Read work correspondence from local units and exact source intervals.

This reader runs before target histories exist. Native response/parent links
provide context; no selected target, Plan or method relation is an input.
"""
from copy import deepcopy

from .capabilities import recorded_scope
from .environment_contracts import excerpt_contracts, reading_context, READING_RULE
from .feedback_assessments import linked_feedback, SOURCE_LINKAGE
from .schema import InputError, digest
from .semantic_extraction import checked_span, source_expression_links
from .semantic_map import evidence
from .semantic_pages import bounded_requests

VERSION='action-target-correspondence/7'
EVIDENCE_LAYOUT='endpoint-interval-and-native-contracts/1'
CONTRACT_CHARS=8000


def local_document(run,extraction):
    """Project complete local selections without reading any derived histories."""
    if extraction['status']!='complete_local_extraction' or extraction['source_hash']!=digest(run):
        raise InputError('Complete local selection for this source is required')
    units=[];relations=[]
    for selected in extraction['units']:
        if selected['status']!='selected':raise InputError('Incomplete selected unit')
        checked_span(run,selected['source'])
        values={k:{'text':v['text'],'evidence':deepcopy(v['evidence'])} if v['status']=='expressed'
                else {'text':'Not expressed','evidence':[]} for k,v in selected['content'].items()}
        work=values.pop('work_target',None)
        if 'target' in values:
            values['requested_target' if selected['activity']=='coordinate' else 'local_target']=values.pop('target')
        values['target']=work or {'text':'No task target expressed' if selected['activity']=='social' else 'Not yet selected','evidence':[]}
        units.append({k:deepcopy(selected[k]) for k in ('id','kind','activity','actor','trajectory_id','source')})
        units[-1]['content']=values
    by_id={u['id']:u for u in units}
    if len(by_id)!=len(units):raise InputError('Duplicate local unit identity')
    for item in linked_feedback(run,extraction,SOURCE_LINKAGE):
        action=by_id[item['action']['id']];event=item['event'];ref=evidence(run,event['id'])
        units.append(dict(id=item['unit_id'],kind='feedback',activity=None,actor=event['actor'],
            trajectory_id=event['trajectory_id'],source=ref,content=dict(
                summary=dict(text='Recorded environment response to this dispatch.',evidence=[ref]),
                target=deepcopy(action['content']['target']),recorded_response=dict(text=event['text'],evidence=[ref]))))
        relations.append(dict(type='feedback_for',**{'from':item['unit_id'],'to':action['id']}))
    relations.extend(source_expression_links(run,extraction['units']))
    return dict(schema='pre-target-local-evidence/1',run_id=run['id'],source_hash=digest(run),units=units,relations=relations)


def request(run,document,action,prior):
    from . import action_targets as targets, method_comparison
    from .work_correspondence import references
    events={e['id']:e for e in run['events']}
    current=checked_span(run,action['source']);before=checked_span(run,prior['source'])
    scope=recorded_scope(current)
    if recorded_scope(before)!=scope:raise InputError('Target endpoints belong to different recorded contexts')
    # Interleaved sessions may reuse a trajectory identifier. Only this recorded
    # context supplies local units and their native associations.
    local=deepcopy(document)
    local['units']=[u for u in local['units'] if recorded_scope(events[u['source']['event_id']])==scope]
    ids={u['id'] for u in local['units']}
    local['relations']=[r for r in local['relations'] if r['from'] in ids and r['to'] in ids]
    for unit in local['units']:
        for ref in references(unit['content']):
            if recorded_scope(events[ref['event_id']])!=scope:
                raise InputError('Selected local content cites another recorded context')
    # The shared reader validates every interval span as it builds the packet.
    # Filter interleaved contexts before that validation, retaining original
    # event IDs, indices, offsets and text. Provenance still names the full run.
    local_hash=digest(local)
    reader_run={**run,'events':[e for e in run['events'] if recorded_scope(e)==scope]}
    local['source_hash']=digest(reader_run)
    from .recurrence_context import source_reader
    reader_run,local,excluded=source_reader(reader_run,local,action['id'])
    if not any(u['id']==prior['unit_id'] for u in local['units']):
        raise InputError('Prior dispatch is outside the visible recorded context')
    req=method_comparison.pair_request(reader_run,local,prior['unit_id'],action['id'],version=method_comparison.NATIVE_VERSION)
    state=req['state']
    state.update(source_hash=digest(run),base_map_hash=local_hash)
    state['source_ranges']=[r for r in state['source_ranges'] if recorded_scope(events[r['event_id']])==scope]
    state['local_extraction_gaps']=[r for r in state['local_extraction_gaps'] if recorded_scope(events[r['event_id']])==scope]
    state['unobserved_media']=[r for r in state['unobserved_media'] if recorded_scope(events[r['event_id']])==scope]
    state['omitted_source_events']=[r for r in state['omitted_source_events'] if recorded_scope(events[r['event_id']])==scope]
    state['omitted_source_events'].extend(excluded)
    for ref in state['source_ranges']:checked_span(run,ref,action['source'])
    state.update(harness=VERSION,stage='action_targets',comparison_rule=state['rule'])
    req['questions']={prior['id']:dict(type='choice',instructions=
        f"Classify CURRENT versus prior {prior['id']} (unit {prior['unit_id']}, event {prior['source']['event_id']}). Follow comparison_rule; select this pair independently.",
        criteria=deepcopy(targets.SCOPE_PAIR_TYPES))}
    endpoint_contracts=[];truncated=[]
    for native in state['native_dispatches']:
        event=events[native['event_id']]
        definitions=excerpt_contracts(event,limit=CONTRACT_CHARS,truncated=truncated)
        if definitions:endpoint_contracts.append(dict(event_id=event['id'],definitions=definitions))
    if endpoint_contracts:state['recorded_endpoint_contracts']=endpoint_contracts
    reference_context=reading_context(run,current)
    if reference_context:state.update(reference_context)
    for kind,context in reference_context.items():
        if kind=='tool_catalog':
            # The session may declare many tools unrelated to this pair. Its
            # catalog is supplementary; captured endpoint definitions above
            # determine required declaration completeness.
            if context.get('truncated_definition_ids'):
                state['missingness']['optional_truncated_definition_ids']=deepcopy(context['truncated_definition_ids'])
            if context.get('omitted_definition_count'):
                state['missingness']['optional_omitted_definition_count']=context['omitted_definition_count']
        else:truncated.extend(context.get('truncated_definition_ids',[]))
    if endpoint_contracts or reference_context:state['interpretation_rule']=READING_RULE
    state['missingness']['required_truncated_event_ids']=list(dict.fromkeys(truncated))
    return req


def pages(run,document,action,pool,*,max_bytes):
    for chunk,req in bounded_requests(pool,lambda chunk:request(run,document,action,chunk[0]),count=1,max_bytes=max_bytes):
        # An incomplete required declaration is an evidence gap, not a negative
        # relationship or permission to decide from a truncated schema.
        if req is not None and req['state']['missingness']['required_truncated_event_ids']:req=None
        yield chunk,req
