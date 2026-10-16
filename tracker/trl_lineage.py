"""Opt-in, version-gated TRL mixin preserving identities through native shuffle.

This uses private trainer boundaries and intentionally fails setup outside the
inspected 1.13.0 single-process CPU path. Generic training-record transport is
independent of this adapter. No Torch/TRL import is required to import tracker.
"""
from importlib.metadata import version
import uuid
import warnings
import math

from .schema import InputError, digest
from .policy_age import OptimizerClock, uniform_history

VERSION = 'trl-grpo-training-lineage/4'
KEY = '_jev_sample_identity'


class OptimizerWindow:
    """Bounded immutable receipts for an accumulation window, never live tensors."""
    def __init__(self, limit=1000, token_limit=131072):
        self.limit = limit
        self.token_limit = token_limit
        self.clear()

    def clear(self):
        self.step = None
        self.records = []
        self.invalid = False
        self.gradient_tokens = 0

    def add(self, step, records):
        if self.invalid:
            return
        tokens = sum(len(r.get('data', {}).get('policy_gradient', {}).get('target_tokens', [])) for r in records if isinstance(r, dict))
        if (self.step is not None and self.step != step) or len(self.records) + len(records) > self.limit or self.gradient_tokens + tokens > self.token_limit:
            self.invalidate()
            raise InputError('Optimizer capture window changed step or exceeded its sample/token budget; confirmation omitted')
        self.step = step
        self.records.extend(records)
        self.gradient_tokens += tokens

    def invalidate(self):
        self.records = []
        self.invalid = True
        self.gradient_tokens = 0

    def finish(self, step, *, skipped, synchronized):
        records, expected, invalid = self.records, self.step, self.invalid
        self.clear()  # A duplicate callback or failed delivery cannot reuse a window.
        if skipped:
            return []
        if not synchronized or invalid or (records and expected != step):
            raise InputError('Optimizer sample window is incomplete, unsynchronized or has a different learner step')
        return records


def _optimizer_callback(trainer):
    # Optional dependency: importing the tracker does not import Transformers.
    from transformers import TrainerCallback

    class CaptureOptimizer(TrainerCallback):
        def on_train_begin(self, args, state, control, **kwargs):
            trainer._jev_optimizer_window.clear()

        def on_step_begin(self, args, state, control, **kwargs):
            window = trainer._jev_optimizer_window
            stale = bool(window.records or window.invalid)
            window.clear()
            if stale:
                trainer._jev_error(InputError('Unconfirmed prior accumulation window discarded'))

        def on_optimizer_step(self, args, state, control, **kwargs):
            trainer._jev_optimizer_completed(state.global_step)

        def on_train_end(self, args, state, control, **kwargs):
            trainer._jev_optimizer_window.clear()

    return CaptureOptimizer()


