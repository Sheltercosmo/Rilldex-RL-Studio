"""Immutable, reproducible researcher notes bound to a source comparison."""
from copy import deepcopy

from .schema import InputError, digest
from .source_study import compare

VERSION='source-investigation/2'


def build(study, request, episode_loader):
    if not isinstance(request,dict):raise InputError('Investigation needs a JSON object')
    allowed={'reference','checkpoint','metric','task_id','episode_ids','note','expected_comparison_id','view'}
    if set(request)-allowed:raise InputError('Unexpected investigation fields')
    if digest({k:v for k,v in study.items() if k!='id'})[:24]!=study['id']:
        raise InputError('Study identity differs from its evidence')
    reference,checkpoint=request.get('reference'),request.get('checkpoint')
    if not isinstance(reference,str) or not isinstance(checkpoint,str):
        raise InputError('Select two recorded policy checkpoints')
    comparison=compare(study,reference,checkpoint)
    if request.get('expected_comparison_id')!=comparison['comparison_id']:
        raise InputError('The comparison changed. Reload it before saving an investigation.')
    metric=request.get('metric')
    if not isinstance(metric,str) or metric not in study['metrics']:raise InputError('Unknown investigation metric')
    note=request.get('note','')
    if not isinstance(note,str) or len(note)>20000:raise InputError('Investigation note must be text of at most 20,000 characters')
    view=request.get('view',{'filter':'','direction':'all'})
    if (not isinstance(view,dict) or set(view)!={'filter','direction'}
            or not isinstance(view['filter'],str) or len(view['filter'])>2000
            or view['direction'] not in {'all','positive','negative','zero','unknown'}):
        raise InputError('Invalid investigation display filters')
    task_id=request.get('task_id')
    if task_id is not None and not isinstance(task_id,str):raise InputError('Invalid investigation task')
    task=next((t for t in comparison['tasks'] if t['task_id']==task_id),None)
    if task_id is not None and task is None:raise InputError('Selected game is outside this matched cohort')
    episode_ids=request.get('episode_ids',{})
    if not isinstance(episode_ids,dict) or set(episode_ids)-{'before','after'}:
        raise InputError('Invalid selected episode sides')
    if (task is None and episode_ids) or (task is not None and set(episode_ids)!={'before','after'}):
        raise InputError('Select both episode sides for a game, or no episodes for a cohort note')
    episodes={}
    for side,identifier in episode_ids.items():
        choices={row['id'] for row in task[side]['episodes']}
        if not isinstance(identifier,str) or identifier not in choices:
            raise InputError('Selected episode belongs to another game or policy')
        episode=episode_loader(identifier)
        if (digest(episode)!=study['episode_hashes'].get(identifier)
                or digest(episode['raw'])!=episode['source_hash']):
            raise InputError('Selected episode evidence changed')
        episodes[side]=deepcopy(episode)
    value={'version':VERSION,'study_id':study['id'],'comparison_id':comparison['comparison_id'],
           'measurement_pack':study['pack'],'provenance':deepcopy(study['provenance']),
           'selection':{'reference':reference,'checkpoint':checkpoint,'metric':metric,
                        'task_id':task_id,'episode_ids':deepcopy(episode_ids),'view':deepcopy(view)},
           'metric_definition':deepcopy(study['metrics'][metric]),
           'comparison':comparison,'selected_game':deepcopy(task),'episodes':episodes,
           'note':note,'annotation_status':'investigation_note_not_reference_label',
           'evidence_scope':'All matched game summaries and the explicitly selected raw episodes. Display filters do not change the comparison cohort.',
           'limitations':deepcopy(study['limitations'])}
    value['id']=digest(value)[:24]
    return value


def validate(value,identifier,study_id):
    if (value.get('version')!=VERSION or value.get('id')!=identifier
            or value.get('study_id')!=study_id
            or digest({k:v for k,v in value.items() if k!='id'})[:24]!=identifier):
        raise InputError('Saved investigation identity differs')
    return value
