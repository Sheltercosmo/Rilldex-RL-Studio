"""Apply your own alert rule to a saved ratio monitor, once or during training.

python examples/custom_monitor_policy.py run workspace.sqlite my-analysis.sqlite MONITOR_ID
python examples/custom_monitor_policy.py resume my-analysis.sqlite BATCH_ID
Use --follow to repeat without saving duplicate unchanged batches.
Use resume to finish retained inputs without the source database.
No model or UI required.
"""
import argparse
import json
import math
import time

from tracker.research import Research, Results

SQL = '''SELECT v.value_id,v.run_id,v.monitor_id,v.observer,v.source_hash,v.input_hash,
  v.value,v.status,v.reason,v.numerator,v.denominator,r.experiment,r.generation_step
  FROM rl_monitor_values v JOIN rl_rollouts r USING(run_id)
  WHERE r.is_latest=1 AND v.is_latest=1 AND v.monitor_id=? ORDER BY v.run_id'''


def assess(row, config):
    if row['status']!='available' or row['value'] is None:
        return dict(flag=None,status='unavailable',reason=row['reason'] or row['status'])
    if row['denominator'] is None or row['denominator']<config['min_opportunities']:
        return dict(flag=None,status='insufficient_support',reason='Not enough recorded eligible opportunities')
    return dict(flag=row['value']<config['threshold'],status='available',value=row['value'],
        numerator=row['numerator'],denominator=row['denominator'],
        reason='User threshold on this saved ratio; no causal or whole-task recovery claim')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    run=commands.add_parser('run',help='Evaluate current monitor results, once or continuously')
    run.add_argument('database');run.add_argument('results');run.add_argument('monitor_id')
    run.add_argument('--threshold',type=float,default=.5);run.add_argument('--min-opportunities',type=int,default=5)
    run.add_argument('--follow',action='store_true');run.add_argument('--interval',type=float,default=10)
    resume=commands.add_parser('resume',help='Finish an exact saved batch using its original configuration')
    resume.add_argument('results');resume.add_argument('batch_id')
    args=parser.parse_args()
    if args.command=='resume':
        saved=Results(args.results)
        definition=saved.batch(args.batch_id)['definition']
        if definition['name']!='user-ratio-threshold' or definition['sql']!=SQL:
            parser.error('This batch was not produced by this example; resume it with its own callback')
        print(json.dumps(saved.resume(args.batch_id,assess,version='1')),flush=True)
        return
    if not math.isfinite(args.threshold) or not 0<=args.threshold<=1:parser.error('threshold must be in [0,1]')
    if args.min_opportunities<1:parser.error('min-opportunities must be positive')
    if not math.isfinite(args.interval) or args.interval<.2:parser.error('interval must be at least 0.2 seconds')
    lab=Research(args.database,args.results)
    config=dict(threshold=args.threshold,min_opportunities=args.min_opportunities)
    try:
        first=True
        while True:
            batch=lab.evaluate('user-ratio-threshold','1',SQL,assess,parameters=[args.monitor_id],
                config=config,key_columns=['run_id','monitor_id'],limit=100000,skip_unchanged=True)
            if first or not batch['unchanged']:print(json.dumps(batch),flush=True)
            first=False
            if not args.follow:break
            time.sleep(args.interval)
    except KeyboardInterrupt:pass


if __name__=='__main__':main()
