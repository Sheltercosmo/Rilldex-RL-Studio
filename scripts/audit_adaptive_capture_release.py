"""Re-ingest retained adaptive evidence through a newly installed release.

The original trial executed fresh policies and native tools. This acceptance
check deliberately reuses that immutable evidence: no policy, tool, evaluator or
annotation model is called again. Run with the installed interpreter and -I.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
import zipfile

import rilldex
from rilldex import Outbox, Workspace
from tracker.adapters import FORMAT_VERSIONS, normalize
from tracker.capabilities import links
from tracker.graph_store import validate as validate_graph
from tracker.semantic_extraction import windows
from tracker.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    args = parser.parse_args()
    root, capture, wheel = args.root.resolve(), args.capture.resolve(), args.wheel.resolve()
    if root.exists():
        raise ValueError('Use a fresh directory; retain earlier audit evidence')
    assert sys.flags.isolated and 'site-packages' in rilldex.__file__
    assert FORMAT_VERSIONS['tau-bench'] == 'tau-bench/2'
    package_root = Path(rilldex.__file__).resolve().parent.parent
    installed_files = 0
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith(('rilldex/', 'tracker/')) and not name.endswith('/'):
                assert (package_root / name).read_bytes() == archive.read(name), name
                installed_files += 1

    report = json.loads((capture / 'report.json').read_text(encoding='utf-8'))
    original = Store(report['database'])
    sources = [original.get(row['run_id'], raw=True)['run']['raw'] for row in report['prefixes']]
    experiment = 'adaptive-capture-release-audit'
    spec = importlib.util.spec_from_file_location('lifecycle', Path(__file__).with_name('rl_lifecycle_simulation.py'))
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    (root / 'outputs').mkdir(parents=True)
    server = lifecycle.Server(root, experiment)
    live = None
    box_path = root / 'outbox.sqlite'
    identity, producer = 'retained-adaptive-case', 'release-audit'
    envelopes, receipts = [], []
    try:
        server.start()
        live = lifecycle.LiveEvents(server.url)
        lifecycle.wait_for(lambda: live.states, 'initial server push')
        initial_revision = live.states[-1]['source_revision']
        box = Outbox(box_path, endpoint=server.url, producer=producer, timeout=1)
        for index, (prefix, source) in enumerate(zip(report['prefixes'], sources)):
            if index == 7:
                live.close()
                server.stop()
            options = dict(state=prefix['state'], format='tau-bench', metadata={'experiment': experiment})
            queued = box.log(identity, source, **options)
            assert queued['revision'] == index and not queued['duplicate']
            envelopes.append(dict(producer=producer, rollout_id=identity, revision=index, document=source, **options))
            if index == 7:
                failed = box.drain()
                assert failed['retryable_error'] and failed['pending'] == 1 and failed['blocked'] == 0
            if 7 <= index < 9:
                continue
            if index == 9:
                assert box.status()['pending'] == 3
                server.start()
                # Recreate the producer from its durable file, with the new address.
                box = Outbox(box_path, endpoint=server.url, producer=producer, timeout=1)
                live = lifecycle.LiveEvents(server.url)
            status = box.drain(limit=1000)
            assert status['pending'] == status['blocked'] == 0, status
        lifecycle.wait_for(lambda: any(s['source_revision'] != initial_revision for s in live.states), 'source change push')
        with box.connect() as connection:
            receipts = [json.loads(row[0]) for row in connection.execute('SELECT receipt FROM queue ORDER BY revision')]
        assert len(receipts) == len(sources) == 26
        for receipt, envelope in zip(receipts, envelopes):
            run = server.request('/api/runs/' + receipt['id'] + '?raw=1')['run']
            source = envelope['document']
            assert run['raw'] == source
            assert run['adapter_version'] == 'tau-bench/2'
            assert run['events'] == normalize(source, 'tau-bench', envelope['metadata'])[0]['events']
            assert len({row['feedback_id'] for row in links(run)['records']}) == sum(
                message['role'] == 'tool' for message in source['simulation']['messages'])
            assert all(not event['source_pointer'].startswith('/task') for event in run['events'])
            if envelope['state'] == 'in_progress':
                assert run['outcome']['recorded_reward'] is None

        final = run
        controls = [event for event in final['events'] if event['kind'] == 'control']
        assert len(controls) == 1 and controls[0]['text'] == '###TRANSFER###'
        assert controls[0]['source_pointer'] == '/simulation/messages/24/content'
        requests = windows(final, include_user=True)
        assert controls[0]['id'] not in {row['event_id'] for row in requests}
        assert final['outcome']['recorded_reward'] == 1.0
        assert final['outcome'].get('verified_success') is None
        assert final['metadata'].get('training_step') is None

        # HTTP batch ingestion and duplicate delivery retain the same source facts.
        batch = dict(envelopes[-1], producer='release-batch', rollout_id='batch-case', revision=0,
                     metadata={'experiment': experiment + '-batch'})
        batch_receipt = server.request('/api/ingest', batch)
        batch_run = server.request('/api/runs/' + batch_receipt['id'] + '?raw=1')['run']
        assert batch_run['events'] == final['events'] and batch_run['outcome'] == final['outcome']
        assert not server.request('/api/ingest', batch)['received']
        assert not server.request('/api/ingest', envelopes[-1])['received']
        assert not server.request('/api/ingest', envelopes[0])['received']

        workspace = Workspace(server.db, experiment=experiment, observer='source')
        assert len(workspace.rollouts().rows) == 1 and not workspace.units().rows
        assert len(Workspace(server.db, experiment=experiment, observer='source', history=True).rollouts(limit=100).rows) == 26
        assert workspace.rollouts().rows[0]['run_id'] == final['id']
        graphs = workspace.graphs().rows
        assert len(graphs) == 1
        graph = server.request('/api/graphs/' + graphs[0]['graph_id'])
        validate_graph({key: value for key, value in graph.items() if key != 'matrices'})
        assert graph['counts']['unresolved_endpoints'] == 0
        assert sum(edge['type'] == 'response_to' for edge in graph['edges']) == 8
        metrics = {row['metric']: row for row in workspace.metrics(limit=1000).rows}
        assert metrics['environment_tool_error_fraction']['numerator'] == 0
        assert metrics['environment_tool_error_fraction']['denominator'] == 8
        assert metrics['recorded_success']['value'] is None
        assert metrics['activity_plan_share']['value'] is None
        sql = workspace.sql("SELECT metric,value,numerator,denominator FROM measurements WHERE metric IN ('recorded_reward','recorded_success','environment_tool_error_fraction') ORDER BY metric").rows
        assert len(sql) == 3
        assert all(row['value'] == metrics[row['metric']]['value'] for row in sql)
        http = server.request('/api/analysis/compute?' + urlencode(dict(function='recorded_outcomes', experiment=experiment, observer='source')))
        assert http['rows'] == workspace.recorded_outcomes().rows
        cli = server.cli('--db', server.db, 'analysis', 'table', 'rollouts', '--experiment', experiment)
        assert len(cli['rows']) == 1 and cli['rows'][0]['run_id'] == final['id']
        before = workspace.rollouts().rows
        live.close()
        server.stop()
        server.start()
        assert server.request('/api/analysis/compute?' + urlencode(dict(function='recorded_outcomes', experiment=experiment, observer='source')))['rows'] == http['rows']
        assert Workspace(server.db, experiment=experiment, observer='source').rollouts().rows == before
        box = Outbox(box_path, endpoint=server.url, producer=producer, timeout=1)
        assert box.drain()['sent_now'] == 0
        result = dict(schema='adaptive-release-audit/1', status='passed', adapter_version=FORMAT_VERSIONS['tau-bench'],
                      wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), installed_files_verified=installed_files,
                      runtime=dict(python=sys.executable, package=rilldex.__file__, isolated=True),
                      original_run=report['run_id'], normalized_run=final['id'], graph_id=graph['id'],
                      retained_revisions=26, final_messages=25, native_call_response_pairs=8,
                      control_events=1, eligible_semantic_windows=len(requests), semantic_units=0,
                      interrupted_pending_revisions=3, server_starts=server.starts,
                      batch_stream_equal=True, duplicate_and_stale_delivery_idempotent=True,
                      python_sql_http_cli_equal=True, live_source_push=True, metrics=sql,
                      outbox=box.status(), http_requests=server.request_counts, model_calls=0,
                      limits=['Re-ingestion of the retained fresh trial, no new policy generation or native execution',
                              'No semantic/macro accuracy or distributed load assertion'])
        (root / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        if live is not None:
            live.close()
        server.stop()


if __name__ == '__main__':
    main()
