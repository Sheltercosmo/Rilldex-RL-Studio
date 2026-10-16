"""Version-pinned measures over reusable deterministic investigation projections.

No semantic inference is started here. Counts describe recorded witnesses;
state-sensitive rates retain all opportunities and exclude unresolved ones.
"""
from .schema import InputError, digest
from . import work_episodes, work_state, investigation_plans, graph_store, adaptation_patterns, history_evidence, feedback_opportunities
from . import work_structure_metrics
from . import work_return_references, retry_outcomes, work_visits, declared_plans, work_order, work_consistency, feedback_timing

VERSION='analysis-measures/1'
DEFINITIONS={
    'work_return_visits':('work_visits','returned','Work visits returning to an earlier subject','count'),
    'work_switch_return_fraction':('work_visits','switch_returns','Return share among decidable work switches','opportunity_ratio'),
    'consecutive_recurrences':('work_episodes','continued','Consecutive work recurrences','count'),
    'returns':('work_episodes','returned','Returns after intervening operations','count'),
    'gap_recurrences':('work_episodes','interrupted','Recurrences across observation gaps','count'),
    'assessed_recurrences':('work_episodes','recurrences_with_assessment','Recurrences with recorded feedback assessment','count'),
    'adjusted_recurrences':('work_episodes','recurrences_with_adjustment','Recurrences with attempted correction','count'),
    'same_procedure_recurrences':('work_episodes','same_procedure','Recurrences using the same procedure','count'),
    'reconfigured_recurrences':('work_episodes','reconfigured_procedure','Recurrences using a reconfigured procedure','count'),
    'different_procedure_recurrences':('adaptation_patterns','alternative_procedure','Recurrences using a different procedure','count'),
    'criterion_recovery':('work_state','recovery','Recovery of the recorded criterion','opportunity_ratio'),
    'delivery_verification':('work_state','applicable_verification','Verification applicable at delivery','opportunity_ratio'),
    'check_input_binding':('work_state','check_binding','Checks bound to recorded input state','opportunity_ratio'),
    'resume_after_preparation':('adaptation_patterns','resume_after_preparation','Same procedure after a separate correction attempt','count'),
    'procedure_change_fraction':('adaptation_patterns','procedure_change','Procedure changes among compared recurrences','opportunity_ratio'),
    'feedback_reference':('feedback_opportunities','reference','Explicit feedback reference within three text events','opportunity_ratio'),
    'feedback_assessment_after_actions':('feedback_timing','after_actions','First saved assessment after other actions','opportunity_ratio'),
}
DETAILS={
    'work_return_visits':'Recorded work visits that return to an earlier explicitly bound subject after other bound work. Consecutive same-subject contributions form one visit. Unknown gaps remain separate; this is not an exploration, recovery or quality score.',
    'work_switch_return_fraction':'Returns to an earlier subject / decidable work switches. Each later bound visit after a different bound subject (or an uncertain gap) is one opportunity. A first-recorded subject is a negative only with completely reviewed prior history in the same lane. Unknown opportunities are excluded and reported. Resumption after reviewed no-target contributions is not a switch. Conditional on annotation coverage, not population prevalence.',
    'consecutive_recurrences':'Recorded same-target recurrences without an intervening action. Recurrence does not establish failure or waste.',
    'returns':'Recorded same-target recurrences after intervening operations. This does not establish exploration, deviation or recovery.',
    'gap_recurrences':'Recorded same-target recurrences spanning missing or ambiguously ordered action observations.',
    'assessed_recurrences':'Recurrences with a saved assessment of the earlier attempt’s feedback before the recurrence. Missing links remain unestablished.',
    'adjusted_recurrences':'Recurrences with a linked correction attempt at or before dispatch. An attempted correction does not establish a successful effect.',
    'same_procedure_recurrences':'Recurrences with an exact-pair same-procedure observation. Command equality alone does not establish the comparison.',
    'reconfigured_recurrences':'Recurrences with an exact-pair reconfigured-procedure observation. This does not establish exploration or improvement.',
    'different_procedure_recurrences':'Recurrences with an exact-pair different-procedure observation. This does not establish a new objective or successful adaptation.',
    'criterion_recovery':'Recovered recorded-criterion opportunities / decidable opportunities, within the next three same-criterion checks. Requires comparable captured state and a recorded relevant change. Not whole-task recovery.',
    'delivery_verification':'Delivery requirements with an applicable recorded passing check / decidable captured delivery requirements. Conflicting outcomes, incompatible check scopes and unknown state remain unresolved, excluded from the rate and inspectable.',
    'check_input_binding':'Checks bound to a recorded input snapshot / recognized or captured checks. Binding alone does not establish stable inputs or a passing result.',
    'resume_after_preparation':'Recorded recurrences using the same dispatched procedure after a separately linked correction/preparation attempt. This does not establish a necessary prerequisite, successful correction or unchanged effective inputs.',
    'procedure_change_fraction':'Reconfigured or alternative procedures / recurrences with a saved exact-pair procedure comparison or named source review. Unknown comparisons are excluded and reported. Review provenance and observer versions remain separate. Covers recorded same-work recurrences, not all actions or all changes of strategy.',
    'feedback_reference':'Visible tool responses explicitly described or interpreted in the next three agent text events / decidable visible tool responses. Unknown windows, segmentation, inspection or candidate coverage are retained. Does not measure silent uptake, correctness or recovery.',
    'feedback_assessment_after_actions':'Responses whose earliest eligible saved assessment follows one or more recorded same-recipient dispatches / responses with a supported assessment and comparable order. Missing links stay unknown and outside the denominator. This is conditional on saved annotations; it does not locate the first actual assessment or establish ignored feedback, execution latency or causal use.',
}


