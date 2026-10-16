"""Bound new inspection work without treating payload bytes as billed tokens."""
from collections import Counter
from pathlib import Path
import time
import uuid

from .schema import InputError, digest, dumps
from .semantic_extraction import read, write

DEFAULT_LIMITS = {'jev_requests': 50, 'candidate_requests': 50, 'input_bytes': 1_000_000}


class BudgetReached(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Semantic execution budget reached; saved work can be resumed')


def limits(values=None):
    result = {**DEFAULT_LIMITS, **(values or {})}
    if set(result) != set(DEFAULT_LIMITS) or any(type(v) is not int or v < 0 for v in result.values()):
        raise InputError('Semantic limits require nonnegative integer jev_requests, candidate_requests and input_bytes')
    return result


class ExecutionBudget:
    """Per-invocation allowance. Cached decisions/proposals never enter invoke.

    Reserve and journal before calling the provider. A crash leaves `started`
    evidence: provider completion and billing are then unknown, not zero.
    """
    def __init__(self, directory, execution_id, allowance=None, *, ledger=None):
        self.directory = Path(directory)
        self.execution_id = execution_id
        self.limits = limits(allowance)
        self.used = dict.fromkeys(DEFAULT_LIMITS, 0)
        self.ledger = ledger

    def invoke(self, kind, request, callback, *, payload=None):
        if kind not in {'jev', 'candidate'}:
            raise InputError('Unknown semantic provider kind')
        key = digest(request)
        if payload is None:
            payload = request if kind == 'jev' else {'request_hash': key, 'request': request}
        elif (kind == 'jev' and payload != request or kind == 'candidate' and
              (not isinstance(payload, dict) or payload.get('request') != request or payload.get('request_hash') != key)):
            raise InputError('Budget payload differs from its bound request')
        size = len(dumps(payload).encode('utf-8'))
        counter = f'{kind}_requests'
        for field, increment in ((counter, 1), ('input_bytes', size)):
            if self.used[field] + increment > self.limits[field]:
                raise BudgetReached({'limit': field, 'used': self.used[field],
                                     'allowed': self.limits[field], 'next': increment,
                                     'provider': kind, 'request_hash': key})
        row = {'schema': 'semantic-provider-attempt/1', 'execution_id': self.execution_id,
               'provider': kind, 'request_hash': key,
               'stage': request.get('stage', request.get('state', {}).get('stage', 'partition')),
               'input_bytes': size, 'started_at_ns': time.time_ns(), 'status': 'started'}
        row['payload_hash'] = digest(payload)
        attempt_id = uuid.uuid4().hex
        row['attempt_id'] = attempt_id
        # An optional durable owner reserves before any external work. An
        # interrupted reservation is spent/unknown, never automatically refunded.
        if self.ledger is not None:
            self.ledger.reserve(row)
        path = self.directory / 'attempts' / f'{attempt_id}.json'
        write(path, row)
        self.used[counter] += 1
        self.used['input_bytes'] += size
        start = time.monotonic()
        try:
            response = callback()
            row['status'] = 'returned'
            usage = response.get('usage') if isinstance(response, dict) else None
            # Preserve numeric reported counters only. Never infer tokens from bytes.
            row['reported_usage'] = {k: usage[k] for k in ('input_tokens', 'output_tokens', 'total_tokens')
                                     if isinstance(usage, dict) and type(usage.get(k)) is int and usage[k] >= 0}
            return response
        except (Exception, KeyboardInterrupt) as exc:
            row['status'] = 'failed_or_interrupted'
            from .jev import failure_details
            from .candidate_process import failure_details as candidate_failure
            failure=failure_details(exc) or candidate_failure(exc)
            if failure is not None:row['provider_failure']=failure
            raise
        finally:
            row['elapsed_seconds'] = round(time.monotonic() - start, 3)
            write(path, row)
            if self.ledger is not None:
                self.ledger.finish(row)


def summary(directory):
    groups = {}
    for path in (Path(directory) / 'attempts').glob('*.json'):
        row = read(path)
        group = groups.setdefault(row['provider'], {'attempts': 0, 'input_bytes': 0,
                                 'statuses': Counter(), 'stages': Counter(),
                                 'reported_usage': Counter(), 'usage_observations': Counter(),
                                 'attempts_without_reported_usage': 0})
        group['attempts'] += 1
        group['input_bytes'] += row['input_bytes']
        group['statuses'][row['status']] += 1
        group['stages'][row['stage']] += 1
        group['reported_usage'].update(row.get('reported_usage', {}))
        group['usage_observations'].update(row.get('reported_usage', {}).keys())
        group['attempts_without_reported_usage'] += not bool(row.get('reported_usage'))
    return {'schema': 'semantic-provider-usage/1', 'providers': groups,
            'scope': 'Journaled attempts in this workspace; older unjournaled calls excluded.',
            'limits': 'Provider invocations and UTF-8 payload bytes, not token or money limits. The built-in Jev client makes one POST attempt per invocation without automatic retries; older clients and custom transports may differ. Reported usage may be incomplete; candidate commands may call a model more than once.'}
