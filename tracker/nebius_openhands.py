"""Native SWE-rebench OpenHands rows; conversation and evaluator stay separate."""
from .schema import InputError
from .chat_messages import append_messages

VERSION='nebius-openhands/1'


def matches(document):
    return (isinstance(document.get('trajectory_id'),str) and 'instance_id' in document
        and isinstance(document.get('trajectory'),list) and 'tools' in document and 'resolved' in document)


def append_events(document,events,warnings,meta):
    for key in ('trajectory_id','instance_id'):
        if not isinstance(document.get(key),str) or not document[key]:raise InputError('OpenHands dataset row requires '+key)
    resolved=document.get('resolved')
    if resolved is not None and (type(resolved) is not int or resolved not in (0,1)):
        raise InputError('OpenHands dataset resolved must be 0, 1 or null')
    # Parquet's common struct retains null optional fields. Keep raw rows intact;
    # interpret null tool_calls as absent only in this explicit native profile.
    append_messages(document,events,warnings,portable=True,message_field='trajectory',nullable_calls=True)
    meta.setdefault('task_id',document['instance_id'])
    meta.setdefault('sample_id',document['trajectory_id'])
    meta.setdefault('environment','swe-rebench-openhands')
    meta.setdefault('source_uri','https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories')
    warnings.append('Public OpenHands evaluation trajectories: dataset order is not a training step, and resolved is a producer-reported task result. No generating policy/checkpoint is inferred.')
    return {'termination':document.get('exit_status'),'verified_success':None if resolved is None else bool(resolved),
        'success_source_pointer':'/resolved','patch':document.get('model_patch'),
        'generated_test_evaluation':{k:document.get(k) for k in ('gen_tests_correct','pred_passes_gen_tests')}}