def catalog(*, legacy=False):
    result={key:{'operation':op,'key':field,'label':label,'aggregation':aggregation,
                 'unit':'fraction' if aggregation=='opportunity_ratio' else 'value',
                 'version':VERSION+'|'+({'work_episodes':work_episodes.VERSION,'work_state':work_state.VERSION,'adaptation_patterns':adaptation_patterns.VERSION,'feedback_opportunities':feedback_opportunities.VERSION,'feedback_timing':feedback_timing.VERSION,'work_visits':investigation_plans.OPS['work_visits']}[op]),
                 'description':DETAILS[key]} for key,(op,field,label,aggregation) in DEFINITIONS.items()}
    for name, (basis,label,description) in work_structure_metrics.MEASURES.items():
        result[name] = dict(operation='work_structure',key=name,label=label,aggregation='count',unit='value',
            version=VERSION+'|'+investigation_plans.OPS['work_structure'],description=description+' '+work_structure_metrics.LIMIT)
    if not legacy:
        # Keep the earlier work_episodes definitions readable for frozen
        # receipts. New counters share the exact eligibility used by the
        # procedure distribution and change fraction.
        for name in ('same_procedure_recurrences', 'reconfigured_recurrences'):
            result[name].update(operation='adaptation_patterns',
                version=VERSION+'|'+adaptation_patterns.VERSION,
                description=DETAILS[name]+' Only complete, prefix-supported exact-pair selections or named source reviews with established work identity count. Partial, legacy and unresolved comparisons remain outside this witness count and visible in comparison coverage.')
    for name,key,label,aggregation,description in [
        ('declared_plan_updates','updates','Structured plan declarations','count',
         'Recorded supported task-list writes. Empty lists remain explicit. Invalid payloads are reported separately. These are agent declarations, not inferred planning effort or accepted tool state.'),
        ('declared_plan_initial_completed_fraction','initial_completed','Initial task-list entries reported complete','opportunity_ratio',
         'Completed entries / decidable entries in the first captured supported list per source lane. Earlier malformed writes or ambiguous ordering make those entries unknown. This distinguishes recorded initial status, not planning quality, verified work, or when the model formed a plan. Missing lists remain unavailable.'),
        ('declared_plan_reopen_fraction','reopened','Reported-complete items reopened','opportunity_ratio',
         'Items reported completed and later pending or active / decidable completed-item follow-ups in the next same-context list declaration. Matching uses unique native IDs with unchanged text where declared, otherwise unique exact text. Removed, renamed, duplicate-identity, unordered or interrupted comparisons remain unknown. Agent-reported status is not verified completion or semantic revision.')]:
        result[name]=dict(operation='declared_plans',key=key,label=label,aggregation=aggregation,
            unit='fraction' if aggregation=='opportunity_ratio' else 'value',
            version=VERSION+'|'+investigation_plans.OPS['declared_plans'],description=description)
    result['work_return_references']={'operation':'work_return_references','key':'references',
        'label':'Returns with recorded references','aggregation':'count','unit':'value','requires_query':True,
        'query_kind':'work_return','default_query':work_return_references.DEFAULT_QUERY,
        'referent_scopes':work_return_references.SCOPES,
        'supported_relations':sorted(work_return_references.work_route_context.RELATIONS),
        'version':VERSION+'|'+investigation_plans.OPS['work_return_references'],
        'description':work_return_references.LIMIT}
    result['history_query']={'operation':'history_evidence','key':'query','label':'Recorded history attribute match',
        'aggregation':'opportunity_ratio','unit':'fraction','requires_query':True,
        'version':VERSION+'|'+investigation_plans.OPS['history_evidence'],
        'description':'Dispatches matching the configured attributes in their latest matching prior lookup / decidable selected dispatches. Unknowns are excluded and reported. Zero selected dispatches is unavailable, not zero. This measures recorded values, not policy compliance or successful effects.'}
    result['criterion_recovery_window']={'operation':'recovery_windows','key':'recovery','label':'Criterion recovery after a recorded change',
        'aggregation':'opportunity_ratio','unit':'fraction','version':VERSION+'|'+investigation_plans.OPS['recovery_windows'],
        'description':'Failures followed by a comparable passing check with a recorded relevant input change / decidable failed-check opportunities, within the next three recorded same-criterion checks. A negative requires three comparable failing checks; incomplete windows and unsupported passes remain unknown. Not whole-task success or causal credit.'}
    for name,key,label,description in [
        ('repeated_failed_checks','repeated_failures','Failures followed by repeated unsuccessful checks',
         'Failed-check windows containing at least two comparable failed follow-up checks. Windows can overlap; this is not a count of unique attempts or wasted compute.'),
        ('incomplete_recovery_followup','incomplete_followup','Failures with unresolved recovery follow-up',
         'Failed-check windows whose recovery is unknown because follow-up, comparable state or outcomes are incomplete. This is an evidence gap, not failed or abandoned work.')]:
        result[name]=dict(operation='recovery_windows',key=key,label=label,aggregation='count',unit='value',
            version=VERSION+'|'+investigation_plans.OPS['recovery_windows'],description=description)
    for suffix, group, label in [
        ('', 'all', 'Next-check success after failure'),
        ('_changed', 'recorded_relevant_change', 'Next-check success · recorded relevant input change'),
        ('_unchanged', 'unchanged_captured_inputs', 'Next-check success · unchanged captured inputs')]:
        result['next_check_success' + suffix] = dict(operation='retry_outcomes', key=group, label=label,
            aggregation='opportunity_ratio', unit='fraction', version=VERSION+'|'+investigation_plans.OPS['retry_outcomes'],
            description='Comparable passing first rechecks / decidable first rechecks after visible failures. '
                + ('Includes every captured input category. ' if group == 'all' else
                   'Restricted to ' + label.split(' · ')[1] + '; known other input groups are excluded, unresolved membership stays unknown. ')
                + 'No later pass replaces the first retry. Captured input changes are not semantic revisions; this rate is not a causal effect or whole-task success.')
    for original, name, label in [
        ('work_return_visits','work_return_visits_parallel','Returns after other work · parallel work included'),
        ('work_switch_return_fraction','work_switch_return_fraction_parallel','Return share · parallel work included'),
        ('work_return_references','work_return_references_parallel','References when returning to work · parallel work included')]:
        result[name] = {**result[original], 'label':label, 'recurrence_order':work_order.VERSION,
            'description':result[original]['description'] + ' Complete observed parallel dispatch groups may intervene between ordered recurrence endpoints. Sibling order is never inferred. Unordered switch entries and incomplete coverage remain unknown. This is a separately versioned ordering policy; earlier measures are unchanged.'}
    parallel = result['work_return_references_parallel']
    parallel['extraction_version'] = investigation_plans.OPS['work_return_references']
    parallel['version'] += '|return-reference-ordering/1|' + work_order.VERSION
    if not legacy:
        for spec in result.values():
            if spec['operation'] not in {'work_visits','work_return_references'}: continue
            spec['extraction_version'] = investigation_plans.OPS[spec['operation']]
            spec['version'] += '|' + work_consistency.POLICY
            spec['scope_consistency'] = work_consistency.POLICY
            spec['description'] += ' ' + work_consistency.LIMIT
    return result


