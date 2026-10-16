"""Run an explicit history query on imported rollouts, without model calls.

Example: python -m tracker.history_query --db .tracker/tracker.sqlite
         --query query.json --run ROLLOUT_ID --output result.json
"""
import argparse
import json
from pathlib import Path
from . import history_evidence, investigation_plans
from .schema import InputError, digest
from .store import Store


def execute(store, query, run_ids):
    history_evidence.validate(query)
    if not run_ids or len(set(run_ids)) != len(run_ids):
        raise InputError('Select distinct imported rollout IDs')
    runs = [investigation_plans.run_source(store, rid) for rid in run_ids]
    plan = {'schema': investigation_plans.VERSION, 'nodes': [
        {'name': 'rollout-' + str(i), 'op': 'history_evidence', 'inputs': [],
         'params': {'run_id': run['id'], 'source_hash': digest(run), 'query': query}}
        for i, run in enumerate(runs)]}
    result = investigation_plans.execute(store, plan)
    return {'schema': 'history-query-export/1', 'query': query, 'plan_id': result['id'],
            'execution': result['execution'],
            'rollouts': [{'run_id': run['id'], 'metadata': run['metadata'],
                          'result': result['outputs']['rollout-' + str(i)]}
                         for i, run in enumerate(runs)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--query', type=Path, required=True)
    parser.add_argument('--run', action='append', required=True, help='Imported rollout ID; repeat for multiple rollouts')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.db.is_file(): raise InputError('Database does not exist')
        query = json.loads(args.query.read_text(encoding='utf-8'))
        result = execute(Store(args.db), query, args.run)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (InputError, OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps({'output': str(args.output), 'plan_id': result['plan_id'],
                      'execution': result['execution'], 'rollouts': [
                          {'run_id': row['run_id'], 'graph_id': row['result']['graph_id'],
                           'metrics': row['result']['metrics']} for row in result['rollouts']]}))


if __name__ == '__main__': main()
