"""Explicit portable source contracts, independent of trainers and task domains.

These are tracker envelopes around supplied data, not claims of native framework
support. Evaluator fields and environment info stay outside agent-visible events.
"""
from copy import deepcopy
import math

from .schema import InputError, content_text, dumps, event, metadata
from . import environment_turns

FORMATS={'chat-messages':'chat-messages/1','environment-episode':'environment-episode/1','generation':'generation/1'}


def detect_record(doc):
    """Recognize a complete record shape, never guess text aliases or tool links."""
    candidates=[]
    if isinstance(doc.get('messages'),list) and doc['messages']:
        candidates.append('chat-messages')
    if 'prompt' in doc and 'completion' in doc:
        candidates.append('generation')
    if all(k in doc for k in ('input','output','step')):
        candidates.append('verl-generation')
    if len(candidates)>1:
        raise InputError('Ambiguous record shapes: '+', '.join(candidates)+'. Choose an explicit format.')
    return candidates[0] if candidates else None


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def outcome(document):
    value=document.get('outcome',{})
    if not isinstance(value,dict):raise InputError('outcome must be an object')
    result={}
    if 'reward' in value:
        if value['reward'] is not None and not finite(value['reward']):raise InputError('outcome.reward must be finite or null')
        result.update(recorded_reward=value['reward'],recorded_reward_pointer='/outcome/reward')
    if 'success' in value:
        if value['success'] is not None and type(value['success']) is not bool:raise InputError('outcome.success must be boolean or null')
        result['verified_success']=value['success']
    if 'termination' in value:
        if not isinstance(value['termination'],str):raise InputError('outcome.termination must be a string')
        result['termination']=value['termination']
    return result


def observation(value):
    if isinstance(value,str):return value,[]
    if isinstance(value,list) and all(isinstance(p,dict) and 'type' in p for p in value):
        return content_text(value)
    # Structured state is explicitly serialized, not interpreted as prose.
    try:return dumps(value),[]
    except (TypeError,ValueError) as e:raise InputError('Observations must be JSON; encode arrays and use explicit media references') from e