def validate(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('measure'),str) or raw['measure'] not in catalog():
        raise InputError('Select a supported analysis measure')
    spec=catalog()[raw['measure']]
    allowed={'measure','version','query'} if spec.get('requires_query') else {'measure','version'}
    if set(raw)-allowed:raise InputError('Unsupported fields for this analysis measure')
    if raw.get('version',spec['version'])!=spec['version']:
        prior=catalog(legacy=True)[raw['measure']]
        if raw.get('version')!=prior['version']:raise InputError('Analysis version is unavailable; create a monitor with the current definition')
        spec=prior
    result={'measure':raw['measure'],'version':spec['version']}
    if spec.get('requires_query'):
        result['query']=(work_return_references.validate if spec['operation']=='work_return_references' else history_evidence.validate)(raw.get('query'))
    return result


def definition(selector):
    spec=catalog()[selector['measure']]
    if selector.get('version',spec['version'])!=spec['version']:
        spec=catalog(legacy=True)[selector['measure']]
        if selector['version']!=spec['version']:raise InputError('Analysis definition version is unavailable')
    return {**spec,'query':selector['query'],'label':selector['query']['name']} if spec.get('requires_query') else spec


def projection_params(spec,run_id,source_hash,graph_id):
    result={'run_id':run_id,'source_hash':source_hash}
    if spec.get('recurrence_order'):result['recurrence_order']=spec['recurrence_order']
    if spec.get('scope_consistency'):result['scope_consistency']=spec['scope_consistency']
    result.update({'query':spec['query']} if spec.get('requires_query') else {'graph_id':graph_id})
    if spec['operation']=='work_return_references':result['graph_id']=graph_id
    return result


