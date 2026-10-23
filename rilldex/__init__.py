"""Rilldex: evidence-linked RL behavior inspection.

The stable, framework-independent Python SDK remains in ``tracker``.
"""
from tracker import __version__
from tracker.workspace_analysis import Workspace
from tracker.capture import Outbox
from tracker.trainer_telemetry import TrainerTelemetry
from tracker.portable import Episode, chat_document, generation_document
from .execution import ExecutionRecorder
from tracker.policy_comparison import compare_probabilities
from tracker.detector_validation import ValidationSet
from tracker.findings_report import export_findings
from .run import Run
from .trials import TrialStudy

__all__ = ['__version__', 'Workspace', 'Outbox', 'Run', 'TrainerTelemetry', 'ExecutionRecorder', 'compare_probabilities', 'ValidationSet', 'export_findings', 'TrialStudy', 'Episode', 'chat_document', 'generation_document']