def append_events(doc,fmt,events,warnings,meta):
    turns = fmt == 'environment-episode' and doc.get('trajectory_format') == environment_turns.VERSION
    unmarked=fmt in {'chat-messages','generation'} and 'trajectory_format' not in doc
    if not turns and not unmarked and doc.get('trajectory_format')!=FORMATS[fmt]:raise InputError('Supply explicit trajectory_format '+FORMATS[fmt])
    if unmarked:
        warnings.append('Record shape decoded without a framework marker. This does not identify a trainer or establish that the captured history is complete. Reward and success use the explicit outcome object; other top-level fields remain in raw source.')
    declared=doc.get('metadata',{})
    if not isinstance(declared,dict):raise InputError('metadata must be an object')
    for key in ('training_step','training_step_basis','generation_step','learner_step','experiment','policy_version','checkpoint','task_id','sample_id','rollout_n','split','environment','environment_version'):
        if key in declared and key in meta and declared[key]!=meta[key]:raise InputError('Conflicting producer metadata: '+key)
    merged=metadata({**declared,**meta});meta.clear();meta.update(merged)
    for key in ('generation_step','learner_step','rollout_n'):
        if key in meta and (type(meta[key]) is not int or meta[key]<0):raise InputError(key+' must be a nonnegative integer')
    result=outcome(doc)
    if fmt=='generation':
        for key,kind,actor in [('prompt','context','context'),('completion','message','agent')]:
            if not isinstance(doc.get(key),str):raise InputError(key+' must be recorded text; token IDs require the matching tokenizer outside this adapter')
            event(events,kind=kind,actor=actor,text=doc[key],pointer='/'+key)
        meta.setdefault('environment','generation-export')
        warnings.append('Flat generation: internal turns and actions are unobserved. Text that looks like a tool call is not parsed into an execution. No training clock or task identity is inferred.')
        return result
    if fmt=='chat-messages':
        from .chat_messages import append_messages
        append_messages(doc,events,warnings,portable=True)
        meta.setdefault('environment','recorded-conversation')
        warnings.append('A supplied model conversation is not a complete simulator log. Additional agent histories must remain separate trajectories. Recorded tool results without native call IDs remain unlinked.')
        return result
    meta.setdefault('environment','recorded-environment')
    steps=doc.get('steps')
    if not isinstance(steps,list) or any(not isinstance(s,dict) for s in steps):raise InputError('steps must be a list of transition objects')
    if turns:
        environment_turns.validate(doc)
        if meta.get('episode_id', doc['episode_id']) != doc['episode_id']: raise InputError('Conflicting episode_id')
        meta['episode_id'] = doc['episode_id']
    initial=doc.get('initial')
    if initial is not None and (not isinstance(initial,dict) or 'observation' not in initial):raise InputError('initial requires an observation')
    goal=doc.get('goal')
    if goal is not None:
        if not isinstance(goal,str):raise InputError('goal must be explicitly supplied text')
        event(events,kind='instruction',actor='user',text=goal,pointer='/goal')
    if 'visible_context' in doc:
        text,media=observation(doc['visible_context'])
        event(events,kind='context',actor='context',text=text,media=media,pointer='/visible_context',context_kind='producer_declared_agent_visible')
    if initial is not None:
        text,media=observation(initial['observation'])
        event(events,kind='context',actor='environment',text=text,media=media,pointer='/initial/observation')
    ended=False
    for i,step in enumerate(steps):
        if ended:raise InputError('An episode cannot contain a step after an explicit ending; start a new episode')
        if 'action' not in step or 'observation' not in step:raise InputError('Each environment step requires action and observation')
        if not isinstance(step.get('reward'),type(None)) and not finite(step['reward']):raise InputError('Step reward must be finite or null')
        if 'done' in step and ('terminated' in step or 'truncated' in step):raise InputError('Use native done OR terminated/truncated; do not invent missing termination semantics')
        for field in ('done','terminated','truncated'):
            if field in step and type(step[field]) is not bool:raise InputError(field+' must be boolean')
        if ('terminated' in step)!=('truncated' in step):raise InputError('Gymnasium transitions need both terminated and truncated')
        ended=bool(step.get('done') or step.get('terminated') or step.get('truncated'))
        pointer=f'/steps/{i}';cid=f'env-step:{i}'
        action_fields, turn_fields = ({}, {})
        if turns:
            action_fields, turn_fields = environment_turns.append_response(
                events, step, pointer, episode_id=doc['episode_id'], index=i)
            cid = 'env-turn:' + step['turn_id']
        # This linkage comes from the recorded transition, not textual proximity.
        event(events,kind='action',actor='agent',text=dumps(step['action']),pointer=pointer+'/action',
            tool='environment.step',arguments={'action':step['action']},call_id=cid,**({'step_id':i}|action_fields))
        text,media=observation(step['observation'])
        event(events,kind='feedback',actor='environment',text=text,pointer=pointer+'/observation',media=media,
            source_call_id=cid,feedback_origin='environment',link_basis='recorded environment transition',**({'step_id':i}|turn_fields))
    if turns:
        warnings.append('Model responses are linked to their recorded dispatch, not to inferred intentions. Missing or empty responses remain unobserved semantic content; response text is never executed or parsed into an extra action.')
    warnings.append('Environment rewards, termination flags and info are retained separately from visible observations. An ended or truncated episode does not establish task success. Numeric state is recorded data, not inferred semantic activity.')
    if any(e.get('media') for e in events):warnings.append('Media references are retained but their pixels/audio have not been inspected.')
    return result


def chat_document(messages,*,metadata=None,tools=None,reward=None,success=None):
    """Wrap an explicit agent-visible message history; no framework import."""
    return deepcopy({'trajectory_format':'chat-messages/1','messages':messages,'tools':tools or [],
        'metadata':metadata or {},'outcome':{'reward':reward,'success':success}})


def generation_document(prompt,completion,*,metadata=None,reward=None):
    return deepcopy({'trajectory_format':'generation/1','prompt':prompt,'completion':completion,
        'metadata':metadata or {},'outcome':{'reward':reward}})


