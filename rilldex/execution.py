"""Small synchronous recorder; use an Outbox for durable background delivery."""
from contextlib import contextmanager
from copy import deepcopy
import time

from tracker import execution_records


class ExecutionRecorder:
    """Capture actual execution spans under an explicitly shared seconds clock.

    ``clock`` identifies both the clock origin and synchronization domain. Use
    different identities for hosts that cannot establish a common time basis.
    The default ``now`` is UTC Unix seconds; this does not synchronize machines.
    """
    def __init__(self, target, *, experiment, clock, producer=None, now=time.time):
        self.target=target;self.experiment=experiment;self.clock=clock;self.now=now
        self.producer=producer or getattr(target,'producer',None)
        execution_records._text(self.producer,'producer')
        execution_records._text(clock,'clock')
        execution_records._text(experiment,'experiment')

    def record(self, record):
        packet=dict(schema=execution_records.TIMELINE_VERSION,producer=self.producer,
                    experiment=self.experiment,records=[deepcopy(record)])
        if hasattr(self.target,'log_execution'):
            return self.target.log_execution(self.experiment,packet['records'],schema=packet['schema'])
        return execution_records.receive(self.target,packet)

    @contextmanager
    def span(self, identifier, *, kind, rollout=None, context=None, configuration=None, policy=None):
        """Yield a record to populate with metrics and exact telemetry references.

        A crash leaves the saved running report. Use a new attempt ID for an
        actual retry; replaying the outbox never starts the operation again.
        """
        start=self.now();tick=time.monotonic()
        record=dict(id=identifier,revision=0,kind=kind,rollout=deepcopy(rollout),
                    state='running',context=deepcopy(context or {}),
                    timing=dict(clock=self.clock,start=start,end=None),evidence='ExecutionRecorder span boundaries')
        if configuration is not None:record['configuration']=deepcopy(configuration)
        if policy is not None:record['policy']=deepcopy(policy)
        self.record(record)
        try:
            yield record
        except BaseException as operation_error:
            record.update(state='failed',revision=1)
            record['timing']['end']=self.now()
            record.setdefault('metrics',{})['duration_ms']=(time.monotonic()-tick)*1000
            # Preserve the operation's exception if capture also fails.
            try:self.record(record)
            except Exception as capture_error:operation_error.add_note('Execution failure could not be captured: '+str(capture_error))
            raise
        else:
            record.update(state='completed',revision=1)
            record['timing']['end']=self.now()
            record.setdefault('metrics',{})['duration_ms']=(time.monotonic()-tick)*1000
            self.record(record)
