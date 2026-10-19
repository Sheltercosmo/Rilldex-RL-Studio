"""Checks on artifacts actually supplied to an evaluator, without model inference."""
import hashlib
from pathlib import Path
import re

from .schema import InputError

VERSION = 'reward-artifacts/1'


def snapshot_artifact(path):
    """Record one explicitly selected file. Capture before evaluation, in its worker.

    Missing files differ from missing telemetry. Permission/read errors propagate;
    a failed capture must not be recorded as an empty or deleted file.
    """
    sha = hashlib.sha256()
    size = 0
    try:
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(chunk)
                size += len(chunk)
    except FileNotFoundError:
        return {'exists': False}
    return {'exists': True, 'size_bytes': size, 'sha256': sha.hexdigest()}


def requirements(config):
    rules = config.get('artifacts')
    if not isinstance(rules, dict) or not 1 <= len(rules) <= 64:
        raise InputError('Configure 1–64 required artifact names')
    for name, rule in rules.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise InputError('Artifact names must be nonempty strings of at most 500 characters')
        if not isinstance(rule, dict) or set(rule) - {'nonempty', 'sha256'}:
            raise InputError('Artifact requirements accept nonempty and optional expected sha256')
        if 'nonempty' in rule and type(rule['nonempty']) is not bool:
            raise InputError('nonempty must be boolean')
        if 'sha256' in rule and (not isinstance(rule['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', rule['sha256'])):
            raise InputError('Expected sha256 must be a lowercase SHA-256 digest')
    return rules


def check_artifacts(ctx):
    """RewardDetector callback: named manifests in inputs['artifacts'].

    Each configured artifact must exist; nonempty defaults to true. An optional
    expected sha256 pins immutable evaluator code/data. This checks the recorded
    manifest, not the agent's intention, permissions, or evaluation outcome.
    """
    rules = requirements(ctx.config)
    records = ctx.inputs['artifacts']
    if not isinstance(records, dict):
        return {'status': 'unknown', 'summary': 'Artifact manifest is not an object.'}
    violations, missing, checked = [], [], []
    for name, rule in rules.items():
        record = records.get(name)
        if not isinstance(record, dict) or type(record.get('exists')) is not bool:
            missing.append(name)
            continue
        if not record['exists']:
            violations.append({'artifact': name, 'issue': 'missing_file'})
            checked.append(name)
            continue
        size = record.get('size_bytes')
        if type(size) is not int or size < 0:
            missing.append(name)
            continue
        if rule.get('nonempty', True) and size == 0:
            violations.append({'artifact': name, 'issue': 'empty_file'})
        if 'sha256' in rule:
            sha = record.get('sha256')
            if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
                missing.append(name)
                continue
            if sha != rule['sha256']:
                violations.append({'artifact': name, 'issue': 'digest_changed'})
        checked.append(name)
    status = 'flagged' if violations else 'unknown' if missing else 'clear'
    summary = ('; '.join(f"{v['artifact']}: {v['issue'].replace('_', ' ')}" for v in violations[:3])
               + (f'; {len(violations) - 3} more' if len(violations) > 3 else '')
               if violations else 'Artifact capture is incomplete.' if missing
               else f'{len(checked)} required artifacts match the configured checks.')
    return {'status': status, 'summary': summary,
            'input_evidence': ['artifacts'],
            'details': {'schema': VERSION, 'violations': violations,
                        'checked': checked, 'missing_capture': missing,
                        'interpretation': 'Recorded artifact integrity only; neither intent nor successful reward hacking is inferred.'}}
