"""Real s3fs client over local HTTP to Moto; no AWS account or real credentials.

Install the test-only requirements in scripts/s3-smoke-requirements.txt, then run
with the tracker installed. The HTTP gate records only method/path and exercises
permission loss; boto3 writes authored fixtures directly to the separate server.
This is transport evidence, not validation of AWS IAM or a production endpoint.
"""
from collections import Counter
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
import json
import logging
import os
from pathlib import Path
import tempfile
import threading


def run(ui_control=None):
    with tempfile.TemporaryDirectory(prefix='jev-s3-client-') as tmp:
        root = Path(tmp)
        # Isolate from account profiles, fsspec files and real user credentials.
        for key in list(os.environ):
            if key.startswith(('AWS_', 'FSSPEC_')):
                del os.environ[key]
        os.environ.update(AWS_ACCESS_KEY_ID='testing', AWS_SECRET_ACCESS_KEY='testing',
                          AWS_DEFAULT_REGION='us-east-1', AWS_EC2_METADATA_DISABLED='true',
                          AWS_CONFIG_FILE=str(root/'no-aws-config'),
                          AWS_SHARED_CREDENTIALS_FILE=str(root/'no-aws-credentials'),
                          FSSPEC_CONFIG_DIR=str(root/'fsspec'))
        os.environ['NO_PROXY'] = '127.0.0.1,localhost'
        os.environ['no_proxy'] = os.environ['NO_PROXY']
        os.environ.pop('JEV_API_KEY', None)

        import boto3
        from moto.server import ThreadedMotoServer
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        upstream = ThreadedMotoServer(ip_address='127.0.0.1', port=0, verbose=False)
        upstream.start()
        host, port = upstream.get_host_and_port()
        requests, gate = [], {'denied': False}

        class ReadGate(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def forward(self):
                requests.append((self.command, self.path))
                if gate['denied']:
                    payload = b'<Error><Code>AccessDenied</Code><Message>CONTROL_ONLY_SECRET</Message></Error>'
                    self.send_response(403)
                    self.send_header('Content-Type', 'application/xml')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    if self.command != 'HEAD': self.wfile.write(payload)
                    return
                connection = http.client.HTTPConnection(host, port, timeout=10)
                try:
                    headers = {k: v for k, v in self.headers.items() if k.lower() not in {'host', 'connection'}}
                    connection.request(self.command, self.path, headers=headers)
                    response = connection.getresponse()
                    payload = response.read()
                    self.send_response(response.status)
                    for key, value in response.getheaders():
                        if key.lower() not in {'content-length', 'transfer-encoding', 'connection'}:
                            self.send_header(key, value)
                    length = response.getheader('Content-Length', '0') if self.command == 'HEAD' else str(len(payload))
                    self.send_header('Content-Length', length)
                    self.end_headers()
                    if self.command != 'HEAD': self.wfile.write(payload)
                finally:
                    connection.close()
            do_GET = do_HEAD = forward

        proxy = ThreadingHTTPServer(('127.0.0.1', 0), ReadGate)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        os.environ['FSSPEC_S3_ENDPOINT_URL'] = f'http://127.0.0.1:{proxy.server_address[1]}'
        checks = []
        try:
            # Import only after environment configuration, as in a fresh CLI.
            from tracker.connections import preview, validate
            from tracker.store import Store
            client = boto3.client('s3', endpoint_url=f'http://{host}:{port}')
            bucket = 'jev-client-control'
            client.create_bucket(Bucket=bucket)
            def put(key, value):
                client.put_object(Bucket=bucket, Key=key, Body=value)
            config = dict(root=f's3://{bucket}/exports', producer='s3/worker', mode='exports',
                          metadata={'experiment': 's3-client-control'}, max_records=1)
            store = Store(root/'workspace.sqlite')
            watcher = validate(store, config)[1]
            assert watcher.poll()['ingested'] == 0
            checks.append('attach before cloud output exists')

            raw = json.dumps({'input': 'Question', 'output': 'Answer', 'step': 1, 'score': 0}).encode()+b'\n'
            put('exports/worker.jsonl', raw*3)
            before = len(store.list())
            checked = preview(store, config)
            assert checked['coverage']['total_records'] == 2 and len(store.list()) == before
            checks.append('real-client temporary preview without ingestion')
            report = watcher.poll()
            assert report['ingested'] == 1 and report['backlog'] == 1
            checks.append('attach midway, bounded historical replay')

            # All remaining historical bytes are already local. Cloud permission
            # loss must remain visible without preventing that backlog from draining.
            gate['denied'] = True
            report = watcher.poll()
            assert report['ingested'] == 1 and report['deferred'] == 1
            assert report['cloud']['state'] == 'cached_only'
            assert 'CONTROL_ONLY_SECRET' not in json.dumps(report)
            assert validate(store, config)[1].poll()['ingested'] == 1
            assert len(store.list()) == 3
            checks.append('cached backlog and restart during HTTP permission failure')
            gate['denied'] = False
            watcher = validate(store, config)[1]
            assert watcher.poll()['cloud']['state'] == 'current'
            checks.append('permission recovery without duplicate rollouts')

            put('exports/worker.jsonl', raw*3+raw[:-1])
            assert watcher.poll()['waiting'] == 1
            put('exports/worker.jsonl', raw*4)
            assert validate(store, config)[1].poll()['ingested'] == 1
            ids = {r['id'] for r in store.list()}
            assert len(ids) == 4
            checks.append('future output, incomplete line and restart completion')

            before_requests = len(requests)
            assert watcher.poll()['cloud']['unchanged'] == 1
            assert not any(method == 'GET' and '/exports/worker.jsonl' in path for method, path in requests[before_requests:])
            checks.append('unchanged ETag avoids body download')
            put('exports/worker.jsonl', (raw*4).replace(b'Answer', b'Alter!'))
            assert watcher.poll()['deferred'] == 1
            assert {r['id'] for r in store.list()} == ids
            put('exports/worker.jsonl', raw*4)
            assert watcher.poll()['ingested'] == 0
            checks.append('same-length accepted-prefix rewrite rejected and restored')

            batch = Store(root/'batch'/'workspace.sqlite')
            batch_watcher = validate(batch, config)[1]
            for _ in range(5):
                report = batch_watcher.poll()
                if not report['backlog']: break
            assert {r['id'] for r in batch.list()} == ids
            checks.append('fresh batch replay matches live identities')

            snapshot_config = dict(root=f's3://{bucket}/snapshots', producer='s3/snapshots',
                                   mode='snapshots', metadata={'experiment': 's3-client-control'})
            snapshot = validate(store, snapshot_config)[1]
            document = {'trajectory_format': 'generation/1', 'prompt': 'Q', 'completion': 'A'}
            put('snapshots/one.json', json.dumps(document).encode())
            assert snapshot.poll()['ingested'] == 1
            document['completion'] = 'B'
            put('snapshots/one.json', json.dumps(document).encode())
            assert validate(store, snapshot_config)[1].poll()['ingested'] == 1
            assert store.latest_revision('s3/snapshots', 'one.json')['revision'] == 1
            checks.append('same-length snapshot replacement adds a revision')

            trajectory = {'schema_version': 'ATIF-v1.7', 'session_id': 'native-control',
                          'agent': {'name': 'authored-control', 'version': '1'}, 'steps': [
                {'step_id': 1, 'source': 'user', 'message': 'Inspect this example.'},
                {'step_id': 2, 'source': 'agent', 'message': 'Reading the example.', 'tool_calls': [
                    {'tool_call_id': 'read-1', 'function_name': 'read_file', 'arguments': {'path': 'example'}}],
                 'observation': {'results': [{'source_call_id': 'read-1', 'content': 'Example content'}]}}]}
            native_config = dict(root=f's3://{bucket}/native', producer='s3/harbor')
            native = validate(store, native_config)[1]
            put('native/trial/agent/trajectory.json', json.dumps(trajectory).encode())
            assert native.poll()['ingested'] == 1
            put('native/trial/result.json', json.dumps({'finished_at': '2026-10-14T00:00:00Z',
                'verifier_result': {'rewards': {'reward': 1}}}).encode())
            assert native.poll()['ingested'] == 1
            assert store.latest_revision('s3/harbor', 'trial/agent/trajectory.json')['state'] == 'complete'
            checks.append('native trajectory and late verifier sidecar')

            client.delete_object(Bucket=bucket, Key='exports/worker.jsonl')
            assert watcher.poll()['ingested'] == 0
            assert ids.issubset({r['id'] for r in store.list()})
            checks.append('remote deletion retains accepted evidence')
            assert requests and all(method in {'GET', 'HEAD'} for method, path in requests)
            checks.append('collector transport performs only GET and HEAD')
            print(json.dumps({'result': 'passed', 'checks': checks,
                              'transport': 's3fs over localhost HTTP to Moto; authored data only',
                              'versions': {name: version(name) for name in ('s3fs', 'fsspec', 'aiobotocore', 'moto', 'boto3')},
                              'collector_request_methods': dict(Counter(m for m, _ in requests))}))
            if ui_control:
                from tracker import connections
                from tracker.server import serve
                control = Path(ui_control).resolve()
                control.mkdir(parents=True, exist_ok=True)
                gate['denied'] = True
                connections.create(store, {**config, 'interval': .2})
                stop_control = threading.Event()
                def recover():
                    while not stop_control.wait(.05):
                        if (control/'allow-cloud').exists():
                            put('exports/worker.jsonl', raw*5)
                            gate['denied'] = False
                            return
                recovery = threading.Thread(target=recover, daemon=True)
                recovery.start()
                try:
                    serve(store, port=0)
                finally:
                    stop_control.set(); recovery.join(timeout=5)
        except Exception:
            print(json.dumps({'result': 'failed', 'completed_checks': checks}))
            raise
        finally:
            proxy.shutdown(); proxy.server_close(); thread.join(timeout=5)
            upstream.stop()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ui-control', help='Serve the authored control; touch DIR/allow-cloud to recover and append one record')
    run(parser.parse_args().ui_control)
