"""mini-SWE-agent's public save boundary → durable tracker outbox.

This module does not import mini-SWE-agent or change model/tool execution.
Use CaptureMixin before DefaultAgent in the subclass's inheritance list.
"""
from copy import deepcopy
import time
import warnings

from .adapters import normalize
from .schema import InputError

VERSION = 'mini-save-capture/1'
RECORDED_ENDINGS = {'Submitted', 'LimitsExceeded', 'TimeExceeded', 'RepeatedFormatError', 'UserInterruption'}


class MiniCapture:
    def __init__(self, outbox, *, rollout_id, context, on_error, enrich=None):
        if not isinstance(rollout_id, str) or not rollout_id.strip() or not callable(context):
            raise InputError('Supply stable rollout identity and explicit metadata context callable')
        if on_error not in {'raise', 'warn'} or enrich is not None and not callable(enrich):
            raise InputError('Choose capture error policy raise/warn and optional state enrichment callable')
        self.outbox = outbox; self.rollout_id = rollout_id; self.context = context
        self.on_error = on_error; self.enrich = enrich
        self.counts = {'snapshots': 0, 'queued': 0, 'failed': 0, 'capture_seconds': 0.0}
        self.last_error = None

    def record(self, data):
        started = time.monotonic(); self.counts['snapshots'] += 1
        try:
            original = deepcopy(data); document = deepcopy(data)
            if not str((data.get('info') or {}).get('mini_version', '')).startswith('2.'):
                raise InputError('Live capture currently requires mini-SWE-agent v2; check a new version before upgrading')
            metadata = deepcopy(self.context())
            if not isinstance(metadata, dict): raise InputError('Capture context must return a metadata object')
            metadata['producer_capture_version'] = VERSION
            metadata['agent_framework_version'] = data['info']['mini_version']
            if self.enrich:
                document = self.enrich(document)
                native = deepcopy(document)
                if not isinstance(native, dict): raise InputError('State enrichment must return a trajectory object')
                native.pop('work_state', None)
                expected = deepcopy(original); expected.pop('work_state', None)
                if native != expected: raise InputError('State enrichment must preserve the entire native trajectory')
            normalize(document, 'mini-swe-agent', metadata)
            status = (data.get('info') or {}).get('exit_status')
            # A normally recorded stop is a complete trace, even when the task
            # was not solved. Treating limits as broken capture biases monitoring
            # by excluding exactly the failure cases researchers need to inspect.
            state = 'complete' if status in RECORDED_ENDINGS else 'failed' if status else 'in_progress'
            result = self.outbox.log(self.rollout_id, document, format='mini-swe-agent', state=state, metadata=metadata)
            self.counts['queued'] += 1; self.last_error = None
            return result
        except Exception as exc:
            self.counts['failed'] += 1; self.last_error = type(exc).__name__
            if self.on_error == 'raise': raise
            warnings.warn('Mini trajectory capture failed (' + type(exc).__name__ + '); native save is retained, inspect capture status.', RuntimeWarning, stacklevel=2)
        finally:
            self.counts['capture_seconds'] += time.monotonic() - started


class CaptureMixin:
    def __init__(self, *args, capture, **kwargs):
        self.tracker_capture = capture
        super().__init__(*args, **kwargs)

    def save(self, path, *extra_dicts):
        # Save the original through upstream first, including its exception/exit path.
        data = super().save(path, *extra_dicts)
        self.tracker_capture.record(data)
        return data