def specification(monitor):
    # A stored definition retains its own metric semantics for old receipts.
    return monitor['analysis_definition']


def definition_notice(monitor):
    """Presentation metadata; never alter a stored definition or receipt."""
    if monitor.get('kind') != 'analysis': return None
    measure = monitor.get('analysis', {}).get('measure')
    if measure not in ('same_procedure_recurrences', 'reconfigured_recurrences'): return None
    spec = monitor.get('analysis_definition', {})
    if spec.get('operation') != 'work_episodes': return None
    return dict(kind='historical_procedure_rules', current_version=catalog()[measure]['version'],
        message='Historical procedure rules can count partial, legacy or unresolved comparisons. Review the current definition to apply completed exact-pair checks. Saved historical values are preserved.')


def projection_plan(spec,run_id,source_hash,graph_id):
    supplied={'run_id':run_id,'source_hash':source_hash,'graph_id':graph_id}
    if spec.get('recurrence_order'):supplied['recurrence_order']=spec['recurrence_order']
    if spec.get('scope_consistency'):supplied['scope_consistency']=spec['scope_consistency']
    if spec.get('requires_query'):supplied['query']=spec['query']
    return investigation_plans.registry_or_default(None).projection_plan(
        spec['operation'],supplied,schema=investigation_plans.VERSION)


