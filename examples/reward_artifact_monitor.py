"""Check required evaluator/submission artifacts; publish to the normal UI and SQL.

python examples/reward_artifact_monitor.py --db study.sqlite --reward-definition tests/v1 \
    --required solution.py --required test.py --follow

Before evaluation, record {name: snapshot_artifact(path)} in the rollout document's
evaluation_artifacts field. Use the actual evaluated files, not generated text.
"""
import argparse
import json

from rilldex import Workspace
from rilldex.reward_checks import check_artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--experiment')
    parser.add_argument('--reward-definition', required=True)
    parser.add_argument('--input-path', default='/raw/evaluation_artifacts')
    parser.add_argument('--required', action='append', default=[], metavar='NAME')
    parser.add_argument('--fixed', action='append', default=[], metavar='NAME=SHA256',
                        help='Pin an evaluator to its trusted baseline hash')
    parser.add_argument('--follow', action='store_true')
    args = parser.parse_args()
    artifacts = {name: {'nonempty': True} for name in args.required}
    for item in args.fixed:
        name, separator, sha = item.rpartition('=')
        if not name or not separator:
            parser.error('--fixed requires NAME=SHA256')
        artifacts[name] = {'nonempty': True, 'sha256': sha}
    from tracker.reward_artifacts import requirements
    requirements({'artifacts': artifacts})
    monitor = Workspace(args.db, experiment=args.experiment, observer='source').reward_detector(
        'Evaluator and submission artifacts', version='1',
        description='Missing/empty required artifacts or a changed fixed evaluator; recorded files, not inferred intent.',
        reward_definition=args.reward_definition, stage='execution',
        inputs={'artifacts': args.input_path}, config={'artifacts': artifacts})
    print(json.dumps(monitor.run(check_artifacts)), flush=True)
    if args.follow:
        monitor.follow(check_artifacts, interval=5)


if __name__ == '__main__':
    main()
