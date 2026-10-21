"""Reproducible, synthetic product-tour inputs; no model or trainer calls.

python scripts/product_tour_fixture.py --output .tracker/product-tour
node scripts/render_product_tour.cjs .tracker/product-tour/tour.json
"""
import argparse
import json
import math
from pathlib import Path
import random
import tempfile

from rilldex import TrainerTelemetry, chat_document, compare_probabilities
from tracker import execution_records, execution_timeline, trainer_telemetry
from tracker.store import Store


def build(store):
    runs = []
    definitions = {
        'solve_rate': dict(label='Task success', group='reward', unit='fraction',
            reduction='successes / 256 generated episodes',
            definition='Seeded Bernoulli outcomes from a fixed synthetic task mixture. Not real training.'),
        'probability_gap': dict(label='Mean probability gap', group='mismatch', unit='probability',
            reduction='mean over 256 aligned sampled tokens',
            definition='Mean absolute learner-versus-sampler probability difference; synthetic binary distributions, not KL.'),
    }
    for arm, label in enumerate(('Steady run', 'Recovered run', 'Degrading run')):
        rng = random.Random(7421 + arm)
        logger = TrainerTelemetry(store, producer='tour-learner', experiment=label,
            framework='custom', framework_version='synthetic-demo', objective='demonstration-only',
            session='demo', population='fixed synthetic task mixture', definitions=definitions)
        records = []
        fluctuation = gap_fluctuation = 0
        for step in range(0, 1801 if arm != 2 else 1591, 3):
            fluctuation = .86 * fluctuation + rng.gauss(0, .007)
            p = .24 + .55 * (1 - math.exp(-step / 260)) + fluctuation
            gap = .0045 + step * .0000015
            if arm == 1:
                disturbance = math.exp(-.5 * ((step - 920) / 125) ** 2)
                p -= .18 * disturbance
                gap += .023 * disturbance
            elif arm == 2:
                p -= .46 / (1 + math.exp(-(step - 1370) / 55))
                gap += .11 / (1 + math.exp(-(step - 1250) / 65))
            gap_fluctuation = .88 * gap_fluctuation + rng.gauss(0, .075)
            gap *= math.exp(gap_fluctuation) * (rng.uniform(1.5, 2.2) if rng.random() < .018 else 1)
            successes = sum(rng.random() < max(.02, min(.98, p)) for _ in range(256))
            behavior = [rng.uniform(.08, .85) for _ in range(256)]
            learner = [max(.001, min(.999, v + rng.choice((-1, 1)) * gap * rng.uniform(.3, 1.7))) for v in behavior]
            measured = compare_probabilities(map(math.log, behavior), map(math.log, learner), [1] * 256)
            # Assemble one record per log before one atomic batch receive.
            packet = trainer_telemetry.packet(
                {'solve_rate': successes / 256, 'probability_gap': measured['mean_probability_gap']},
                step=step, split='train', record_id='step-' + str(step), training_uses=None, **logger.context)
            records.extend(packet['records'])
        trainer_telemetry.receive(store, dict(schema=trainer_telemetry.VERSION,
            experiment=label, producer='tour-learner', records=records))
        captured = trainer_telemetry.snapshot(store, experiment=label)
        assert not captured['truncated']
        runs.append(dict(label=label, snapshot=captured))

    experiment = 'Asynchronous execution demo'
    records = []
    def span(identifier, worker, start, end, kind='inference', state='completed', rollout=None, **extra):
        r = dict(id=identifier, revision=0 if end is None else 1, kind=kind,
            state=state, rollout=rollout, context=dict(worker=worker),
            timing=dict(clock='demo/shared-seconds', start=start, end=end),
            evidence='Authored product-tour simulation; not measured execution.')
        if end is not None: r['metrics'] = dict(duration_ms=(end-start)*1000)
        r.update(extra)
        records.append(r)
        return r

    rng = random.Random(8102)
    for worker in range(1, 5):
        cursor = (worker-1)*2.4
        index = 0
        while cursor < 172:
            duration = rng.uniform(13, 32)
            end = cursor+duration
            if worker == 2 and index == 2:
                cursor = 62; end = 82
                r = span('request-18-a1', 'Sampler 2', cursor, end, state='failed',
                    rollout=dict(producer='tour', id='rollout-18'), source_revision=0,
                    configuration={'finish_reason': 'request_timeout', 'backend': 'vLLM', 'policy_version': 'v42'})
                span('request-18-a2', 'Sampler 2', 86, 114,
                    rollout=dict(producer='tour', id='rollout-18'), source_revision=0,
                    retry_of=dict(producer='tour', id='request-18-a1'),
                    configuration={'finish_reason': 'stop', 'backend': 'vLLM', 'policy_version': 'v42'})
                cursor=119; index+=2; continue
            span(f's{worker}-{index}', f'Sampler {worker}', round(cursor, 1),
                round(end, 1) if end <= 180 else None,
                state='completed' if end <= 180 else 'running',
                rollout=dict(producer='tour', id=f'rollout-{worker}-{index}'))
            cursor=end+rng.uniform(2, 6); index+=1
    for i, start in enumerate((16, 31, 50, 74, 94, 119, 143, 164)):
        span(f'check-{i}', 'Verifier', start, start+rng.uniform(4, 9), kind='verification',
            rollout=dict(producer='tour', id=f'check-rollout-{i}'))
    logger = TrainerTelemetry(store, producer='tour', experiment=experiment, framework='custom',
        framework_version='synthetic-demo', objective='demonstration-only', session='demo',
        definitions={'throughput': dict(label='Generation throughput', group='throughput', unit='tokens/s',
            reduction='synthetic interval token count / elapsed seconds', definition='Authored demonstration signal, not a benchmark.')})
    for i, start in enumerate((26, 49, 72, 99, 126, 151, 173)):
        logger.log({'throughput': [3240, 3510, 2980, 2440, 3380, 3620, 3490][i]}, step=40+i, record_id=f'log-{i}')
        span(f'update-{40+i}', 'Learner', start, start+5, kind='learner_update',
            telemetry=[dict(producer='tour', id=f'log-{i}')])
        span(f'sync-{40+i}', 'Weight sync', start+5, start+6.8, kind='weight_sync')
    store.ingest(dict(producer='tour', rollout_id='rollout-18', revision=0, state='complete',
        document=chat_document([dict(role='user', content='Repair the parser and verify the change.'),
            dict(role='assistant', content='The first inference request timed out. The retried request completed; run the targeted parser test next.')]),
        metadata={'experiment': experiment, 'environment': 'software'}))
    execution_records.receive(store, dict(schema=execution_records.TIMELINE_VERSION,
        producer='tour', experiment=experiment, records=records))
    execution = execution_timeline.snapshot(store, experiment=experiment, clock='demo/shared-seconds', start=0, end=180)
    failed = next(e for e in execution['executions'] if e['record']['id']=='request-18-a1')
    assert failed['run_id'] and len(execution['logs']) == 7
    assert sum(e['record']['state']=='failed' for e in execution['executions']) == 1
    return dict(schema='product-tour-demo/1', synthetic=True, seed=[7421, 7422, 7423, 8102],
        note='Authored demonstration. No real training results, algorithm comparison, or causal inference.',
        runs=runs, execution=execution)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    output=parser.parse_args().output; output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rilldex-tour-') as tmp:
        data=build(Store(Path(tmp)/'workspace.sqlite'))
    (output/'tour.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'runs': len(data['runs']), 'logs': sum(r['snapshot']['records'] for r in data['runs']),
                      'operations': len(data['execution']['executions']), 'output': str(output/'tour.json')}))
