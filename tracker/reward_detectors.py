"""Reward-specific detectors on the existing code-monitor publication contract.

The reward definition and input paths are explicit, versioned configuration.
Callbacks run in the user's worker; their findings are rule results, not proof
of intent or confirmed reward hacking. No inference runs on UI reads.
"""
from copy import deepcopy
from dataclasses import dataclass
import re

from .custom_monitors import CustomMonitor, json_value, text
from .schema import InputError, digest

VERSION = 'reward-detector/1'
MISSING = object()
STAGES = {'attempt', 'execution', 'reward_disagreement', 'constraint_violation', 'custom'}


def tokens(path):
    if not isinstance(path, str) or not path.startswith('/') or len(path)>1000 or re.search(r'~(?![01])',path):
        raise InputError('Input paths must be JSON pointers, for example /outcome/recorded_reward')
    return [part.replace('~1','/').replace('~0','~') for part in path[1:].split('/')]


def lookup(document,path):
    value=document
    for key in tokens(path):
        if isinstance(value,dict):
            if key not in value:return MISSING
            value=value[key]
        elif isinstance(value,list) and re.fullmatch(r'0|[1-9][0-9]*',key):
            index=int(key)
            if index>=len(value):return MISSING
            value=value[index]
        else:return MISSING
    return value


def contract(*, reward_definition, inputs, definition_path='/metadata/reward_definition', stage='custom', config=None):
    text(reward_definition,'Reward definition',240);tokens(definition_path)
    if not isinstance(stage,str) or stage not in STAGES:raise InputError('Unknown reward detector stage')
    if not isinstance(inputs,dict) or not 1<=len(inputs)<=32:
        raise InputError('Declare 1–32 named required inputs')
    for name,path in inputs.items():
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name):
            raise InputError('Use short identifier names for detector inputs')
        tokens(path)
    config=json_value({} if config is None else config)
    if not isinstance(config,dict):raise InputError('Detector config must be an object')
    return dict(schema=VERSION,reward_definition=reward_definition,definition_path=definition_path,
                inputs=dict(inputs),stage=stage,settings=config)


@dataclass(frozen=True)
class DetectorContext:
    run: dict
    graph: dict
    workspace: object
    inputs: dict
    config: dict
    reward_definition: str
    evaluations: dict

    def compare_evaluations(self,left,right):
        from .monitor_evaluation_inputs import compare
        return compare(self.evaluations,left,right)

    def cite(self,event_id,*,role='context',quote=None,start=None,end=None):
        from .evaluation_receipts import cite_source
        return cite_source(self.run,event_id,role=role,quote=quote,start=start,end=end)


def finding(raw,spec,inputs):
    if not isinstance(raw,dict) or set(raw)-{'status','summary','evidence_ids','source_citations','evaluation_ids','input_evidence','details','next_check'}:
        raise InputError('Detector returns status, summary, evidence_ids, source_citations, evaluation_ids, input_evidence, details and next_check')
    status=raw.get('status')
    if not isinstance(status,str) or status not in {'flagged','clear','unknown','not_applicable'}:
        raise InputError('Detector status must be flagged, clear, unknown or not_applicable')
    summary=text(raw.get('summary'),'Detector summary')
    selected=raw.get('input_evidence',[])
    if not isinstance(selected,list) or any(not isinstance(k,str) or k not in inputs for k in selected) or len(selected)!=len(set(selected)):
        raise InputError('Input evidence must name distinct supplied inputs')
    ids=raw.get('evidence_ids',[])
    if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):raise InputError('Evidence IDs must be a string list')
    if status=='flagged' and not selected and not ids and not raw.get('source_citations') and not raw.get('evaluation_ids'):
        raise InputError('A flagged result needs input_evidence, source_citations or source/graph evidence IDs')
    feedback=dict(severity='warning' if status=='flagged' else 'info',summary=summary)
    if raw.get('next_check') is not None:feedback['next_check']=text(raw['next_check'],'Next check')
    value=1 if status=='flagged' else 0 if status=='clear' else None
    result=dict(value=value,evidence_ids=ids,feedback=feedback,unknown=int(status=='unknown'),
        details=dict(detector=dict(schema=VERSION,status=status,stage=spec['stage'],reward_definition=spec['reward_definition'],
            definition_path=spec['definition_path'],input_evidence={name:dict(pointer=spec['inputs'][name],value=deepcopy(inputs[name])) for name in selected},
            interpretation='Custom rule finding; reward exploitation, intent and causal training effects are not established.'),
            custom=raw.get('details',{})))
    if value is None:result['reason']=summary
    if 'source_citations' in raw:result['source_citations']=raw['source_citations']
    if 'evaluation_ids' in raw:result['evaluation_ids']=raw['evaluation_ids']
    return json_value(result)