class Episode:
    """Record one environment instance/episode. Never intercept or execute steps."""
    def __init__(self,*,metadata=None,goal=None,visible_context=None,episode_id=None):
        self.document={'trajectory_format':'environment-episode/1' if episode_id is None else environment_turns.VERSION,'metadata':deepcopy(metadata or {}),'steps':[]}
        if episode_id is not None:self.document['episode_id']=environment_turns.identifier(episode_id, 'episode_id')
        if goal is not None:self.document['goal']=goal
        if visible_context is not None:self.document['visible_context']=json_value(visible_context)

    def reset(self,observation,info=None):
        if 'initial' in self.document or self.document['steps']:raise InputError('Create a new Episode for each reset')
        self.document['initial']=json_value({'observation':observation,'info':info})
        return self

    def _append(self,step,*,model_response=None,turn_id=None,response_id=None):
        if self.document['trajectory_format'] == environment_turns.VERSION:
            step['turn_id'] = turn_id if turn_id is not None else 'capture:'+str(len(self.document['steps']))
            step['turn_identity_basis'] = 'producer_id' if turn_id is not None else 'capture_sequence'
            if model_response is not None:step['model_response']=model_response
            if response_id is not None:step['response_id']=response_id
            proposed = {**self.document, 'steps':self.document['steps'] + [json_value(step)]}
            environment_turns.validate(proposed)
        elif any(v is not None for v in (model_response,turn_id,response_id)):
            raise InputError('Supply episode_id when creating Episode to retain model responses and turn identities')
        self.document['steps'].append(json_value(step))
        return self

    def gym_step(self,action,result,*,model_response=None,turn_id=None,response_id=None):
        if not isinstance(result,(tuple,list)) or len(result)!=5:raise InputError('Expected Gymnasium (observation, reward, terminated, truncated, info)')
        obs,reward,terminated,truncated,info=result
        return self._append(dict(action=action,observation=obs,reward=reward,terminated=terminated,truncated=truncated,info=info),
                            model_response=model_response,turn_id=turn_id,response_id=response_id)

    def openenv_step(self,action,result,*,model_response=None,turn_id=None,response_id=None):
        # Current OpenEnv returns an Observation object, not Gymnasium's tuple.
        if hasattr(result,'model_dump'):result=result.model_dump(mode='json')
        if hasattr(action,'model_dump'):action=action.model_dump(mode='json')
        if not isinstance(result,dict) or 'done' not in result:raise InputError('Expected OpenEnv Observation with done and optional reward')
        visible={k:v for k,v in result.items() if k not in {'reward','done','metadata'}}
        return self._append(dict(action=action,observation=visible,reward=result.get('reward'),done=result['done'],info={'metadata':result.get('metadata')}),
                            model_response=model_response,turn_id=turn_id,response_id=response_id)

    def step(self,action,observation,*,reward=None,done=None,info=None,model_response=None,turn_id=None,response_id=None):
        """Record an explicit native transition with an optional unsplit done flag.

        Supply the dispatched action, not an action parsed by this tracker. No
        terminated/truncated flags or success are inferred from done or reward.
        """
        step = dict(action=action,observation=observation,reward=reward,info=info)
        if done is not None:step['done']=done
        return self._append(step,model_response=model_response,turn_id=turn_id,response_id=response_id)

    def snapshot(self,*,reward=None,success=None):
        result=deepcopy(self.document);result['outcome']={'reward':reward,'success':success}
        return result


def json_value(value):
    """Copy JSON values and NumPy scalars without a NumPy runtime dependency.

    Arrays need an explicit producer projection: low-dimensional state can use
    tolist(), while screenshots should be stored as referenced media assets.
    """
    if type(value).__module__.startswith('numpy'):
        if getattr(value,'ndim',None)==0:return json_value(value.item())
        raise InputError('Project NumPy arrays explicitly: tolist() for state, media references for screenshots')
    if isinstance(value,dict):return {k:json_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_value(v) for v in value]
    if value is None or isinstance(value,(str,bool,int)) or finite(value):return value
    raise InputError('Capture values must be finite JSON data; project framework objects explicitly')
