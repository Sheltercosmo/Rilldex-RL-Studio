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

__all__ = ['__version__', 'Workspace', 'Outbox', 'TrainerTelemetry', 'ExecutionRecorder', 'compare_probabilities', 'Episode', 'chat_document', 'generation_document']
