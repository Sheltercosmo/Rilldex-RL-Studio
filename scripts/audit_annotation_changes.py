"""Read retained review/observer snapshots without inference or source migration."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

if not sys.flags.isolated:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rilldex import Workspace
from tracker import annotation_changes
from tracker.graph_queries import PRESETS
from tracker.schema import dumps


def run(database, output, pairs):
    database = database.resolve(); output.mkdir(parents=True, exist_ok=False)
    if sys.flags.isolated and 'site-packages' not in Path(annotation_changes.__file__).parts:
        raise AssertionError('Isolated audit requires the installed package')
    ws = Workspace(database, history=True)
    before_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as c:
        headers = {r[0]: json.loads(r[1]) for r in c.execute('SELECT id,document FROM rollout_graphs')}
    if not pairs:
        pairs = [(review['previous_graph_id'], gid) for gid, g in headers.items()
                 if (review := (g.get('semantic_context') or {}).get('unit_reviews'))]
    if not pairs:
        raise AssertionError('No saved unit reviews or explicit graph pairs')
    questions = [PRESETS['assessment_of_inspection_feedback'],
                 {**PRESETS['assessment_of_inspection_feedback'], 'anchor_activity':'verify',
                  'question':'How often does the agent assess feedback returned by verification?'}]
    results = []
    for a, b in pairs:
        report = ws.annotation_changes(a, b, requirements=questions)
        name = f'comparison-{len(results)+1}.json'
        (output/name).write_text(dumps(report)+'\n', encoding='utf-8')
        results.append(dict(file=name, baseline=a, current=b, run_id=report['run_id'],
            baseline_units=report['units']['baseline'], current_units=report['units']['current'],
            exact_span_matches=report['units']['exact_span_matches'], changed_aligned_units=report['units']['changed_aligned_units'],
            boundary_changes=[r['kind'] for r in report['units']['boundary_changes']],
            activity_deltas=[r for r in report['activity_counts'] if r['delta']],
            relation_delta_groups=len(report['relationships']['changes']),
            measures=[dict(anchor_activity=r['requirement']['anchor_activity'], delta=r['delta'],
                           baseline_status=r['baseline']['status'], current_status=r['current']['status'],
                           same_anchor_population=r['same_anchor_population']) for r in report['measurements']]))
    after_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    if after_hash != before_hash:
        raise AssertionError('Audit input changed; use a quiescent workspace copy to validate no mutation')
    result = dict(schema='annotation-change-audit/1', status='passed', database=str(database),
                  source_database_sha256=before_hash, database_file_unchanged=True,
                  access_mode='Read-only SQLite connections; no source migration or inference. File hash does not cover live WAL changes.',
                  installed=bool(sys.flags.isolated), implementation=str(Path(annotation_changes.__file__).resolve()),
                  comparisons=results, training_source_coverage=ws.table('training_records')['source_coverage'],
                  fresh_model_calls=0,
                  limits='Saved development annotations and named review controls, not independent gold, fresh inference or training improvement.')
    (output/'report.json').write_text(dumps(result)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--database', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--pair', nargs=2, action='append', default=[], metavar=('BASELINE_GRAPH','CURRENT_GRAPH'))
    args = p.parse_args(); run(args.database, args.output, args.pair)