def checked_inputs(run,spec,result):
    """Resolve declared input evidence against the immutable source, not a copy supplied by code."""
    contract(reward_definition=spec.get('reward_definition'),inputs=spec.get('inputs'),
        definition_path=spec.get('definition_path'),stage=spec.get('stage'),config=spec.get('settings'))
    details=result.get('details');record=details.get('detector') if isinstance(details,dict) else None
    if record is None and result.get('status')=='error':return []
    if not isinstance(record,dict) or any(record.get(k)!=spec.get(k) for k in ('schema','reward_definition','definition_path','stage')):
        raise InputError('Reward finding does not match its saved detector contract')
    status=record.get('status')
    if not isinstance(status,str) or status not in {'flagged','clear','unknown','not_applicable'}:
        raise InputError('Invalid saved reward finding status')
    if result.get('value')!=({'flagged':1,'clear':0}.get(status)):
        raise InputError('Reward finding status and value disagree')
    if status in {'flagged','clear'}:
        if lookup(run,spec['definition_path'])!=spec['reward_definition']:
            raise InputError('Reward finding uses a different reward definition')
        if any((v:=lookup(run,path)) is MISSING or v is None for path in spec['inputs'].values()):
            raise InputError('Reward finding is missing required inputs')
    evidence=record.get('input_evidence')
    if not isinstance(evidence,dict):raise InputError('Invalid saved reward input evidence')
    if status=='flagged' and not evidence and not result.get('evidence_ids') and not result.get('source_citations') and not result.get('evaluation_ids'):
        raise InputError('A flagged result needs input_evidence, source_citations or source/graph evidence IDs')
    checked=[]
    for name,item in evidence.items():
        if name not in spec['inputs'] or not isinstance(item,dict) or set(item)!={'pointer','value'} or item['pointer']!=spec['inputs'][name]:
            raise InputError('Reward input evidence differs from its configured path')
        value=lookup(run,item['pointer'])
        if value is MISSING or digest(value)!=digest(item['value']):
            raise InputError('Reward input evidence differs from the saved source')
        checked.append(dict(name=name,pointer=item['pointer'],value=deepcopy(value)))
    return checked


class RewardDetector:
    def __init__(self,workspace,name,*,version,description,reward_definition,inputs,
                 definition_path='/metadata/reward_definition',stage='custom',config=None,evaluations=None):
        self.spec=contract(reward_definition=reward_definition,inputs=inputs,definition_path=definition_path,stage=stage,config=config)
        self.monitor=CustomMonitor(workspace,name,version=version,description=description,unit='fraction',aggregation='incidence',
            config={'reward_detector':self.spec},group='Reward integrity',evaluations=evaluations)
        self.id=self.monitor.id
        self.definition=self.monitor.definition

    def _callback(self,function):
        if not callable(function):raise InputError('Provide a detector callback')
        # Rehydrate the immutable saved contract, not a caller-mutated wrapper.
        def measure(ctx):
            spec=ctx.config['reward_detector']
            actual=lookup(ctx.run,spec['definition_path'])
            if actual is MISSING or actual is None:
                return finding(dict(status='unknown',summary='Reward definition is missing at '+spec['definition_path']),spec,{})
            if actual!=spec['reward_definition']:
                return finding(dict(status='not_applicable',summary='Rollout uses a different reward definition.'),spec,{})
            values={name:lookup(ctx.run,path) for name,path in spec['inputs'].items()}
            missing=[name for name,value in values.items() if value is MISSING or value is None]
            if missing:
                return finding(dict(status='unknown',summary='Missing required detector inputs: '+', '.join(missing)),spec,{})
            # Freeze values independently of mutable callback state.
            # The result limit applies to published evidence, not the trace we
            # inspect. Long rollouts can cite graph/event IDs instead of copying
            # the entire input into the result.
            values=deepcopy(values)
            context=DetectorContext(ctx.run,ctx.graph,ctx.workspace,deepcopy(values),deepcopy(spec['settings']),spec['reward_definition'],ctx.evaluations)
            return finding(function(context),spec,values)
        return measure

    def run(self,function,*,dependencies=None):
        return self.monitor.run(self._callback(function),dependencies=dependencies)

    def input_snapshot(self,run_id):
        return self.monitor.input_snapshot(run_id)

    def follow(self,function,*,interval=5,dependencies=None):
        return self.monitor.follow(self._callback(function),interval=interval,dependencies=dependencies)