def measure(output,spec):
    key=spec['key'];cases=[]
    if spec['operation'] in {'work_visits','work_return_references'} and output.get('scope_consistency')!=spec.get('scope_consistency'):
        raise InputError('Work-consistency policy differs from the saved measure definition')
    readers = {'declared_plans': declared_plans.measure, 'retry_outcomes': retry_outcomes.measure,
               'work_structure': work_structure_metrics.measure}
    if spec['operation'] in readers:
        return readers[spec['operation']](output,key)
    if spec['operation']=='work_return_references':
        if output['query']!=spec['query']:raise InputError('Work-return query differs from its projection')
        if output.get('recurrence_order') != spec.get('recurrence_order'):
            raise InputError('Work-return ordering differs from its projection')
        for row in output['records']:
            if not row['references']:continue
            cases.append(dict(id=row['id'],label=row['target'],taken=None if row.get('work_conflicts') else True,status=row['status'],
                node_ids=row['node_ids'],edge_ids=row['edge_ids'],record=row,work_visit_id=row['visit_id']))
            if row.get('work_conflicts'):cases[-1]['work_conflicts']=row['work_conflicts']
            if output.get('recurrence_order'):cases[-1]['recurrence_order']=output['recurrence_order']
        disputed=bool(output.get('scope_consistency') and output['coverage'].get('disputed_work_visits'))
        if output['value']!=(len(cases) if output['observed'] and not disputed else None):raise InputError('Work-return references do not reconcile')
        return dict(value=output['value'],numerator=None,denominator=None,opportunities=None,unknown=None,
            cases=cases,coverage=output['coverage'],reason='Count withheld: saved work identities conflict. Review the disputed assignments.' if disputed else 'Recorded witnesses only; returns without a matching saved link remain unestablished.' if output['observed'] else 'No bound contribution-work subjects.')
    if spec['operation']=='work_visits':
        if output.get('recurrence_order') != spec.get('recurrence_order'):
            raise InputError('Work recurrence ordering differs from the saved measure definition')
        if key=='returned':
            for row in output['records']:
                if row.get('unqualified_category',row['category'])=='returned':
                    case=dict(id=row['id'], label=row['target'], taken=None if row.get('work_conflicts') else True, status='disputed_work_identity' if row.get('work_conflicts') else 'returned',
                        node_ids=row['node_ids'], edge_ids=row['edge_ids'], episode=row['episode'], work_visit=row)
                    if row.get('work_conflicts'):case['work_conflicts']=row['work_conflicts']
                    if output.get('recurrence_order'):case['recurrence_order']=output['recurrence_order']
                    cases.append(case)
            disputed=bool(output.get('scope_consistency') and output['coverage'].get('disputed_work_visits'))
            return dict(value=len(cases) if output['observed'] and not disputed else None, numerator=None, denominator=None,
                opportunities=None, unknown=None, cases=cases, coverage=output['coverage'],
                reason='Count withheld: saved work identities conflict. Review the disputed assignments.' if disputed else 'Recorded return witnesses; incomplete identity remains unestablished.' if output['observed'] else 'No bound contribution-work subjects.')
        for row in output['switches']:
            case=dict(id=row['id'], label=row['target'], taken=row['value'], status=row['status'],
                node_ids=row['node_ids'], edge_ids=row['edge_ids'], record=row, work_visit_id=row['visit_id'])
            if row.get('work_conflicts'):case['work_conflicts']=row['work_conflicts']
            if output.get('recurrence_order'):case['recurrence_order']=output['recurrence_order']
            cases.append(case)
        return {**output['metrics'], 'cases':cases, 'coverage':output['coverage'],
                'reason':None if output['metrics']['denominator'] else 'Work identity conflicts leave no decidable switches. Review the disputed assignments.' if output['coverage'].get('disputed_work_switches') else 'No decidable work switches; annotation gaps stay unknown.'}
    if spec['operation']=='recovery_windows':
        for row in output['records']:
            cases.append({'id':row['id'],'label':row['criterion_id']+' · failure '+row['failure_action_id'],
                'taken':row['value'],'status':row['status'],'node_ids':['event:'+eid for eid in row['event_ids']],
                'edge_ids':row['feedback_reference_edge_ids'],'record':row,'recovery_window':True})
        n=sum(c['taken'] is True for c in cases);d=sum(c['taken'] is not None for c in cases)
        if key in {'repeated_failures','incomplete_followup'}:
            selected=[c for c in cases if (c['taken'] is None if key=='incomplete_followup' else
                sum(a['status']=='failed' for a in c['record']['attempts'])>=2)]
            return dict(value=len(selected) if cases else None,numerator=None,denominator=None,
                opportunities=len(cases),unknown=len(cases)-d,cases=selected,coverage=output['coverage'],
                reason='Recorded failed-check windows; overlapping windows are not independent attempts.' if cases else 'No visible recorded failed checks.')
        expected={'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(cases),'unknown':len(cases)-d}
        if output['metrics']!=expected:raise InputError('Recovery opportunities do not reconcile with projection')
        return {**expected,'cases':cases,'coverage':output['coverage'],
            'reason':None if d else 'Recovery windows or captured state remain incomplete.' if cases else 'No visible recorded failed checks.'}
    if spec['operation'] in {'feedback_opportunities','feedback_timing'}:
        for row in output['observations']:
            cases.append({'id':row['id'],'label':'Response '+row['response_event_id'],'taken':row['value'],
                'status':row['status'],'node_ids':row['node_ids'],'edge_ids':row['edge_ids'],'record':row,
                **({'feedback_timing':True} if spec['operation']=='feedback_timing' else {})})
        n=sum(c['taken'] is True for c in cases);d=sum(c['taken'] is not None for c in cases)
        expected={'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(cases),'unknown':len(cases)-d}
        if output['metrics']!=expected:raise InputError('Feedback opportunities do not reconcile with projection')
        return {**expected,'cases':cases,'coverage':output['coverage'],
            'reason':None if d else 'Feedback assessment links or timing are incomplete.' if cases and spec['operation']=='feedback_timing' else 'Feedback reference coverage is incomplete.' if cases else 'No visible bound tool responses; measure is not applicable.'}
    if spec['operation']=='history_evidence':
        if output['query']!=spec['query']:raise InputError('Analysis query differs from its projection')
        for row in output['observations']:
            ids=[row['action_id'],row['history_action_id'],row['result_event_id'],*row['invalidating_action_ids']]
            cases.append({'id':'history-case-'+digest([output['id'],row['action_id']]),
                'label':'Dispatch '+row['action_id'],'taken':row['value'],
                'status':'match' if row['value'] is True else 'mismatch' if row['value'] is False else 'unknown',
                'node_ids':list(dict.fromkeys('event:'+i for i in ids if i)),
                'edge_ids':[],'record':row,'history_evidence':True})
        n=sum(c['taken'] is True for c in cases);d=sum(c['taken'] is not None for c in cases)
        expected={'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(cases),'unknown':len(cases)-d}
        if output['metrics']!=expected:raise InputError('History query opportunities do not reconcile with projection')
        return {**expected,'cases':cases,'coverage':{},'reason':None if d else 'No decidable selected dispatches.' if cases else 'No dispatches selected by this query.'}
    if spec['operation']=='adaptation_patterns':
        for row in output['records']:
            if key=='procedure_change':
                taken=None if row['procedure']=='unresolved' else row['procedure']!='same_procedure'
            elif key=='resume_after_preparation':
                taken=row['procedure']=='same_procedure' and bool(row['preparation_edge_ids'])
            elif key in {'same_procedure','reconfigured_procedure','alternative_procedure'}:
                taken=row['procedure']==key
            else:raise InputError('Unknown procedure measure')
            if spec['aggregation']=='count' and not taken:continue
            e=row['episode']
            cases.append({'id':row['id'],'label':row['target'],'taken':taken,'status':row['procedure'],
                          'node_ids':[c['unit_id'] for c in e['cards']], 'edge_ids':e['edge_ids'],
                          'episode':e,'adaptation':{k:v for k,v in row.items() if k!='episode'}})
        if spec['aggregation']=='count':
            return {'value':len(cases) if output['observed'] else None,'numerator':None,'denominator':None,
                    'opportunities':None,'unknown':None,'cases':cases,'coverage':output['coverage'],
                    'reason':'Count of recorded witnesses; incomplete relationships remain unestablished.' if output['observed'] else 'No usable work recurrence or identity review.'}
        n=sum(c['taken'] is True for c in cases);d=sum(c['taken'] is not None for c in cases)
        return {'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(cases),
                'unknown':len(cases)-d,'cases':cases,'coverage':output['coverage'],
                'reason':None if d else 'No established exact-pair procedure comparisons.'}
    if spec['operation']=='work_episodes':
        observed=bool(output['counts']['identity_reviewed'] or output['episodes'])
        for e in output['episodes']:
            if key=='recurrences_with_assessment':selected=bool(e['assessment_unit_ids'])
            elif key=='recurrences_with_adjustment':selected=bool(e['adjustments'])
            elif key.endswith('_procedure'):selected=(e.get('method') or {}).get('comparison')==key
            else:selected=e['category']==key
            if selected:cases.append({'id':e['id'],'label':e['target'],'taken':True,'status':'recorded',
                'node_ids':[c['unit_id'] for c in e['cards']],'edge_ids':e['edge_ids'],
                'episode':e})
        return {'value':len(cases) if observed else None,'numerator':None,'denominator':None,
                'opportunities':None,'unknown':None,'cases':cases,'coverage':output['counts'],
                'reason':'Recorded witnesses; missing semantic links remain unestablished.' if observed else 'No work-identity review or positive recurrence is recorded.'}
    if key=='recovery':
        for e in output['episodes']:
            taken=None if e['status']=='unknown' else e['status']=='recovered'
            cases.append({'id':e['id'],'label':'Check '+e['failure']+' → '+(e['retry'] or 'no comparable retry'),
                          'status':e['status'],'taken':taken,'node_ids':['event:'+x for x in e['event_ids']], 'edge_ids':[],'record':e})
    elif key=='applicable_verification':
        from .delivery_verification import value as verification_value
        for d in output['deliveries']:
            taken=verification_value(d['status'])
            cases.append({'id':'delivery-'+digest([d['event_id'],d['requirement']]),'label':'Delivery '+d['event_id']+' · '+d['requirement']['criterion_id'],
                          'status':d['status'],'taken':taken,'node_ids':['event:'+x for x in d['event_ids']], 'edge_ids':[],'record':d})
    else:
        for q in output['checks']:
            cases.append({'id':'check-'+q['action_id'],'label':'Check '+q['action_id'],'taken':bool(q.get('snapshot_id')),
                          'status':'bound' if q.get('snapshot_id') else 'unbound','node_ids':['event:'+x for x in [q['action_id'],q.get('result_event_id')] if x], 'edge_ids':[],'record':q})
    n=sum(c['taken'] is True for c in cases);d=sum(c['taken'] is not None for c in cases)
    m=output['metrics'][key]
    if (n,d,len(cases))!=(m['numerator'],m['denominator'],m['opportunities']):raise InputError('Analysis opportunities do not reconcile with projection')
    return {'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(cases),
            'unknown':len(cases)-d,'cases':cases,'coverage':{},'reason':None if d else 'No decidable recorded opportunities; unknowns are retained.'}


def evaluate(store,monitor,graph):
    selector=validate(monitor['analysis']);spec=specification(monitor)
    if spec!=definition(selector):raise InputError('Analysis definition does not match the selected version')
    plan=projection_plan(spec,graph['run_id'],graph['source_hash'],graph['id'])
    result=investigation_plans.execute(store,plan);output=result['outputs']['observation'];m=measure(output,spec)
    analysis={'plan_id':result['id'],'output_id':output['id'],'output_hash':digest(output),
              'input_graph_id':graph['id'],'definition':spec,'measurement':m}
    return {k:m[k] for k in ('value','numerator','denominator','opportunities','unknown','coverage','reason')}|{
        'status':'available' if m['value'] is not None else 'unavailable','graph_id':output['graph_id'],
        'evidence_ids':list(dict.fromkeys(i for c in m['cases'] if c['taken'] is True for i in c['node_ids'])),
        'analysis':analysis}


def receipt(store,value,monitor):
    a=value['analysis'];spec=specification(monitor)
    if a['definition']!=spec:raise InputError('Saved analysis definition differs from monitor')
    plan=investigation_plans.read_plan(store,a['plan_id']);output=investigation_plans.read_output(store,a['output_id'])
    expected_plan=projection_plan(spec,value['run_id'],value['source_hash'],a['input_graph_id'])
    if plan['definition']!=expected_plan or len(plan['nodes'])!=len(expected_plan['nodes']):raise InputError('Analysis plan is bound to a different source or dependency')
    node=plan['definition']['nodes'][-1];p=node['params']
    extraction_version=spec.get('extraction_version',spec['version'].split('|',1)[1])
    if plan['nodes'][-1]['version']!=extraction_version or output['schema']!=extraction_version.split('|')[0]:raise InputError('Analysis extraction version mismatch')
    # Validate saved dependencies against the monitor's pinned composite recipe,
    # never the installed registry. Reading a receipt must survive an upgrade
    # without executing a newer extraction or weakening its content checks.
    if spec['operation'] in {'recovery_windows','retry_outcomes'}:
        recovery_version = extraction_version if spec['operation']=='recovery_windows' else extraction_version.partition('|')[2]
        parts = recovery_version.split('|')
        if (len(parts)!=3 or not parts[0].startswith('recovery-windows/')
                or not parts[1].startswith('work-state/') or not parts[2].startswith('feedback-reference-opportunities/')):
            raise InputError('Saved recovery dependency recipe is unsupported')
        state_version = parts[1]
    if spec['operation']=='recovery_windows':
        if plan['nodes'][0]['version']!=state_version:raise InputError('Recovery state dependency version mismatch')
        dependency=investigation_plans.read_output(store,output['state_projection_id'])
        if (dependency['schema']!=state_version or digest(dependency)!=plan['nodes'][0]['output_hash']
                or dependency['source_hash']!=value['source_hash'] or dependency['run_id']!=value['run_id']):
            raise InputError('Recovery state dependency differs from its receipt')
        if output['input_graph_id']!=a['input_graph_id']:raise InputError('Recovery reference graph differs from its receipt')
    if spec['operation']=='retry_outcomes':
        dependencies = [(output['state_projection_id'], 0, state_version),
                        (output['recovery_projection_id'], 1, recovery_version)]
        saved = []
        for identifier, index, version in dependencies:
            dependency=investigation_plans.read_output(store,identifier)
            if (plan['nodes'][index]['version']!=version or dependency['schema']!=version.split('|')[0]
                    or digest(dependency)!=plan['nodes'][index]['output_hash']
                    or dependency['source_hash']!=value['source_hash'] or dependency['run_id']!=value['run_id']):
                raise InputError('Next-check dependency differs from its receipt')
            saved.append(dependency)
        if (saved[1]['state_projection_id']!=saved[0]['id']
                or saved[1]['input_graph_id']!=a['input_graph_id'] or output['input_graph_id']!=a['input_graph_id']):
            raise InputError('Next-check dependency binding differs from its receipt')
    if digest(output)!=a['output_hash'] or plan['nodes'][-1]['output_hash']!=a['output_hash'] or output['id']!=a['output_id']:raise InputError('Analysis output identity mismatch')
    if output['run_id']!=value['run_id'] or output['source_hash']!=value['source_hash'] or output['graph_id']!=value['graph_id']:raise InputError('Analysis evidence graph mismatch')
    input_graph=graph_store.read(store,a['input_graph_id'])
    if input_graph['observer']!=monitor['observer'] or value['input_id']!=input_graph['id'] or input_graph['source_hash']!=value['source_hash'] or input_graph['run_id']!=value['run_id']:raise InputError('Analysis input observer mismatch')
    # Reconcile arithmetic and witnesses without invoking a newer extraction.
    m=a['measurement'];cases=m['cases']
    if measure(output,spec)!=m:raise InputError('Saved analysis measure differs from its projection')
    if len({c['id'] for c in cases})!=len(cases):raise InputError('Duplicate analysis opportunities')
    graph=graph_store.read(store,value['graph_id']);nodes={n['id'] for n in graph['nodes']};edges={e['id'] for e in graph['edges']}
    if any(not set(c['node_ids'])<=nodes or not set(c['edge_ids'])<=edges for c in cases):raise InputError('Analysis witness missing from bound graph')
    if spec['aggregation']=='opportunity_ratio':
        n=sum(c['taken'] is True for c in cases);d=sum(c['taken'] is not None for c in cases)
        expected={'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(cases),'unknown':len(cases)-d}
    else:expected={'value':len(cases) if m['value'] is not None else None,'numerator':None,'denominator':None,'opportunities':None,'unknown':None}
    if any(value.get(k)!=v or m.get(k)!=v for k,v in expected.items()):raise InputError('Analysis arithmetic differs from cases')
    evidence=list(dict.fromkeys(i for c in cases if c['taken'] is True for i in c['node_ids']))
    if value['evidence_ids']!=evidence:raise InputError('Analysis contributing evidence differs from cases')
    display_cases=list(cases)
    if spec['operation']=='work_visits' and spec['key']=='switch_returns':
        # Read-only explanation metadata. Preserve the saved v1 projection,
        # arithmetic and original full-visit case hashes for historical replay.
        display_cases = [{**c,'entry_scope':work_visits.entry_evidence(graph,output,c)} for c in cases]
    if spec['operation']=='work_return_references':
        display_cases += [dict(id=r['id'],label=r['target']+(' · disputed work' if r.get('work_conflicts') else ' · reference not established'),taken=None,
            status=r['status'],node_ids=r['node_ids'],edge_ids=r['edge_ids'],record=r,work_visit_id=r['visit_id'],
            **({'work_conflicts':r['work_conflicts']} if r.get('work_conflicts') else {}),
            **({'recurrence_order':output['recurrence_order']} if output.get('recurrence_order') else {}))
            for r in output['records'] if not r['references']]
    if output.get('scope_consistency'):
        for conflict in output['work_consistency']['conflicts']:
            display_cases.append(dict(id=conflict['id'],label='Conflicting work assignments',taken=None,
                status='disputed_work_identity',node_ids=[b['unit_id'] for b in conflict['bindings']],
                edge_ids=[conflict['edge_id']],work_conflicts=[conflict]))
    return graph,output,{'definition':spec['description'],'unit':spec['unit'],'basis':'analysis_projection',
        'value':value['value'],'numerator':value['numerator'],'denominator':value['denominator'],
        'status':value['status'],'reason':value['reason'],'cases':[], 'analysis_cases':display_cases,
        'opportunities':m['opportunities'],'unknown':m['unknown'],'coverage':m['coverage'],
        'evidence_ids':evidence,'engine_version':monitor['analysis']['version'],'plan_id':a['plan_id'],
        'limitations':output['limits']}
