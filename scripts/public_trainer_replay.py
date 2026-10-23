"""Validate published TimeChat-Captioner logs through the installed CLI and query API.

Download the two pinned JSON files into --source-dir first; this script makes no
network or model calls and does not load model weights or pickle files.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from tracker.store import Store
from tracker import telemetry_queries as q


REVISION = '46ca41be720031a2fd0959b4902147a71c22fc10'
BASE = 'https://huggingface.co/yaolily/TimeChat-Captioner-GRPO-7B/resolve/' + REVISION
FILES = {
    'trainer_state.json': 'cbd9d221ce12d13291d64a7eda7b74348f5d666dfa6beb54667a1756b745fede',
    'args.json': '006ab88644282eab17c29cf561506e5bb29ff4fd1b34be87886dc9d8027afb6a',
}
EXPERIMENT = 'public-timechat-captioner-grpo'


def replay(source_dir, database):
    source_dir, database = Path(source_dir).resolve(), Path(database).resolve()
    for name, expected in FILES.items():
        actual = hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f'{name}: expected the pinned public file from {BASE}/{name}')
    rows = json.loads((source_dir / 'trainer_state.json').read_text('utf-8'))['log_history']
    config = json.loads((source_dir / 'args.json').read_text('utf-8'))
    command = [sys.executable, '-m', 'rilldex', '--db', str(database), 'telemetry', 'import',
               str(source_dir / 'trainer_state.json'), '--experiment', EXPERIMENT,
               '--producer', 'timechat-captioner/published-learner', '--framework', 'ms-swift-grpo',
               '--framework-version', '3.11-custom/published-source-901444595260',
               '--objective', 'grpo/beta=0.04/scale_rewards=group/token-level', '--session', REVISION,
               '--population', 'published trainer log interval', '--environment', 'video-captioning']
    imports = []
    for _ in range(2):
        result = subprocess.run(command, text=True, encoding='utf-8', capture_output=True, check=True)
        imports.append(json.loads(result.stdout)['imported'])
    assert imports[1] == 0, imports
    store = Store(database)
    result = q.query(store, experiment=EXPERIMENT, half_life=10)
    series = {s['native_key']: s for s in result['series']}
    assert result['records'] == len(rows) == 256
    keys = set(rows[0]) - {'step', 'epoch'}
    assert set(series) == keys
    for key in keys:
        observed = series[key]
        assert observed['recorded'] == 256, key
        assert observed['reduction'] != 'unmapped', key
        assert observed['stats']['first']['value'] == rows[0][key], key
        assert observed['stats']['last']['value'] == rows[-1][key], key
        assert observed['stats']['minimum']['value'] == min(r[key] for r in rows), key
        assert observed['stats']['maximum']['value'] == max(r[key] for r in rows), key
    window = q.query(store, experiment=EXPERIMENT, start=100, end=120, half_life=10, as_of=result['as_of'])
    assert window['records'] == 21
    expected = None
    alpha = 1 - 2 ** (-1 / 10)
    for row in rows[:100]:
        expected = row['reward'] if expected is None else alpha * row['reward'] + (1 - alpha) * expected
    window_reward = next(s for s in window['series'] if s['native_key'] == 'reward')
    assert math.isclose(window_reward['trend_points'][0]['value'], expected)
    cutoff, packets = q.export_records(store, experiment=EXPERIMENT, as_of=result['as_of'])
    exported = [record for packet in packets for record in packet['records']]
    assert len(exported) == 256 and cutoff == result['as_of']
    originals = {r['step']: r for r in rows}
    for record in exported:
        assert record['split'] == 'train'
        assert 'training_uses' not in record
        for key, item in record['metrics'].items():
            assert item['value'] == originals[record['step']][key]
    summary = dict(source=BASE, sha256=FILES, experiment=EXPERIMENT, records=len(rows),
                   metrics=len(series), scalar_values=len(rows)*len(series), step_range=[1, 256],
                   repeated_imports=imports, interval_records=window['records'],
                   exact_native_export=True, full_history_ema=True,
                   source_configuration={k:config[k] for k in ('loss_type','beta','scale_rewards','num_generations','importance_sampling_level','reward_weights')},
                   limits=['Recorded-log replay; not execution of the original trainer.',
                           'Published v3.11 custom source; exact installed build is not recorded.',
                           'No rollout text, optimizer-use links, held-out outcomes, throughput or execution spans in this file.'])
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--report')
    args = parser.parse_args()
    output = json.dumps(replay(args.source_dir, args.database), indent=2)
    if args.report:
        Path(args.report).write_text(output + '\n', encoding='utf-8')
    print(output)
