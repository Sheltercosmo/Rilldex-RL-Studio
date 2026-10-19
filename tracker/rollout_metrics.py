"""One evidence-linked observation per rollout snapshot and observer version.

Training coordinates never come from import order or checkpoint-name parsing.
Unknown semantic constructs remain unavailable, not zero-valued measurements.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import json
import math
from .schema import digest, dumps, InputError
from .capabilities import links

VERSION = 'rollout-behavior/20'
DEFINITIONS = {
 'actions': ('Dispatched actions', 'Count of non-copied agent action events. Does not measure success.'),
 'agent_text_chars': ('Agent text characters', 'Characters in recorded non-copied agent prose; not tokens or hidden reasoning.'),
 'feedback_link_rate': ('Actions with a recorded response', 'Unique actions with source-linked feedback / all agent actions. A response is not success.'),
 'exact_dispatch_repeat_rate': ('Repeated dispatch fraction', 'Actions whose tool, arguments and text appeared earlier in the same actor, trajectory and recorded context / all agent actions. Not semantic repetition or waste.'),
 'recorded_success': ('Source-reported task success', 'Explicit boolean verified_success in the normalized outcome; unavailable otherwise. No completion-text heuristic.'),
 'recorded_reward': ('Logged reward', 'Explicit finite producer score for one rollout. Its reward function and scale belong to the source experiment; not independent correctness, task success or semantic accuracy.'),
 'annotated_actions_fraction': ('Action annotation coverage', 'Unique source agent dispatches represented in this semantic map / all source agent dispatches.'),
 'recurring_target_fraction': ('Recurring target fraction', 'Saved recurring target assignments / represented action operations. Unknown identity is reported separately; recurrence is not failure.'),
 'identity_unresolved_fraction': ('Unresolved target identity', 'Unresolved or uninspected action identities / represented operations.'),
 'plan_stage_attempt_fraction': ('Plan stages with an attempt', 'Distinct (Plan unit, stage) with a saved attempts_plan_step link / all extracted Plan stages. Not completion.'),
 'activity_verify_share': ('Verify share in prose', 'Verify units / agent semantic prose units in this map. Excludes dispatched tool actions. Unit frequency, not time or effort.'),
 'activity_plan_share': ('Plan share in prose', 'Plan units / agent semantic prose units in this map. Excludes dispatched tool actions. Not planning quality.'),
 'agent_verify_unit_share': ('Verify share across tagged activities', 'Verify units / all saved agent prose and dispatched-action units with activity labels. Includes unresolved labels in the denominator; excludes user and environment units. Conditional on annotation coverage, not passing checks, time or effort.'),
 'agent_plan_unit_share': ('Plan share across tagged activities', 'Plan units / all saved agent prose and dispatched-action units with activity labels. Includes unresolved labels in the denominator; excludes user and environment units. Conditional on annotation coverage, not planning quality or effort.'),
 'execution_report_coverage': ('Executor response inspection coverage', 'Inspected source-bound visible executor responses / all eligible source responses. Includes unresolved selections; not semantic accuracy.'),
 'execution_error_report_fraction': ('Responses reporting execution errors', 'Responses selected as containing an executor error / responses with a decidable error observation. Missing or incomplete negative observations are excluded. Not whole-operation failure rate.'),
 'execution_error_unknown_fraction': ('Unknown execution-error observations', 'Uninspected, unresolved or incomplete negative observations / all eligible source responses. Reported positives remain evidence of a report despite unrelated omissions.'),
 'execution_warning_report_fraction': ('Responses reporting execution warnings', 'Responses selected as containing an executor warning / responses with a decidable warning observation. Not task failure or degraded-result rate.'),
 'target_revisit_after_error_count': ('Target revisits after error reports', 'Unique actions revisiting a selected earlier target whose response already reported an executor error. Temporal association, not causal retry or recovery.'),
 'plan_stage_change_count': ('Observed Plan-stage changes', 'Changes between selected stage correspondences within one Plan in recorded source order. Unassigned gaps remain recorded; ambiguous batch order is excluded. Not active-goal changes or progress.'),
 'plan_stage_reentry_count': ('Observed Plan-stage re-entries', 'Stage changes returning to a stage observed earlier in the same Plan. Not a mental return, failure or wasted work.'),
 'plan_stage_material_coverage': ('Plan product-response inspection coverage', 'Inspected stage-product response pairs / eligible source-bound responses to stage attempts and checks. Preparation is excluded. Coverage is not accuracy.'),
 'plan_stages_with_contents_fraction': ('Plan stages with recorded contents', 'Distinct Plan stages with a contents selection / extracted Plan stages. Returned contents may contain unsupported claims or be stored artifacts. Not completion or verification.'),
 'operation_outcome_coverage': ('Operation-response outcome coverage', 'Inspected source-bound response pairs / eligible visible response pairs. Includes unresolved outcomes; not accuracy.'),
 'operation_failed_fraction': ('Failed operation fraction', 'Calls with a failed outcome / calls with completed, failed or partial outcomes and complete consistent response sets. Pending and unknown calls are excluded. Not task failure rate.'),
 'operation_unknown_fraction': ('Unknown operation outcome fraction', 'Calls without a complete consistent outcome, including uninspected calls / calls with an eligible source-bound response. Missing response calls remain outside this denominator.'),
 'completed_after_failed_call_count': ('Completed calls after failed calls', 'Unique later calls with a completed outcome following an already-observed failed call on the same selected target. Not task recovery, causal attribution or result correctness.'),
 'exploration_rate': ('Exploration', 'Requires validated alternative-direction and work-history interpretation; not yet measured.'),
 'plan_deviation_rate': ('Plan deviation', 'Requires current Plan scope plus supported departures; not yet measured.'),
 'recovery_rate': ('Recovery after failure', 'Requires scoped failure, subsequent attempt and confirmed recovery; not yet measured.'),
 'plan_completion_rate': ('Plan completion', 'Requires result evidence for each stage; attempts and reports alone are insufficient.'),
}
from .diagnostic_monitors import DETECTORS as BASE_DIAGNOSTIC_DETECTORS
from .diagnostic_access import definitions as access_definitions
DIAGNOSTIC_DETECTORS=access_definitions(BASE_DIAGNOSTIC_DETECTORS)
DEFINITIONS.update({'diagnostic_'+k:(label+' · experimental',definition+' Per-rollout indicator (1/0); unresolved or unsupported evidence is unavailable. Incidence uses only decidable inspected rollouts; not a policy-violation or confirmed reward-hacking rate.') for k,(label,definition) in DIAGNOSTIC_DETECTORS.items()})
from .requirement_diagnostics import METRIC as REQUIREMENT_METRIC, DEFINITION as REQUIREMENT_DEFINITION
DEFINITIONS['diagnostic_'+REQUIREMENT_METRIC]=REQUIREMENT_DEFINITION
from .reward_records import DEFINITIONS as REWARD_DEFINITIONS, INDICATORS as REWARD_INDICATORS
DEFINITIONS.update(REWARD_DEFINITIONS)
from .feedback_assessment import DEFINITIONS as FEEDBACK_DEFINITIONS
DEFINITIONS.update(FEEDBACK_DEFINITIONS)
from .retry_metrics import DEFINITIONS as RETRY_DEFINITIONS
DEFINITIONS.update(RETRY_DEFINITIONS)
from .revision_metrics import DEFINITIONS as REVISION_DEFINITIONS
DEFINITIONS.update(REVISION_DEFINITIONS)
from .adjustment_graph import DEFINITIONS as LINKED_ADJUSTMENT_DEFINITIONS
DEFINITIONS.update(LINKED_ADJUSTMENT_DEFINITIONS)
from .environment_metrics import DEFINITIONS as ENVIRONMENT_DEFINITIONS, measures as environment_measures
DEFINITIONS.update(ENVIRONMENT_DEFINITIONS)
from .tool_contracts import DEFINITIONS as TOOL_CONTRACT_DEFINITIONS
DEFINITIONS.update(TOOL_CONTRACT_DEFINITIONS)


def metric_aggregation(name):
    if name in RETRY_DEFINITIONS or name in REVISION_DEFINITIONS or name in LINKED_ADJUSTMENT_DEFINITIONS or name in {'feedback_assessment_fraction','feedback_assessment_unknown_fraction','plan_stage_attempt_fraction','environment_model_response_fraction','environment_tool_error_fraction','environment_tool_error_coverage','reward_component_coverage'}:
        return 'opportunity_ratio'
    return 'incidence' if name.startswith('diagnostic_') or name in REWARD_INDICATORS or name in {'environment_terminated','environment_truncated','environment_done'} else 'distribution'


def measurement(value=None, *, numerator=None, denominator=None, evidence=(), reason=None):
    if denominator is not None:
        value = numerator / denominator if denominator else None
        if not denominator: reason = reason or 'No eligible denominator'
    return {'value': value, 'numerator': numerator, 'denominator': denominator,
            'status': 'available' if value is not None else 'unavailable',
            'evidence_ids': list(evidence), 'reason': reason}


def source_record(run):
    events=[e for e in run['events'] if not e.get('copied_context') and e['actor']=='agent']
    actions=[e for e in events if e['kind']=='action']; prose=[e for e in events if e['kind'] in {'reasoning','message'}]
    feedback=links(run); linked=[e['id'] for e in actions if feedback['by_action'].get(e['id'])]
    seen=set(); repeats=[]
    for e in actions:
        key=(e['actor'],e['trajectory_id'],e.get('context_id'),digest({k:e.get(k) for k in ('tool','arguments','text')}))
        if key in seen: repeats.append(e['id'])
        seen.add(key)
    success=run.get('outcome',{}).get('verified_success')
    reward=run.get('outcome',{}).get('recorded_reward')
    reward_refs=[]
    if reward is None:
        # Harbor's named verifier output lives in a separately preserved result
        # source. Select the conventional `reward` key or an explicit metadata
        # reward_key. Never infer a scalar from an arbitrary multi-reward map.
        key=run.get('metadata',{}).get('reward_key','reward')
        candidates=[]
        for fact in run.get('environment_context',{}).get('facts',[]):
            if fact['key']=='verifier rewards' and isinstance(key,str) and isinstance(fact['value'],dict) and key in fact['value']:
                candidates.append((fact['value'][key],{'source_id':fact['source_id'],'pointer':fact['pointer']+'/'+key.replace('~','~0').replace('/','~1')}))
            elif fact['key']=='producer final reward':
                candidates.append((fact['value'],{'source_id':fact['source_id'],'pointer':fact['pointer']}))
        if len(candidates)==1:
            reward,ref=candidates[0];reward_refs=[ref]
    reward_known=isinstance(reward,(int,float)) and not isinstance(reward,bool) and math.isfinite(reward)
    values={
        'actions':measurement(len(actions),evidence=[e['id'] for e in actions]),
        'agent_text_chars':measurement(sum(len(e['text']) for e in prose),evidence=[e['id'] for e in prose]),
        'feedback_link_rate':measurement(numerator=len(linked),denominator=len(actions),evidence=linked),
        'exact_dispatch_repeat_rate':measurement(numerator=len(repeats),denominator=len(actions),evidence=repeats),
        'recorded_success':measurement(int(success) if isinstance(success,bool) else None,reason=None if isinstance(success,bool) else 'No explicit source task-success boolean'),
        'recorded_reward':measurement(reward if reward_known else None,evidence=[run['outcome']['recorded_reward_pointer']] if reward_known and run['outcome'].get('recorded_reward_pointer') else [],reason=None if reward_known else 'No explicit finite rollout reward'),
    }
    if reward_refs:values['recorded_reward']['source_refs']=reward_refs
    for key in DEFINITIONS:
        if key not in values: values[key]=measurement(reason='No complete semantic observation' if key not in {'exploration_rate','plan_deviation_rate','recovery_rate','plan_completion_rate'} else DEFINITIONS[key][1])
    if run.get('adapter') in {'verl-generation','generation'}:
        for key in ('actions','feedback_link_rate','exact_dispatch_repeat_rate'):
            values[key]=measurement(reason='Flattened generation export has no structured action/response coverage')
    for key,params in environment_measures(run).items():values[key]=measurement(**params)
    from .reward_records import inspect as inspect_reward
    reward_inspection=inspect_reward(run,include_criteria=False)
    for key,params in reward_inspection['metrics'].items():values[key]=measurement(**params)
    return {'schema':VERSION,'run_id':run['id'],'source_hash':digest(run),'observer':'source','observation_kind':'source',
            'observer_label':'Recorded source','annotation_hash':None,'metrics':values,
            'metadata':run['metadata'],'adapter_version':run['adapter_version'],
            'activity_counts':{},'reward_inspection_protocol':reward_inspection['protocol'],
            'scope':'Recorded rollout snapshot; copied context and other participants excluded from agent counts. Evaluator feedback is inspected separately from agent-visible events.'}


def semantic_record(run,bundle):
    from .measurement_lineage import semantic_input_hash
    d=bundle['document']
    if d.get('source_hash')!=digest(run): raise InputError('Metric source and semantic map differ')
    result=source_record(run);result.update(observer=bundle['observer']['id'],observer_label=bundle['observer']['label'],observation_kind='semantic',annotation_hash=semantic_input_hash(d))
    units={u['id']:u for u in d['units']}; actions={e['id'] for e in run['events'] if e['kind']=='action' and e['actor']=='agent' and not e.get('copied_context')}
    represented={u['source']['event_id'] for u in units.values() if u['actor']=='agent' and u['kind']=='action'}&actions
    m=result['metrics'];m['annotated_actions_fraction']=measurement(numerator=len(represented),denominator=len(actions),evidence=sorted(represented))
    prose=[u for u in units.values() if u['actor']=='agent' and u['kind']=='semantic'];counts=Counter(u['activity'] for u in prose);result['activity_counts']=dict(counts)
    for activity in ['plan','verify']:
        m['activity_'+activity+'_share']=measurement(numerator=counts[activity],denominator=len(prose),evidence=[u['id'] for u in prose if u['activity']==activity])
    apply_agent_activity_measures(result,units.values())
    history=d.get('work_history',{});hc=history.get('counts',{})
    if history.get('available'):
        m['recurring_target_fraction']=measurement(numerator=hc['recurring_assignments'],denominator=hc['operations'],evidence=[r['unit_id'] for r in history['recurrences']])
        m['identity_unresolved_fraction']=measurement(numerator=hc['unresolved_or_uninspected'],denominator=hc['operations'])
    stages={(u['id'],s['id']) for u in prose for s in u.get('plan_structure',{}).get('steps',[])}
    attempts={(r['to'],r['plan_step_id']) for r in d['relations'] if r['type']=='attempts_plan_step' and r.get('plan_step_id') and units[r['from']]['kind']=='action'}&stages
    m['plan_stage_attempt_fraction']=measurement(numerator=len(attempts),denominator=len(stages),evidence=[p+':'+s for p,s in sorted(attempts)])
    if 'plan_relation_review' in d:
        from .plan_execution import build as project_plans
        plans=project_plans(run,d)['plans']
        if plans:
            transitions=[t for p in plans for t in p['stage_transitions'] if t['order_status']=='source_order']
            for name,selected in [('plan_stage_change_count',transitions),('plan_stage_reentry_count',[t for t in transitions if t['reentry']])]:
                m[name]=measurement(len(selected),evidence=[t['to_action_event_id'] for t in selected])
        if d.get('plan_stage_material'):
            from .plan_stage_material import pairs
            rows=d['plan_stage_material']['observations'];observed={(r['plan_unit_id'],r['stage_id']) for r in rows if r['form']=='contents'}&stages
            m['plan_stage_material_coverage']=measurement(numerator=len(rows),denominator=len(pairs(run,d)),evidence=[r['response_event_id'] for r in rows])
            m['plan_stages_with_contents_fraction']=measurement(numerator=len(observed),denominator=len(stages),evidence=[p+':'+s for p,s in sorted(observed)])
    reports=d.get('execution_reports')
    if reports:
        from .execution_reports import bound_responses, VERSION as EXECUTION_VERSION
        if reports.get('schema')!=EXECUTION_VERSION or reports.get('source_hash')!=digest(run):
            raise InputError('Metric execution report source/version differs')
        bindings={f['id']:a['id'] for a,f in bound_responses(run)};eligible=set(bindings)
        rows=reports['observations'];seen={r['response_event_id'] for r in rows}
        if len(seen)!=len(rows) or not seen<=eligible or any(bindings[r['response_event_id']]!=r['action_event_id'] for r in rows):
            raise InputError('Duplicate or unbound execution observations')
        m['execution_report_coverage']=measurement(numerator=len(rows),denominator=len(eligible),evidence=sorted(seen))
        for axis in ('error','warning'):
            known=[r for r in rows if r[axis]=='reported' or r[axis]=='not_reported' and r['complete_readable_response']]
            positive=[r['response_event_id'] for r in known if r[axis]=='reported']
            m['execution_'+axis+'_report_fraction']=measurement(numerator=len(positive),denominator=len(known),evidence=positive,
                reason='Decidable responses only; absence of a report is not successful execution.')
            if axis=='error':
                unknown=eligible-{r['response_event_id'] for r in known}
                m['execution_error_unknown_fraction']=measurement(numerator=len(unknown),denominator=len(eligible),evidence=sorted(unknown))
        returns=sorted({r['from'] for r in d.get('execution_returns',[])})
        m['target_revisit_after_error_count']=measurement(len(returns),evidence=returns)
    if d.get('operation_outcomes'):
        apply_operation_metrics(run,m,d['operation_outcomes'])
        completed=sorted({r['from'] for r in d.get('operation_transitions',[])})
        m['completed_after_failed_call_count']=measurement(len(completed),evidence=completed)
    from .retry_metrics import inspect as inspect_retries
    retry=inspect_retries(run,d)
    if retry:
        result['retry_observation']=retry
        for name,params in retry['metrics'].items():m[name]=measurement(**params)
    from .revision_metrics import inspect as inspect_revisions
    revision=inspect_revisions(run,d)
    if revision:
        result['revision_observation']=revision
        for name,params in revision['metrics'].items():m[name]=measurement(**params)
    if d.get('adjustment_graph'):
        graph=d['adjustment_graph'];result['linked_adjustment_observation']=graph
        for name,params in graph['metrics'].items():m[name]=measurement(**params)
    result['scope']='Selected semantic map scope; annotation coverage is not accuracy. Observer versions must be compared consistently.'
    return result


def apply_operation_metrics(run,metrics,observed):
    from .operation_outcomes import action_outcomes,bound_responses
    aggregates=action_outcomes(run,observed)
    pairs={(a['id'],r['id']) for a,r in bound_responses(run)};eligible={a for a,r in pairs}
    terminal={a:v for a,v in aggregates.items() if v['outcome'] in {'completed','failed','partial'}}
    failed=sorted(a for a,v in terminal.items() if v['outcome']=='failed')
    unknown=sorted(eligible-{a for a,v in aggregates.items() if v['outcome']!='not_established'})
    metrics['operation_outcome_coverage']=measurement(numerator=len(observed['observations']),denominator=len(pairs),evidence=[r['response_event_id'] for r in observed['observations']])
    metrics['operation_failed_fraction']=measurement(numerator=len(failed),denominator=len(terminal),evidence=failed)
    metrics['operation_unknown_fraction']=measurement(numerator=len(unknown),denominator=len(eligible),evidence=unknown)


def operation_record(run,protocol,result,observation_id):
    record=source_record(run)
    record.update(observer=protocol['id'],observer_label='Operation outcomes · '+protocol['outcome_harness'],
        observation_kind='operations',annotation_hash=digest(result),operation_observation_id=observation_id,
        protocol=protocol,scope=protocol['scope'])
    apply_operation_metrics(run,record['metrics'],result)
    # No base semantic map/identity was selected by this pass. A zero would
    # incorrectly claim inspection of cross-call target correspondence.
    record['metrics']['completed_after_failed_call_count']=measurement(reason='Requires separately selected semantic target identity and recurrence')
    return record


def save(connection,record,*,created_at=None):
    key=digest(record)
    if created_at is None:
        timestamp=datetime.now(timezone.utc)
        previous=connection.execute('SELECT created_at FROM rollout_measurements WHERE run_id=? AND observer=? ORDER BY created_at DESC LIMIT 1',
            (record['run_id'],record['observer'])).fetchone()
        if previous:
            # Windows wall-clock precision can give successive observations an
            # identical timestamp. Hash order is not observation order. Keep
            # new observations strictly ordered; migrations retain their
            # explicitly supplied original timestamp below.
            timestamp=max(timestamp,datetime.fromisoformat(previous[0])+timedelta(microseconds=1))
        created_at=timestamp.isoformat()
    connection.execute('INSERT OR IGNORE INTO rollout_measurements VALUES (?,?,?,?,?)',(key,record['run_id'],record['observer'],dumps(record),created_at))
    return key


def record_map(store,run,bundle):
    value=semantic_record(run,bundle)
    from .graph_store import build as build_graph, save as save_graph
    graph=build_graph(run,bundle)
    value['graph_id']=graph['id']
    with store.connect() as c:
        # Derived view metadata can change the graph snapshot without changing
        # this semantic observation. Keep its first exact binding so a harmless
        # projection rebuild does not duplicate the per-rollout metric record.
        for prior in c.execute('SELECT document FROM rollout_measurements WHERE run_id=? AND observer=? ORDER BY created_at',
                               (run['id'],value['observer'])):
            old=json.loads(prior[0])
            if old.get('graph_id') and {k:v for k,v in old.items() if k!='graph_id'}=={k:v for k,v in value.items() if k!='graph_id'}:
                value['graph_id']=old['graph_id'];break
        save(c,value)
        save_graph(c,graph)
    return value


def apply_agent_activity_measures(record, units):
    """Source form and semantic activity are orthogonal; tools can Verify too.

    Keep legacy prose-only counters unchanged. Unlabeled historical actions are
    excluded, rather than treated as non-verification. No unit is relabeled here.
    """
    selected=[u for u in units if u.get('actor')=='agent' and u.get('kind') in {'semantic','action'}
              and isinstance(u.get('activity'),str) and u['activity']]
    record['agent_activity_counts']=dict(Counter(u['activity'] for u in selected))
    record['agent_activity_scope']='Saved labeled agent prose and action units; environment/user units and unlabeled units excluded. Unresolved labels retained. Frequency, not time or effort.'
    for activity in ('plan','verify'):
        evidence=[u['id'] for u in selected if u['activity']==activity]
        record['metrics']['agent_'+activity+'_unit_share']=measurement(
            numerator=len(evidence),denominator=len(selected),evidence=evidence)


def ensure_current(store):
    """Append compatible metric extensions before any dashboard reads them.

    This consumes immutable saved inputs, never an inference provider. Older
    observations and their exact graph/annotation identities remain retained.
    """
    compatible=tuple('rollout-behavior/'+str(v) for v in range(6,20))
    with store.connect() as c:
        before=c.total_changes
        # Most source values are unchanged. Recompute only traces with attached
        # producer reward sources or recorded sessions whose native links changed.
        current_sources={r[0] for r in c.execute("SELECT run_id FROM rollout_measurements WHERE observer='source' AND json_extract(document,'$.schema')=?",(VERSION,))}
        for row in c.execute("""SELECT m.document,m.created_at,CASE WHEN EXISTS
            (SELECT 1 FROM json_each(r.document,'$.sources') s WHERE json_extract(s.value,'$.kind') IN ('harbor_trial_result','swe_rl_grading')) OR json_extract(r.document,'$.adapter') IN ('environment-episode','generation','tau-bench')
            OR json_extract(r.document,'$.raw.reward_evaluation') IS NOT NULL OR json_extract(r.document,'$.raw.healthbench_rubric_items') IS NOT NULL
            OR EXISTS (SELECT 1 FROM json_each(r.document,'$.events') e WHERE json_type(e.value,'$.reported_tool_error') IS NOT NULL)
            OR EXISTS (SELECT 1 FROM json_each(r.document,'$.events') e WHERE json_extract(e.value,'$.context_id') IS NOT NULL)
            THEN r.document END source_document FROM rollout_measurements m JOIN runs r ON r.id=m.run_id
            WHERE m.observer='source' AND json_extract(m.document,'$.schema') IN ('rollout-behavior/13','rollout-behavior/14','rollout-behavior/15','rollout-behavior/16','rollout-behavior/17','rollout-behavior/18','rollout-behavior/19')
            AND NOT EXISTS (SELECT 1 FROM rollout_measurements current WHERE current.run_id=m.run_id AND current.observer='source'
              AND json_extract(current.document,'$.schema')=?)
            ORDER BY json_extract(m.document,'$.schema') DESC,m.created_at DESC""",(VERSION,)).fetchall():
            record=json.loads(row['document'])
            if record['run_id'] not in current_sources:
                if row['source_document']:
                    run=json.loads(row['source_document']);record=source_record(run)
                    if any(e.get('context_id') is not None for e in run['events']):
                        from .graph_store import build as build_graph, save as save_graph
                        save_graph(c,build_graph(run))
                for key,params in environment_measures({}).items():record['metrics'].setdefault(key,measurement(**params))
                for key in REWARD_DEFINITIONS:record['metrics'].setdefault(key,measurement(reason='No recognized evaluator feedback'))
                for key in ('agent_verify_unit_share','agent_plan_unit_share'):
                    record['metrics'].setdefault(key,measurement(reason='No complete semantic observation'))
                record['schema']=VERSION;save(c,record,created_at=row['created_at'])
                current_sources.add(record['run_id'])
        present={r[0] for r in c.execute("SELECT run_id FROM rollout_measurements WHERE observer='source' AND json_extract(document,'$.schema')=?",(VERSION,))}
        legacy=c.execute("SELECT document,created_at FROM rollout_measurements WHERE observer!='source' AND json_extract(document,'$.schema') IN ("+','.join('?' for _ in compatible)+') ORDER BY created_at,id',compatible).fetchall()
        records=[json.loads(r[0]) for r in legacy]
        required={r['run_id'] for r in records}
        missing={r[0] for r in c.execute('SELECT id FROM runs')}-present
        required.update(missing)
        # Source documents can be large. Only fetch runs that actually need an
        # extension, instead of re-reading every training rollout on each sync.
        raw={}
        for rid in required:
            row=c.execute('SELECT document FROM runs WHERE id=?',(rid,)).fetchone()
            if row:raw[rid]=json.loads(row[0])
        source_records={run['id']:source_record(run) for run in raw.values()}
        for rid in missing:
            if rid in source_records:save(c,source_records[rid])
        for record,saved in zip(records,legacy):
            run=raw.get(record['run_id'])
            if run and record['source_hash']==digest(run):
                record['schema']=VERSION
                source=source_records[run['id']]
                for name,metric in source['metrics'].items():
                    if name in REWARD_DEFINITIONS or name in ENVIRONMENT_DEFINITIONS or name in {'feedback_link_rate','exact_dispatch_repeat_rate'}:record['metrics'][name]=metric
                    else:record['metrics'].setdefault(name,metric)
                record['metrics']['recorded_reward']=source['metrics']['recorded_reward']
                record['reward_inspection_protocol']=source['reward_inspection_protocol']
                if record.get('retry_observation'):
                    from .retry_metrics import refresh as refresh_retries
                    record['retry_observation']=refresh_retries(run,record['retry_observation'])
                    for name,params in record['retry_observation']['metrics'].items():
                        record['metrics'][name]=measurement(**params)
                # Extend only from the immutable graph linked to this exact
                # measurement. Never use a newer observer graph to fill history.
                graph=c.execute('SELECT id FROM rollout_graphs WHERE id=? AND run_id=? AND observer=? AND source_hash=?',
                    (record.get('graph_id'),record['run_id'],record['observer'],record['source_hash'])).fetchone()
                if graph:
                    apply_agent_activity_measures(record,(json.loads(row[0])['properties'] for row in c.execute(
                        "SELECT document FROM graph_nodes WHERE graph_id=? AND kind='unit'",(graph['id'],))))
                # Migrating an older observation must not make it newer than a
                # subsequently measured result for this observer.
                save(c,record,created_at=saved['created_at'])
        return c.total_changes-before


def report(store):
    # Latest producer revisions only; old snapshots and observer versions stay stored.
    ensure_current(store)
    latest=store.list();by_id={r['id']:r for r in latest};rows=[]
    with store.connect() as c:
        raw={r['id']:json.loads(r['document']) for r in c.execute('SELECT id,document FROM runs') if r['id'] in by_id}
        stored=c.execute('SELECT * FROM rollout_measurements ORDER BY created_at,id').fetchall()
    for saved in stored:
        if saved['run_id'] not in by_id:continue
        record=json.loads(saved['document']);summary=by_id[saved['run_id']]
        if record['schema']!=VERSION or record['source_hash']!=digest(raw[record['run_id']]):continue
        # Newly available optional observers do not retroactively measure old
        # observations. Extend the read projection with explicit missingness.
        for name in TOOL_CONTRACT_DEFINITIONS:
            record['metrics'].setdefault(name,measurement(reason='Parameter-schema observer has not measured this snapshot'))
        ingestion=summary.get('ingestion');record.update(measurement_id=saved['id'],imported_at=summary['imported_at'],ingestion=ingestion)
        record['rollout_id']=ingestion['rollout_id'] if ingestion else record['run_id']
        record['snapshot_state']=ingestion['state'] if ingestion else 'imported_snapshot'
        rows.append(record)
    value={'schema':VERSION,'grain':'one rollout snapshot per observer/annotation version','rollouts':len(latest),
           'definitions':{k:{'label':v[0],'definition':v[1],'aggregation':metric_aggregation(k)} for k,v in DEFINITIONS.items()},'rows':rows,
           'training_coordinate_count':sum(isinstance(r['metadata'].get('training_step'),int) and not isinstance(r['metadata'].get('training_step'),bool) and bool(r['metadata'].get('experiment')) for r in latest),
           'limits':['Import time is not training time. No missing training step is inferred.',
                     'Semantic measurements cover selected saved maps, not unattended annotation of every rollout.',
                     'Source-reported success and selected semantic labels are not independent validation.']}
    from .diagnostic_worker import report as worker_report
    value['diagnostic_monitoring']=worker_report(store)
    value['report_hash']=digest(value);return value


def training_series(report,metric,*,observer='source',bin_width=1):
    if metric not in DEFINITIONS:raise InputError('Unknown rollout metric')
    if isinstance(bin_width,bool) or not isinstance(bin_width,int) or not 1<=bin_width<=1000000:raise InputError('Invalid training bin width')
    candidates=[r for r in report['rows'] if r['observer']==observer]
    multiplicities=Counter(r['run_id'] for r in candidates);cohorts=defaultdict(list);excluded=Counter();unknown_bins=Counter()
    for r in candidates:
        meta=r['metadata'];step=meta.get('training_step');m=r['metrics'][metric]
        if multiplicities[r['run_id']]!=1:excluded['multiple_annotation_versions']+=1;continue
        if not isinstance(step,int) or isinstance(step,bool) or step<0 or not meta.get('experiment'):excluded['missing_training_coordinates']+=1;continue
        if r.get('snapshot_state') in {'in_progress','failed'}:excluded['incomplete_snapshot']+=1;continue
        key=dumps({k:meta.get(k) for k in ('experiment','environment','environment_version','split','task_revision','sampling','training_step_basis','reward_definition','source_selection','training_inclusion')}|{'adapter_version':r['adapter_version'],'observer':observer,'metric_version':VERSION,'reward_inspection_protocol':r.get('reward_inspection_protocol') if metric in REWARD_DEFINITIONS else None})
        if m['value'] is None:
            excluded['metric_unavailable']+=1;unknown_bins[(key,step//bin_width*bin_width)]+=1;continue
        cohorts[key].append({'run_id':r['run_id'],'rollout_id':r['rollout_id'],'training_step':step,'value':m['value'],
                            'numerator':m['numerator'],'denominator':m['denominator'],'measurement_id':r['measurement_id'],
                            'task_id':meta.get('task_id'),'policy_version':meta.get('policy_version') or meta.get('checkpoint')})
    def quantile(values,p):
        x=(len(values)-1)*p;lo=int(x);hi=min(lo+1,len(values)-1);return values[lo]+(values[hi]-values[lo])*(x-lo)
    result=[]
    for cohort,points in sorted(cohorts.items()):
        bins=defaultdict(list)
        for p in points:bins[p['training_step']//bin_width*bin_width].append(p)
        summaries=[]
        for step,items in sorted(bins.items()):
            values=sorted(p['value'] for p in items)
            summaries.append({'start':step,'end':step+bin_width-1,'n':len(items),'mean':sum(values)/len(values),'unknown':unknown_bins[(cohort,step)],'positive':sum(v==1 for v in values) if metric_aggregation(metric)=='incidence' else None,'median':quantile(values,.5),'p10':quantile(values,.1),'p90':quantile(values,.9),'tasks':dict(Counter(p['task_id'] or '[missing]' for p in items))})
        result.append({'cohort':json.loads(cohort),'points':sorted(points,key=lambda p:(p['training_step'],p['run_id'])),'bins':summaries})
    return {'metric':metric,'definition':DEFINITIONS[metric][1],'aggregation':metric_aggregation(metric),'bin_width':bin_width,'cohorts':result,'excluded':dict(excluded),
            'unknown_bins':[{'cohort':json.loads(key),'start':step,'unknown':count} for (key,step),count in sorted(unknown_bins.items())],
            'interpretation':'Each dot is a rollout. Indicator bin means are incidence among decidable inspected rollouts; unknowns are excluded and counted separately. Other bins summarize rollout distributions, not pooled action ratios. Task mix can change; no causal training improvement is inferred.'}


def metric_view(report,metric):
    """Small UI response; the full immutable-value export remains available."""
    if metric not in DEFINITIONS:raise InputError('Unknown rollout metric')
    value={**report,'projection_metric':metric,
           'rows':[{**r,'metrics':{metric:r['metrics'][metric]}} for r in report['rows']]}
    value['projection_hash']=digest(value)
    return value
