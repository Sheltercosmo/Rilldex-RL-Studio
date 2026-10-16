"""Authored boundary controls; native CPU execution has a separate audit."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tracker.schema import InputError
from tracker.trl_lineage import GRPOTrainingLineageMixin, OptimizerWindow
from tracker.policy_age import OptimizerClock


class OptimizerWindowTests(unittest.TestCase):
    def test_token_budget_omits_confirmation_without_retaining_partial_arrays(self):
        w=OptimizerWindow(token_limit=3)
        row={'data':{'policy_gradient':{'target_tokens':[1,2]}}}
        w.add(0,[row])
        with self.assertRaises(InputError):w.add(0,[row])
        self.assertEqual(w.records,[]);self.assertEqual(w.gradient_tokens,0)
        with self.assertRaises(InputError):w.finish(0,skipped=False,synchronized=True)

    def test_accumulated_rows_preserve_duplicates_and_order_and_finish_once(self):
        w = OptimizerWindow()
        w.add(4, [{'id': 'a'}, {'id': 'b'}]); w.add(4, [{'id': 'a'}])
        self.assertEqual(w.finish(4, skipped=False, synchronized=True), [{'id': 'a'}, {'id': 'b'}, {'id': 'a'}])
        self.assertEqual(w.finish(4, skipped=False, synchronized=True), [])

    def test_skipped_update_cannot_leak_into_next_update(self):
        w = OptimizerWindow(); w.add(3, ['old'])
        self.assertEqual(w.finish(3, skipped=True, synchronized=True), [])
        w.add(4, ['new'])
        self.assertEqual(w.finish(4, skipped=False, synchronized=True), ['new'])

    def test_incomplete_changed_or_unsynchronized_window_never_confirms(self):
        for variant in ('invalid', 'changed', 'unsynchronized'):
            with self.subTest(variant=variant):
                w = OptimizerWindow(); w.add(1, ['a'])
                if variant == 'invalid': w.invalidate()
                with self.assertRaises(InputError):
                    w.finish(2 if variant == 'changed' else 1, skipped=False, synchronized=variant != 'unsynchronized')
                self.assertEqual(w.records, [])

    def test_capacity_or_coordinate_violation_invalidates_whole_window(self):
        for step in (0, 1):
            w = OptimizerWindow(limit=1); w.add(0, ['a'])
            with self.assertRaises(InputError): w.add(step, ['b'])
            w.add(step, ['c'])
            self.assertEqual(w.records, [])
            with self.assertRaises(InputError): w.finish(step, skipped=False, synchronized=True)

    def test_failed_training_clears_state_without_replacing_original_exception(self):
        class Native:
            def train(self):
                self._jev_optimizer_window.add(0, ['pending'])
                self._jev_prepared = 'tensor'
                raise RuntimeError('native optimizer failed')
        class Wrapped(GRPOTrainingLineageMixin, Native): pass
        trainer = object.__new__(Wrapped)
        trainer._jev_optimizer_window = OptimizerWindow(); trainer._jev_prepared = None
        with self.assertRaisesRegex(RuntimeError, 'native optimizer failed'): trainer.train()
        self.assertEqual(trainer._jev_optimizer_window.records, [])
        self.assertIsNone(trainer._jev_prepared)

    def test_failed_backward_clears_tensor_and_invalidates_accumulated_rows(self):
        class Native:
            def training_step(self, *args):
                self._jev_prepared = 'tensor'
                raise RuntimeError('native backward failed')
        class Wrapped(GRPOTrainingLineageMixin, Native): pass
        trainer = object.__new__(Wrapped); trainer.state = SimpleNamespace(global_step=0)
        trainer._jev_optimizer_window = OptimizerWindow(); trainer._jev_optimizer_window.add(0, ['pending'])
        with self.assertRaisesRegex(RuntimeError, 'native backward failed'): trainer.training_step(None, None, None)
        self.assertTrue(trainer._jev_optimizer_window.invalid)
        self.assertIsNone(trainer._jev_prepared)

    def callback_case(self, *, skipped=False, fail=False):
        class AdamW: pass
        class AcceleratedOptimizer:
            def __init__(self): self.optimizer = AdamW()
        emitted = []
        def log(experiment, records):
            if fail: raise InputError('outbox full')
            emitted.extend(records)
        t = object.__new__(GRPOTrainingLineageMixin)
        t.training_capture = SimpleNamespace(experiment='e', on_error='raise',
            outbox=SimpleNamespace(log_training=log), counts=dict(lineage_failures=0, optimizer_callbacks=0, optimizer_skipped=0, optimizer_sample_uses=0))
        t.optimizer = AcceleratedOptimizer()
        t.accelerator = SimpleNamespace(optimizer_step_was_skipped=skipped, sync_gradients=True)
        t._jev_optimizer_window = OptimizerWindow()
        t._jev_policy_clock = OptimizerClock('callback-test/actor')
        t._jev_optimizer_window.add(2, [t._jev_record('use', 'native/backward/0', {'producer': 'p', 'rollout_id': 'r'},
            dict(batch_id='window2', learner_step=2, stage='backward_completed', model_tokens=8, loss_tokens=0, advantage=1), 'authored control')])
        modules = {'torch': SimpleNamespace(optim=SimpleNamespace(AdamW=AdamW)),
            'accelerate.optimizer': SimpleNamespace(AcceleratedOptimizer=AcceleratedOptimizer)}
        return t, emitted, modules

    def test_callback_preserves_zero_mask_and_links_original_backward(self):
        t, rows, modules = self.callback_case()
        with patch.dict(sys.modules, modules):
            t._jev_optimizer_completed(2); t._jev_optimizer_completed(2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['data']['stage'], 'optimizer_step_completed')
        self.assertEqual(rows[0]['data']['loss_tokens'], 0)
        self.assertEqual(rows[0]['id'], 'native/backward/0/optimizer')
        self.assertEqual(t.training_capture.counts['optimizer_sample_uses'], 1)
        self.assertEqual(t._jev_policy_clock.snapshot()['index'],1)

    def test_callback_skip_and_delivery_failure_cannot_later_confirm_old_rows(self):
        for skipped, fail in ((True, False), (False, True)):
            t, rows, modules = self.callback_case(skipped=skipped, fail=fail)
            with patch.dict(sys.modules, modules):
                if fail:
                    with self.assertRaisesRegex(InputError, 'outbox full'): t._jev_optimizer_completed(2)
                else: t._jev_optimizer_completed(2)
                t._jev_optimizer_completed(2)
            self.assertEqual(rows, [])
            self.assertEqual(t._jev_optimizer_window.records, [])
            self.assertEqual(t.training_capture.counts['optimizer_skipped'], 2 if skipped else 0)
            self.assertEqual(t._jev_policy_clock.snapshot()['index'],0 if skipped else 1)

    def test_custom_optimizer_is_not_native_confirmation(self):
        t, rows, modules = self.callback_case(); t.optimizer = object()
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(InputError, 'native AcceleratedOptimizer'): t._jev_optimizer_completed(2)
        self.assertEqual(rows, []); self.assertEqual(t._jev_optimizer_window.records, [])
        self.assertIsNone(t._jev_policy_clock.snapshot())