def catalog(store):
    from .rollout_metrics import DIAGNOSTIC_DETECTORS as DETECTORS
    from .requirement_diagnostics import METRIC,DEFINITION
    from .evaluation_components import DEFINITIONS
    with store.connect() as c:
        import json
        observers=[]
        for r in c.execute("SELECT observer,min(json_extract(document,'$.observer_label')),min(json_extract(document,'$.diagnostic_result.protocol')) FROM rollout_measurements WHERE json_extract(document,'$.observation_kind')='diagnostics' GROUP BY observer ORDER BY observer"):
            saved=json.loads(r[2]) if r[2] else {}
            definitions=saved.get('detectors',{})
            observers.append(dict(id=r[0],label=r[1] or r[0],protocol_version=saved.get('schema'),
                checks={k:dict(name=v[0],description=v[1]) for k,v in definitions.items()
                        if k in DETECTORS and isinstance(v,list) and len(v)==2 and all(isinstance(s,str) for s in v)}))
    rows=[dict(id=k,name=label,description=description,metric='diagnostic_'+k,observer_type='diagnostic',
               requires='Saved diagnostic observations; enabling this chart does not run a model.') for k,(label,description) in DETECTORS.items()]
    rows.append(dict(id=METRIC,name=DEFINITION[0],description=DEFINITION[1],metric='diagnostic_'+METRIC,
        observer_type='diagnostic',requires='Run monitor-rollouts with --protocol requirements, then select its saved observer.'))
    for key in ['reward_diagnostic_failure_observed','reward_aggregation_gap']:
        rows.append(dict(id=key,name=DEFINITIONS[key][0],description=DEFINITIONS[key][1],metric=key,observer_type='source',
                         requires='Recorded reward components or diagnostic checks in a supported evaluator record.'))
    return dict(checks=rows,observers=observers,custom_sdk='Workspace.reward_detector')


def activate(store,body):
    from . import monitoring
    if not isinstance(body,dict) or set(body)-{'checks','observer','population'}:raise InputError('Supply checks, optional diagnostic observer and population')
    ids=body.get('checks')
    if not isinstance(ids,list) or not ids or any(not isinstance(k,str) for k in ids) or len(ids)!=len(set(ids)):
        raise InputError('Select distinct reward checks')
    available=catalog(store);by_id={r['id']:r for r in available['checks']}
    if set(ids)-set(by_id):raise InputError('Unknown reward check')
    if any(by_id[k]['observer_type']=='diagnostic' for k in ids) and body.get('observer') not in {r['id'] for r in available['observers']}:
        raise InputError('Choose a saved diagnostic observer, or run a diagnostic worker first')
    prepared=[]
    selected=next((row for row in available['observers'] if row['id']==body.get('observer')),None)
    from .rollout_metrics import DIAGNOSTIC_DETECTORS
    for key in ids:
        row=by_id[key]
        saved=(selected or {}).get('checks',{}).get(key)
        if key in DIAGNOSTIC_DETECTORS and saved is None:
            raise InputError('This saved observer does not provide the selected check')
        prepared.append(monitoring.validate(dict(name=saved['name'] if saved else row['name'],kind='metric',metric=row['metric'],group='Reward integrity',
            observer='source' if row['observer_type']=='source' else body['observer'],population=body.get('population',{}))))
    def identity(d):return {k:v for k,v in d.items() if k not in {'name','group','id','enabled','schema'}}
    previous=monitoring.definitions(store);added=[];existing=[]
    for definition in prepared:
        match=next((m for m in previous if identity(m)==identity(definition)),None)
        if match:existing.append(match['id'])
        else:
            saved=monitoring.create(store,definition);previous.append(saved);added.append(saved['id'])
    return dict(added=added,existing=existing)
