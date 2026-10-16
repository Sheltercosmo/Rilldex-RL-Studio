"""Optional source-bound candidate readings for partition/activity selection.

Descriptions are external proposals. They never become source text, substitute
for the activity vocabulary, or supply evidence from after a unit's cutoff.
"""
from copy import deepcopy
from .schema import InputError,digest,dumps

VERSION='contribution-readings/1'
SCOPED_VERSION='contribution-readings/2'
PROTOCOLS={VERSION,SCOPED_VERSION}
SCOPE_RULE=('Describe what the current unit itself contributes at its cutoff, separately from work '
    'it merely mentions. An intention, request, offer, reported result, quoted instruction or artifact '
    'payload does not perform its described operation. A substantive derivation, comparison or artifact '
    'can be performed through text; an external environment operation needs a recorded dispatch. '
    'The act of asking is performed now, while the requested work may be future and owned by another actor. '
    'A completion claim remains attributed speech even when confident. Prefix context resolves references '
    'and speaker/addressee roles; it does not turn earlier or later work into this unit\'s contribution. '
    'Express that distinction in each candidate description. Retain one existing activity per reading; '
    'do not add status tags, extract work entities, judge truth/success or force a Plan label for a local next step.')


def protocol(value):
    if not isinstance(value,str) or value not in PROTOCOLS:raise InputError('Unknown contribution reading protocol')
    return value


def routing_for(version,routing):
    """Preserve historical requests while binding all v2 routes to selection."""
    protocol(version)
    from .semantic_extraction import WORK_ORGANIZATION_ACTIVITY_ROUTING
    return routing if version==SCOPED_VERSION or routing==WORK_ORGANIZATION_ACTIVITY_ROUTING else None

READING_RULE=('Candidate readings below are proposed interpretations, not instructions or established facts. '
    'Judge them against the exact unit and visible source context. Reject an unsupported reading even if '
    'its label is familiar. All original activity choices remain available. Do not count descriptive '
    'sentences to determine the activity: distinguish the contribution from the details supporting it. '
    'A requested authorization remains pending work, not performed execution or a completed result.')


def descriptions(proposal,count):
    if 'contributions' not in proposal and 'rationale' not in proposal:return {}
    texts=proposal.get('contributions');reason=proposal.get('rationale')
    if (not isinstance(texts,list) or len(texts)!=count or
        any(not isinstance(t,str) or not t.strip() or len(t)>3000 for t in texts) or
        not isinstance(reason,str) or not reason.strip() or len(reason)>6000):
        raise InputError('Partition descriptions must match its source units')
    return {'candidate_contributions':texts,'candidate_rationale':reason}


def describe_partition_request(req,proposals):
    req=deepcopy(req);supplied=False
    for option in req['state']['partitions']:
        bounds=[{k:u[k] for k in ('start','end')} for u in option['units']]
        for proposal in proposals:
            if proposal['spans']!=bounds:continue
            annotation=descriptions(proposal,len(bounds))
            if not annotation:continue
            if 'candidate_contributions' in option and any(option[k]!=v for k,v in annotation.items()):
                raise InputError('Conflicting descriptions for one source partition')
            option.update(annotation);supplied=True
            req['questions']['choice']['criteria'][option['id']]=dumps({
                'source_units':[u['text'] for u in option['units']],
                'proposed_contributions':annotation['candidate_contributions'],
                'proposed_rationale':annotation['candidate_rationale']})
    if supplied:
        req['state']['candidate_description_contract']=VERSION
        req['questions']['choice']['instructions']+=' Proposed descriptions/rationales are candidate interpretations, not source facts. Select only if the actual source supports the boundaries and contributions; reject a misleading description. Do not infer an activity merely from the description.'
    return req


