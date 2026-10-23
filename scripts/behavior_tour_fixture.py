"""Build authored behavior examples through the real aggregation pipeline.

For documentation only; never calls a model or represents measured accuracy.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_approach_distribution import save_run
from tracker import behavior_distributions
from tracker.store import Store


def build(store):
    examples = [
        (0, ['reported'] * 5, ['same_procedure'] * 4),
        (1, ['reported', 'reported', 'unresolved'], ['reconfigured_procedure'] * 2),
        (2, ['reported', 'reported'], ['alternative_procedure']),
        (3, ['reported', 'not_reported'], ['same_procedure']),
        (4, ['reported', 'not_reported', 'reported', 'unresolved'], ['reconfigured_procedure'] * 3),
        (5, ['reported', 'not_reported', 'reported'], ['alternative_procedure'] * 2),
        (5, ['reported', 'unresolved'], [None]),
    ]
    for i, (step, reports, procedures) in enumerate(examples):
        save_run(store, f'demo-{i}', step, reports, procedures)
    snapshot = behavior_distributions.snapshot(
        store, lens='procedure', a_start=0, a_end=2, b_start=3, b_end=5)
    assert snapshot['approach_followup']['earlier']['total'] == 7
    assert snapshot['approach_followup']['later']['total'] == 5
    return {'synthetic': True, 'note': 'Authored behavior examples; not an accuracy evaluation.',
            'snapshot': snapshot}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='rilldex-behavior-tour-') as directory:
        result = build(Store(Path(directory) / 'workspace.sqlite'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    print('Saved authored behavior snapshot:', args.output)
