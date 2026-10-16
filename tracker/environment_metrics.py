"""Recorded transition measures. Terminal and truncated never mean success."""
import math

DEFINITIONS={
 'environment_steps':('Recorded environment steps','Number of explicit action/observation transition records; not token turns or inferred activities.'),
 'environment_episode_return':('Recorded episode return','Undiscounted sum of step rewards only when reset, ending and every finite step reward are recorded. Not the training reward unless the producer defines it that way.'),
 'environment_terminated':('Environment termination reported','Final native Gymnasium terminated flag. OpenEnv done cannot establish termination versus truncation.'),
 'environment_truncated':('Environment truncation reported','Final native Gymnasium truncated flag; does not imply task failure or a specific timeout cause.'),
 'environment_done':('Episode ending reported','Native OpenEnv done, or Gymnasium terminated OR truncated. An ending is not task success.'),
 'environment_model_response_fraction':('Turns with model text','Environment turns with a nonempty recorded model response / captured turns in environment-episode/2. Capture coverage, not semantic annotation or correctness. Legacy episode exports leave this unavailable.'),
 'environment_tool_error_fraction':('Tool responses flagged as errors','Source-linked agent responses with an explicit true tool-error flag / responses with an explicit boolean flag. A false flag does not establish task success or a correct result. User-side actions are excluded.'),
 'environment_tool_error_coverage':('Tool error flag coverage','Source-linked agent responses with an explicit boolean tool-error flag / all source-linked agent responses. Missing flags are not silently treated as false.'),
}


def measures(run):
    missing={key:{'value':None,'reason':'No explicit environment-episode transition contract'} for key in DEFINITIONS}
    from .capabilities import links
    records=links(run)['records'] if run.get('events') else []
    actions={e['id'] for e in run.get('events',[]) if e.get('actor')=='agent' and e['kind']=='action'}
    ids={row['feedback_id'] for row in records if row['action_id'] in actions}
    responses=[e for e in run.get('events',[]) if e['id'] in ids and not e.get('copied_context')]
    known=[e for e in responses if type(e.get('reported_tool_error')) is bool]
    errors=[e for e in known if e['reported_tool_error']]
    missing['environment_tool_error_fraction']={'numerator':len(errors),'denominator':len(known),
        'evidence':[e['id'] for e in errors or known],'reason':'No explicit native tool-error flags' if not known else None}
    missing['environment_tool_error_coverage']={'numerator':len(known),'denominator':len(responses),
        'evidence':[e['id'] for e in known],'reason':'No source-linked agent responses' if not responses else None}
    if run.get('adapter')!='environment-episode':return missing
    doc=run['raw'];steps=doc['steps'];last=steps[-1] if steps else {}
    result={'environment_steps':{'value':len(steps),'evidence':[f'/steps/{i}/action' for i in range(len(steps))]}}
    if doc.get('trajectory_format') == 'environment-episode/2':
        present = [i for i,s in enumerate(steps) if s.get('model_response','').strip()]
        result['environment_model_response_fraction'] = {'numerator':len(present), 'denominator':len(steps),
            'evidence':[f'/steps/{i}' for i in range(len(steps))]}
    else:
        result['environment_model_response_fraction'] = {'value':None, 'reason':'This legacy episode contract does not record per-turn model responses'}
    for key in ('terminated','truncated'):
        known=type(last.get(key)) is bool
        result['environment_'+key]={'value':int(last[key]) if known else None,
            'evidence':[f'/steps/{len(steps)-1}/{key}'] if known else [],'reason':None if known else 'Native '+key+' flag is not recorded'}
    done=last.get('done') if 'done' in last else (last['terminated'] or last['truncated']) if 'terminated' in last and 'truncated' in last else None
    result['environment_done']={'value':int(done) if type(done) is bool else None,
        'evidence':[f'/steps/{len(steps)-1}'] if steps else [],'reason':None if done is not None else 'No explicit ending flag'}
    rewards=[s.get('reward') for s in steps]
    complete=bool(doc.get('initial') is not None and done is True and rewards and all(isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x) for x in rewards))
    total=None
    if complete:
        try:total=math.fsum(rewards)
        except OverflowError:pass
    result['environment_episode_return']={'value':total,
        'evidence':[f'/steps/{i}/reward' for i in range(len(steps))] if complete else [],
        'reason':None if total is not None else 'Episode return needs a recorded reset, ending and every step reward with a finite sum'}
    return {**missing,**result}