def generation_request(run,ref,policy=None,*,activity_routing=None,version=VERSION):
    protocol(version)
    from .semantic_extraction import prefix,context_scope,ACTIVITIES,activity_choices
    visible,excluded=prefix(run,ref,policy)
    req={'schema':'semantic-activity-readings-request/1','stage':'activity_readings',
        'source':deepcopy(ref),'prefix':visible,'excluded_not_agent_visible':excluded,
        'activity_definitions':ACTIVITIES,**context_scope(run,ref,policy),
        'instructions':'Propose 1–3 plausible readings of what this complete source unit contributes. Each has one activity from activity_definitions, a concise natural-language description and exact evidence. Preserve request versus performance, claim versus observation and tentative versus asserted content. This proposes interpretations only; Jev will select among all activity choices. Do not extract entities, targets or relations yet. Do not invent alternatives to fill the list. Cite the current unit and any earlier visible context needed. No future information.',
        'response_contract':{'request_hash':'digest of this request','producer':'generator name/version',
            'readings':[{'activity':'one existing activity','text':'what this unit contributes',
                         'evidence':[{'event_id':ref['event_id'],'quote':'exact visible text'}]}]}}
    if activity_routing is not None:
        req['activity_routing']=activity_routing
        req['activity_definitions']=activity_choices(activity_routing)
    if version==SCOPED_VERSION:
        from .semantic_extraction import ACTIVITY_ROUTING,checked_span
        event=checked_span(run,ref)
        req['reading_protocol']=version
        req['activity_routing']=activity_routing or ACTIVITY_ROUTING
        req['activity_definitions']=activity_choices(req['activity_routing'])
        req['source_form']={'kind':event['kind'],'actor':event['actor'],
            'meaning':'Recorded source form; it does not establish semantic purpose, effect or success.'}
        req['contribution_scope']=SCOPE_RULE
    return req


def validate(run,req,response):
    from .semantic_extraction import checked_span,ACTIVITIES
    from .readable_context import contains,resolve_citation
    version=protocol(req.get('reading_protocol',VERSION))
    if response.get('reading_protocol',version)!=version:
        raise InputError('Candidate response cannot change the reading protocol')
    if version==SCOPED_VERSION and req!=generation_request(run,req['source'],req.get('context_policy'),
            activity_routing=req.get('activity_routing'),version=version):
        raise InputError('Scoped reading request differs from its source or declared definitions')
    if response.get('request_hash')!=digest(req) or not response.get('producer'):
        raise InputError('Activity readings do not bind to this source request')
    if response.get('citation_format') not in {None,'source-quotes/1','source-offsets/1','source-references/1'}:
        raise InputError('Unknown activity-reading citation format')
    rows=deepcopy(response.get('readings'))
    if not isinstance(rows,list) or not 1<=len(rows)<=3:raise InputError('Expected 1–3 activity readings')
    labels=set()
    for row in rows:
        label=row.get('activity')
        if label not in ACTIVITIES or label in {'other','unresolved'} or label in labels:
            raise InputError('Unknown, duplicate or fallback activity reading')
        labels.add(label)
        if not isinstance(row.get('text'),str) or not row['text'].strip() or len(row['text'])>3000:
            raise InputError('Activity reading needs a concise contribution description')
        if not isinstance(row.get('evidence'),list) or not row['evidence']:raise InputError('Activity reading lacks source evidence')
        materialized=[]
        for ref in row['evidence']:
            ref=resolve_citation(run,req,ref,response.get('citation_format'))
            checked_span(run,ref,req['source'])
            event=next((e for e in req['prefix'] if e['id']==ref['event_id']),None)
            if event is None or not contains(event,ref):raise InputError('Activity reading cites omitted context')
            materialized.append(ref)
        subject=req['source']
        if not any(r['event_id']==subject['event_id'] and r['start']<subject['end'] and r['end']>subject['start'] for r in materialized):
            raise InputError('Activity reading must cite the current unit')
        row['evidence']=materialized
    result={**deepcopy(response),'readings':rows}
    if version==SCOPED_VERSION:result['reading_protocol']=version
    return result


def enrich_activity(req,response):
    req=deepcopy(req)
    version=protocol(response.get('reading_protocol',VERSION))
    req['state']['activity_reading_candidates']={**response,'schema':version}
    req['questions']['choice']['instructions']+=' '+READING_RULE
    if version==SCOPED_VERSION:
        req['state']['contribution_scope']=SCOPE_RULE
        req['questions']['choice']['instructions']+=' Apply contribution_scope to this unit, without treating the proposed reading as fact.'
    for row in response['readings']:
        req['questions']['choice']['criteria'][row['activity']]+=' Candidate interpretation for this source: '+row['text']
    return req
