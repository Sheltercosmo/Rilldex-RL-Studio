"""Add clearly synthetic comparison arms to execution_timeline_smoke's workspace."""
import argparse
import copy
import json
import math
from tracker.store import Store
from tracker.trainer_telemetry import receive, VERSION


def seed(database):
    store = Store(database)
    with store.connect() as c:
        source = c.execute('SELECT document FROM trainer_telemetry WHERE experiment=? ORDER BY step',
                           ('synthetic-execution-signals',)).fetchall()
    if not source:
        raise ValueError('First create the isolated execution_timeline_smoke workspace')
    count = 0
    for arm in ('synthetic-stable-control', 'synthetic-mismatch-growth'):
        records = []
        for i, row in enumerate(source):
            record = copy.deepcopy(json.loads(row[0]))
            record.pop('training_uses', None)
            record.update(id=f'comparison-{i}', session='synthetic-comparison', objective=arm)
            metrics = record['metrics']
            if arm.endswith('control'):
                reward = .5 + i*.003 + math.sin(i*.7)*.008
                gap = .03 + i*.0001
            else:
                reward = .5 + i*.003 - max(0, i-43)*.018
                gap = .03 * math.exp(max(0, i-35)*.10)
            for key, value in {'reward':reward, 'gap':gap,
                               'actor/grad_norm':2 + abs(math.sin(i))*.2,
                               'perf/throughput':680 if arm.endswith('control') else 800}.items():
                if key in metrics:
                    metrics[key]['value'] = value
            records.append(record)
        result = receive(store,dict(schema=VERSION,producer=arm,experiment=arm,records=records))
        count += result['inserted']
    return count


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True)
    print({'synthetic_records_added':seed(parser.parse_args().database)})