class GRPOTrainingLineageMixin:
    def __init__(self, *args, training_capture, confirm_optimizer_steps=False, capture_policy_gradients=False,
                 reward_components=None, **kwargs):
        if version('trl') != '1.13.0':
            raise InputError('Training lineage mixin is validated only with TRL 1.13.0')
        if confirm_optimizer_steps and any(version(name) != pin for name, pin in
                [('transformers', '5.19.0'), ('accelerate', '1.15.0'), ('torch', '2.14.1')]):
            raise InputError('Optimizer confirmation requires the validated Transformers 5.19.0 / Accelerate 1.15.0 / Torch 2.14.1 runtime')
        self.training_capture = training_capture
        self._jev_reward_components = reward_components
        self._jev_reward_matrix = None
        self._jev_optimizer_window = OptimizerWindow() if confirm_optimizer_steps else None
        self._jev_session = uuid.uuid4().hex
        self._jev_policy_clock = OptimizerClock(self._jev_session + '/actor') if confirm_optimizer_steps else None
        self._jev_uses = 0
        self._jev_prepared = None
        self._jev_capture_policy_gradients = capture_policy_gradients
        self._jev_gradient_active = False
        self._jev_gradient_hook = None
        self._jev_policy_gradients = None
        self._jev_gradient_error = None
        super().__init__(*args, **kwargs)
        if (self.accelerator.num_processes != 1 or self.accelerator.device.type != 'cpu'
                or self.use_vllm or getattr(self, 'tools', None) or getattr(self, 'rollout_func', None)
                or getattr(self.reward_funcs[0], '_jev_capture', None) is not training_capture):
            raise InputError('Lineage mixin requires single-process CPU, no tools/custom rollout, and the first reward wrapped by training_capture')
        if len(self.reward_funcs) != 1 or reward_components is not None:
            from .trl_reward_components import validate_components
            self._jev_reward_components = validate_components(reward_components, len(self.reward_funcs), training_capture.reward_definition)
            if any(getattr(f, '_jev_capture', None) is not None for f in self.reward_funcs[1:]):
                raise InputError('Wrap only the first reward; additional native reward columns share its sample identities')
        training_capture.retain_last_batch = True
        training_capture.counts.setdefault('lineage_failures', 0)
        self._jev_setup_ids = set()
        if capture_policy_gradients:
            from .trl_policy_gradients import check_runtime
            check_runtime(self)
        if confirm_optimizer_steps:
            if self.args.optim.value != 'adamw_torch':
                raise InputError('Optimizer confirmation is validated only for native adamw_torch')
            training_capture.counts.setdefault('optimizer_callbacks', 0)
            training_capture.counts.setdefault('optimizer_skipped', 0)
            training_capture.counts.setdefault('optimizer_sample_uses', 0)
            self.add_callback(_optimizer_callback(self))

    def train(self, *args, **kwargs):
        # A failed backward/optimizer/callback must not carry receipts into a
        # later train() call. Do not catch or replace the original exception.
        self._jev_session = uuid.uuid4().hex
        self._jev_policy_clock = OptimizerClock(self._jev_session + '/actor') if self._jev_optimizer_window else None
        self._jev_uses = 0
        if self._jev_optimizer_window:
            self._jev_optimizer_window.clear()
        try:
            return super().train(*args, **kwargs)
        finally:
            self._jev_prepared = None
            self._jev_reward_matrix = None
            if self._jev_optimizer_window:
                self._jev_optimizer_window.clear()

    def _jev_optimizer_completed(self, step):
        cap = self.training_capture
        cap.counts['optimizer_callbacks'] += 1
        clock = getattr(self, '_jev_policy_clock', None)
        verified = False
        try:
            import torch
            from accelerate.optimizer import AcceleratedOptimizer
            # A custom/no-op optimizer must not acquire the native guarantee.
            if (type(self.optimizer) is not AcceleratedOptimizer
                    or type(self.optimizer.optimizer) is not torch.optim.AdamW):
                raise InputError('Optimizer confirmation requires native AcceleratedOptimizer wrapping torch.optim.AdamW')
            skipped = self.accelerator.optimizer_step_was_skipped
            if skipped:
                cap.counts['optimizer_skipped'] += 1
            # Advance even when receipt delivery fails or the sample window is
            # incomplete. Those failures do not undo the actual optimizer step.
            if clock: clock.advance(step, skipped=skipped, synchronized=self.accelerator.sync_gradients)
            verified = True
            prior = self._jev_optimizer_window.finish(step, skipped=skipped,
                synchronized=self.accelerator.sync_gradients)
            for start in range(0, len(prior), 1000):
                records = [self._jev_record('use', r['id'] + '/optimizer', r['sample'],
                    {**r['data'], 'stage': 'optimizer_step_completed'},
                    'native on_optimizer_step after non-skipped AdamW step; learner_step is the trainer update index before increment; '
                    'completion mask is not final loss/gradient credit; backward record ' + r['id']) for r in prior[start:start + 1000]]
                cap.outbox.log_training(cap.experiment, records)
                cap.counts['optimizer_sample_uses'] += len(records)
        except Exception as exc:
            if clock and not verified: clock.invalidate()
            self._jev_optimizer_window.clear()
            self._jev_error(exc)

    def _jev_error(self, exc):
        cap = self.training_capture
        cap.counts['lineage_failures'] += 1
        if cap.on_error == 'raise': raise exc
        warnings.warn('Training lineage capture failed; training continues and facts may be partial: ' + str(exc), RuntimeWarning, stacklevel=3)

    def _jev_record(self, kind, identifier, sample, data, basis):
        return {'id': identifier, 'revision': 0, 'kind': kind, 'sample': sample,
                'evidence': {'basis': VERSION + ': ' + basis, 'source_revision': 0}, 'data': data}

    def _jev_setup(self):
        from .training_setup import TRL_FIELDS, inspect
        cap = self.training_capture
        # The trainer copies several arguments at initialization. Prefer those
        # effective attributes if present, not a subsequently edited args value.
        aliases = {'epsilon':'epsilon_low'}
        config = {k: getattr(self, aliases.get(k, k), getattr(self.args, k, None)) for k in TRL_FIELDS
                  if hasattr(self, aliases.get(k, k)) or hasattr(self.args, k)}
        if hasattr(config.get('reward_weights'), 'tolist'):
            config['reward_weights'] = config['reward_weights'].tolist()
        result = inspect({'framework':'trl', 'version':'1.13.0', 'resolved':True, 'config':config})
        recipe = result['recipe']
        if recipe is None:
            raise InputError('Unrecognized effective TRL settings; training context omitted')
        if recipe['id'] not in self._jev_setup_ids:
            cap.outbox.log_recipes(cap.experiment, [recipe])
            self._jev_setup_ids.add(recipe['id'])
        return {'producer':cap.outbox.producer, 'id':recipe['id'], 'revision':0}

    def _calculate_rewards(self, *args, **kwargs):
        self._jev_reward_matrix = None
        matrix = super()._calculate_rewards(*args, **kwargs)
        if self._jev_reward_components is not None:
            try:
                rows = matrix.detach().cpu().tolist()
                if (not isinstance(rows, list) or not 1 <= len(rows) <= 256
                        or any(len(row) != len(self._jev_reward_components) for row in rows)
                        or any(math.isinf(value) for row in rows for value in row)):
                    raise InputError('Native reward matrix shape or values are unsupported')
                self._jev_reward_matrix = [[None if math.isnan(v) else v for v in row] for row in rows]
            except Exception as exc:
                self._jev_error(exc)
        return matrix

    def _generate_and_score_completions(self, inputs):
        cap = self.training_capture
        cap.last_queued_batch = None
        self._jev_reward_matrix = None
        recipe = None
        clock = getattr(self, '_jev_policy_clock', None)
        generating_policy = clock.snapshot() if clock else None
        try:
            recipe = self._jev_setup()
        except Exception as exc:
            self._jev_error(exc)
        output = super()._generate_and_score_completions(inputs)
        try:
            if clock and generating_policy != clock.snapshot():
                raise InputError('Policy changed during generation; uniform policy history omitted')
            saved = cap.last_queued_batch
            if not saved or saved['reward_error']:
                raise InputError('Native generation completed without a captured reward batch')
            b = saved['batch']; n = len(b['completions'])
            g = self.num_generations if self.model.training else self.num_generations_eval
            if not 1 <= n <= 256 or n % g or len(output['completion_ids']) != n:
                raise InputError('Unsupported native group shape or more than 256 local completions')
            components = getattr(self, '_jev_reward_components', None)
            if components is not None and (self._jev_reward_matrix is None or len(self._jev_reward_matrix) != n):
                raise InputError('Native reward columns cannot bind to the captured sample rows')
            records = []; identities = []
            for i, snapshot in enumerate(saved['snapshots']):
                ids = b['token_ids'][i]
                if output['completion_ids'][i, :len(ids)].tolist() != ids:
                    raise InputError('Native completion tokens do not align with the captured reward row')
                ref = {'producer': cap.outbox.producer, 'rollout_id': snapshot['rollout_id']}
                meta = snapshot['document']['metadata']
                data = {'split': meta['split'], 'group_id': b['batch_id'] + '/group/' + str(i // g), 'group_size': g,
                        'step': meta['training_step'], 'step_basis': meta['training_step_basis']}
                if recipe: data['recipe'] = recipe
                if generating_policy: data['policy_history'] = uniform_history(generating_policy, len(ids))
                for key in ('task_id', 'environment', 'environment_version', 'policy_version'):
                    if key in meta: data[key] = meta[key]
                records.append(self._jev_record('sample', 'sample/' + ref['rollout_id'], ref, data,
                    'native single-process row groups in _generate_and_score_completions before shuffle'))
                if components is None:
                    value = saved['scores'][i]
                    records.append(self._jev_record('score', 'score/' + ref['rollout_id'], ref,
                        {'component': cap.reward_definition, 'definition': cap.reward_definition,
                         'status': 'scored' if value is not None else 'unavailable', 'value': value},
                        'the single wrapped reward component; not an inferred aggregate'))
                else:
                    for column, component in enumerate(components):
                        value = self._jev_reward_matrix[i][column]
                        records.append(self._jev_record('score', 'score/' + ref['rollout_id'] + '/' + str(column), ref,
                            {**component, 'status': 'scored' if value is not None else 'unavailable', 'value': value},
                            'native _calculate_rewards matrix column ' + str(column) + '; before reward weights/aggregation; NaN is unavailable'))
                loss_tokens = int(output['completion_mask'][i].sum().item())
                records.append(self._jev_record('selection', 'mask/' + ref['rollout_id'], ref,
                    {'filter': 'native_completion_mask', 'definition': 'trl/1.13.0/completion_mask',
                     'decision': 'admitted' if loss_tokens else 'rejected', 'batch_id': b['batch_id'],
                     'reason': 'positive native completion mask' if loss_tokens else 'zero native completion mask'},
                    'native completion mask after trainer truncation handling; not proof of backward use'))
                identity = {'sample': ref, 'model_tokens': len(ids), 'completion_digest':digest(ids)}
                if self._jev_capture_policy_gradients:
                    from .training_spans import from_tokenizer, unavailable
                    from .adapters import normalize
                    document = snapshot['document']; source = normalize(document, meta={'producer': cap.outbox.producer, 'logical_rollout_id': snapshot['rollout_id']})[0]
                    pointer = '/completion' if document['trajectory_format'] == 'generation/1' else (
                        '/messages/'+str(len(b['prompts'][i]))+'/content' if len(b['completions'][i]) == 1
                        and set(b['completions'][i][0]) <= {'role', 'content'} else None)
                    event = next((e for e in source['events'] if e['source_pointer'] == pointer), None)
                    identity['source_alignment'] = (from_tokenizer(self.processing_class, ids, source, event['id']) if event
                        else unavailable('Native completion is not one plain model-authored text event'))
                identities.append(identity)
            for start in range(0, len(records), 1000):
                cap.outbox.log_training(cap.experiment, records[start:start + 1000])
            # Native shuffle/split moves this list in exactly the same order as
            # the tensors, including identical completions and reused batches.
            output[KEY] = identities
        except Exception as exc:
            self._jev_error(exc)
        finally:
            cap.last_queued_batch = None
            self._jev_reward_matrix = None
        return output

    def _prepare_inputs(self, inputs):
        prepared = super()._prepare_inputs(inputs)
        refs = prepared.get(KEY)
        # Do not mutate the native reusable buffer or pass tracker fields to loss.
        clean = {k: v for k, v in prepared.items() if k != KEY}
        if self.model.training:
            recipe = None
            try:
                recipe = self._jev_setup()
            except Exception as exc:
                self._jev_error(exc)
            self._jev_prepared = (refs, clean, recipe)
        return clean

    def training_step(self, model, inputs, num_items_in_batch):
        self._jev_prepared = None
        self._jev_gradient_active = getattr(self, '_jev_capture_policy_gradients', False)
        self._jev_policy_gradients = None
        self._jev_gradient_error = None
        before = self.state.global_step
        clock = getattr(self, '_jev_policy_clock', None)
        learner_policy = clock.snapshot() if clock else None
        try:
            result = super().training_step(model, inputs, num_items_in_batch)
        except BaseException:
            self._jev_prepared = None
            self._jev_policy_gradients = None
            if self._jev_optimizer_window:
                self._jev_optimizer_window.invalidate()
            raise
        finally:
            self._jev_gradient_active = False
            handle = getattr(self, '_jev_gradient_hook', None)
            if handle is not None: handle.remove()
            self._jev_gradient_hook = None
        cap = self.training_capture
        try:
            if not self._jev_prepared or not self._jev_prepared[0]:
                raise InputError('Backward completed without retained sample identities')
            refs, prepared, recipe = self._jev_prepared
            if self._jev_gradient_error is not None:
                self._jev_policy_gradients = None
                self._jev_error(self._jev_gradient_error)
            elif getattr(self, '_jev_capture_policy_gradients', False) and self._jev_policy_gradients is None:
                self._jev_error(InputError('Backward returned without a native policy-gradient observation'))
            records = []
            for i, ref in enumerate(refs):
                records.append(self._jev_record('use', self._jev_session + '/use/' + str(self._jev_uses) + '/' + str(i), ref['sample'],
                    {'batch_id': self._jev_session + '/optimizer-before/' + str(before), 'learner_step': before,
                     **({'recipe':recipe} if recipe else {}),
                     **({'learner_policy':learner_policy} if learner_policy else {}),
                     **({'policy_gradient':self._jev_policy_gradients[i]} if self._jev_policy_gradients is not None else {}),
                     'stage': 'backward_completed', 'advantage': float(prepared['advantages'][i].item()),
                     'model_tokens': ref['model_tokens'], 'loss_tokens': int(prepared['completion_mask'][i].sum().item())},
                    'training_step returned after native backward; learner_step is the trainer update index before increment, including any skipped updates; completion_mask tokens'))
            cap.outbox.log_training(cap.experiment, records)
            if self._jev_optimizer_window:
                self._jev_optimizer_window.add(before, records)
        except Exception as exc:
            if self._jev_optimizer_window:
                self._jev_optimizer_window.invalidate()
            self._jev_error(exc)
        finally:
            self._jev_uses += 1
            self._jev_prepared = None
            self._jev_policy_gradients = None
        return result

    def _get_per_token_logps_and_entropies(self, *args, **kwargs):
        output = super()._get_per_token_logps_and_entropies(*args, **kwargs)
        if getattr(self, '_jev_gradient_active', False) and self._jev_prepared is not None:
            try:
                from .trl_policy_gradients import attach
                attach(self, output[0])
            except Exception as exc:
                self._jev_gradient_error = exc
        return output
