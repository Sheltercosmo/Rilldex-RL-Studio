"""Read verl's flattened generation exports without inventing internal turns.

One physical JSONL record is one sampled completion. Identical completions at
different lines remain separate rollouts. Scores/ground truths never become
agent-visible events. The logged step is not a generating-policy identifier.
"""
import hashlib
import math

from .schema import InputError, event

VERSION = 'verl-generation/1'


def validate(row):
    if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ('input', 'output')):
        raise InputError('A verl generation record requires input and output strings')
    step = row.get('step')
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise InputError('A verl generation record requires an explicit nonnegative integer step')
    score = row.get('score')
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)):
        raise InputError('A logged score must be a finite number or null')


def append_events(row, events, meta):
    validate(row)
    if meta.get('training_step') is not None and meta['training_step'] != row['step']:
        raise InputError('Sidecar training_step conflicts with the recorded step')
    meta['training_step'] = row['step']
    meta['training_step_basis'] = 'source_logged_iteration'
    meta['training_step_pointer'] = '/step'
    # Hash identity is explicit about its grain: equal serialized prompts, not
    # a recovered environment task ID or proof of equal hidden task conditions.
    if not meta.get('task_id'):
        meta['task_id'] = 'prompt-sha256:' + hashlib.sha256(row['input'].encode()).hexdigest()
        meta['task_identity_basis'] = 'exact serialized input SHA-256'
    meta.setdefault('environment', 'verl-generation-export')
    event(events, kind='context', actor='context', text=row['input'], pointer='/input',
          source_role='serialized_generation_input')
    event(events, kind='message', actor='agent', text=row['output'], pointer='/output',
          source_role='serialized_generation_output')
    return {'recorded_reward': row.get('score'), 'recorded_reward_pointer': '/score'}


def read_jsonl(path, meta=None, *, max_bytes=100_000_000):
    """Validate the whole bounded batch before the caller writes any records."""
    from .import_batch import read_path
    return read_path(path,'verl-generation',meta,max_bytes)
