"""Publish a graph-aware custom monitor; use --follow for ongoing collection.

python examples/live_custom_monitor.py --db workspace.sqlite --follow
Runs locally against the collector database. Does not call an LLM or export data.
"""
import argparse
import json
from rilldex import Workspace


def missing_responses(ctx):
    actions = {event['id'] for event in ctx.run['events']
               if event['kind'] == 'action' and event['actor'] == 'agent'
               and not event.get('copied_context')}
    responded = {edge['target'].removeprefix('event:') for edge in ctx.graph['edges']
                 if edge['type'] == 'response_to'}
    missing = sorted(actions - responded)
    if not actions:
        return {'value': None, 'reason': 'No recorded agent actions; no opportunities.'}
    return {
        'numerator': len(missing), 'denominator': len(actions),
        'evidence_ids': ['event:' + event for event in missing],
        'feedback': {
            'severity': 'warning' if missing else 'info',
            'summary': f'{len(missing)} of {len(actions)} actions lack a linked response.',
            'next_check': 'Inspect capture completeness and terminal actions before interpreting agent behavior.'
                          if missing else 'Response links are present; inspect their meaning with semantic monitors.'},
        'details': {'missing_action_ids': missing, 'interpretation':
                    'Capture coverage only. No inference about tool success or whether the agent used feedback.'},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--experiment')
    parser.add_argument('--follow', action='store_true')
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    workspace = Workspace(args.db, experiment=args.experiment, observer='source')
    monitor = workspace.monitor('Actions missing responses', version='1',
        description='Share of recorded agent actions without a source-linked response; capture coverage, not task failure.',
        unit='fraction', aggregation='opportunity_ratio')
    print(json.dumps({'monitor_id': monitor.id, **monitor.run(missing_responses)}), flush=True)
    if args.follow:
        monitor.follow(missing_responses, interval=args.interval)


if __name__ == '__main__':
    main()
