"""Exercise an installed wheel from outside the checkout, using only stdlib.

Run with the Python interpreter where the wheel is installed. No trainer/model
provider is contacted. The process and temporary workspace are always cleaned up.
"""
import base64
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen


def run(container=False):
    with tempfile.TemporaryDirectory(prefix='jev-portable-') as directory:
        root = Path(directory)
        outputs = root / 'outputs'
        outputs.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'JEV_API_KEY'}}
        env['PYTHONUTF8'] = '1'
        # Exercise installed entry points, including existing user scripts.
        scripts = Path(sysconfig.get_path('scripts'))
        suffix = '.exe' if os.name == 'nt' else ''
        expected_version = 'Rilldex ' + importlib.metadata.version('rilldex')
        for entry in ([sys.executable, '-m', 'rilldex'], [sys.executable, '-m', 'tracker'],
                      [str(scripts / ('rilldex' + suffix))], [str(scripts / ('jev-track' + suffix))]):
            result = subprocess.run([*entry, '--version'], cwd=root, env=env,
                                    capture_output=True, text=True, check=True, timeout=15)
            assert result.stdout.strip() == expected_version, result.stdout
        base = [sys.executable, '-m', 'rilldex', '--db', str(root / 'db.sqlite')]
        checked = subprocess.run([*base, 'doctor', '--port', '0'], cwd=root, env=env,
                                 capture_output=True, text=True, check=True, timeout=30)
        assert json.loads(checked.stdout)['ready']
        log_path = root / 'server.log'
        args = [*base, 'start', '--port', '0', '--watch', str(outputs), '--mode', 'exports',
                '--experiment', 'smoke', '--producer', 'smoke/worker', '--interval', '.2']
        if container:
            args.append('--container')

        def stop(process):
            if process.poll() is None:
                # Windows venv launchers may own a child Python process. Stop
                # this test's process tree so a collector cannot outlive it.
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                else:
                    process.terminate()
                process.wait(timeout=10)

        def start():
            log = log_path.open('w', encoding='utf-8')
            process = subprocess.Popen(args, cwd=root, env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                text = log_path.read_text(encoding='utf-8')
                match = re.search(r'Rilldex: (http://127\.0\.0\.1:\d+)', text)
                if match:
                    return process, log, match[1]
                if process.poll() is not None:
                    log.close()
                    raise AssertionError(text)
                time.sleep(.1)
            stop(process)
            log.close()
            raise AssertionError('Startup timeout: ' + log_path.read_text(encoding='utf-8'))

        def request(path, body=None):
            req = Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'} if body is not None else {})
            with urlopen(req, timeout=20) as response:
                data = response.read()
                return json.loads(data) if 'application/json' in response.headers.get('Content-Type', '') else data

        def wait_for(predicate):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if predicate():
                    return
                time.sleep(.1)
            raise AssertionError('Timed out waiting for collection')

        process, log, url = start()
        try:
            assert request('/api/health') == {'ready': True, 'service': 'rilldex'}
            import xml.etree.ElementTree as ET
            for asset in ('/rilldex-mark.svg', '/rilldex-logo.svg', '/favicon.ico'):
                with urlopen(url + asset, timeout=5) as response:
                    assert response.headers.get_content_type() == 'image/svg+xml'
                    svg = ET.fromstring(response.read())
                    assert svg.tag == '{http://www.w3.org/2000/svg}svg'
                    assert svg.find('{http://www.w3.org/2000/svg}title').text == 'Rilldex'
            from urllib.error import HTTPError
            for headers in ({'Host': 'untrusted.example'}, {'Origin': 'https://untrusted.example'}):
                try:
                    urlopen(Request(url + '/api/health', headers=headers), timeout=5)
                    raise AssertionError('Unexpected cross-origin/host access')
                except HTTPError as e:
                    assert e.code == 403
            for route in ('/', '/connections', '/semantic-map', '/investigate', '/integration-guide',
                          '/connections.js', '/deployment-guide.js', '/rollout-map.js', '/api/integrations'):
                assert request(route), route
            assert request('/api/runs')['runs'] == []
            # Start before output exists; then attach, partial write and finish.
            row = {'input':'Question','output':'Answer','step':7,'score':0}
            path = outputs / 'worker.jsonl'
            raw = json.dumps(row).encode()
            path.write_bytes(raw)
            wait_for(lambda: request('/api/connections')['connections'][0]['status'].get('waiting') == 1)
            assert request('/api/runs')['runs'] == []
            with path.open('ab') as f:
                f.write(b'\n')
            wait_for(lambda: len(request('/api/runs')['runs']) == 1)
            rid = request('/api/runs')['runs'][0]['id']
            # CLI replay must not race an active managed reader of this producer.
            config_row = request('/api/connections')['connections'][0]
            replay_args = [*base, 'watch', str(outputs), '--mode', 'exports',
                           '--experiment', 'smoke', '--producer', 'smoke/worker', '--once']
            busy = subprocess.run(replay_args, cwd=root, env=env, capture_output=True, text=True, timeout=20)
            assert busy.returncode == 1 and 'still being collected' in busy.stderr
            request('/api/connections/' + config_row['id'] + '/state', {'enabled': False})
            def paused():
                row = request('/api/connections')['connections'][0]
                return not row['running'] and not row['stopping']
            wait_for(paused)
            replay = subprocess.run(replay_args, cwd=root, env=env, capture_output=True, text=True, timeout=20)
            assert replay.returncode == 0, replay.stderr
            assert len(request('/api/runs')['runs']) == 1
            request('/api/connections/' + config_row['id'] + '/state', {'enabled': True})
            wait_for(lambda: request('/api/connections')['connections'][0]['running'])
            rollout = request('/api/monitoring/rollout/' + rid + '?observer=source')
            assert rollout['run']['id'] == rid and rollout['graph']['nodes']
            assert request('/api/graphs/' + rollout['graph']['id'])['run_id'] == rid
            assert request('/api/rollout-metrics')
            # Frozen file import and live HTTP are both available in this wheel.
            doc = {'trajectory_format':'generation/1','prompt':'Q','completion':'A','outcome':{'reward':1}}
            body = {'file':{'name':'completed.json','base64':base64.b64encode(json.dumps(doc).encode()).decode()}}
            assert request('/api/import-file/check', body)['total_rollouts'] == 1
            assert request('/api/import-file', body)['total_rollouts'] == 1
            packet = {'producer':'http-worker','rollout_id':'sample-1','revision':0,'state':'in_progress',
                      'document':doc,'metadata':{'experiment':'smoke'}}
            receipt = request('/api/ingest', packet)
            assert receipt['received']
            assert not request('/api/ingest', packet)['received']
            assert request('/api/ingest', {**packet,'revision':1,'state':'complete'})['received']
            assert len(request('/api/runs')['runs']) == 3
            delivery = request('/api/source-status/' + receipt['id'])
            assert delivery['tracked'] and delivery['is_latest'] and delivery['state']=='complete'
            # Download the online snapshot and restore it through the installed
            # CLI, without restarting collection or using repository resources.
            archive = root/'download.rilldex.zip'
            archive.write_bytes(request('/api/workspace/snapshot'))
            restored_path = root/'restored.sqlite'
            restored = subprocess.run([sys.executable,'-m','rilldex','--db',str(restored_path),
                                      'workspace','restore',str(archive)],cwd=root,env=env,
                                     capture_output=True,text=True,check=True,timeout=30)
            receipt = json.loads(restored.stdout)
            assert receipt['status']=='restored' and not receipt['inference_started']
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(restored_path)) as c:
                assert c.execute('SELECT count(*) FROM runs').fetchone()[0] == 3
                assert c.execute('SELECT count(*) FROM data_connections WHERE enabled=1').fetchone()[0] == 0
            # Restart with a new automatic port and the same persistent state.
            stop(process)
            log.close()
            process, log, url = start()
            wait_for(lambda: request('/api/connections')['connections'][0]['status'].get('phase') == 'watching')
            assert len(request('/api/runs')['runs']) == 3
            assert rid in {r['id'] for r in request('/api/runs')['runs']}
            with path.open('ab') as f:
                f.write(raw + b'\n')
            wait_for(lambda: len(request('/api/runs')['runs']) == 4)
            # Generic JSON snapshots use the same path before/during/after a job.
            snapshots = root/'snapshots'
            snapshots.mkdir()
            config = {'root':str(snapshots),'producer':'snapshot-worker','mode':'snapshots',
                      'metadata':{'experiment':'smoke'},'interval':.2}
            empty = request('/api/connections/preview', config)
            assert empty['files'] == 0 and not empty['persisted']
            connection = request('/api/connections', config)
            snapshot = snapshots/'sample.json'
            snapshot.write_text(json.dumps(doc),encoding='utf-8')
            wait_for(lambda: len(request('/api/runs')['runs']) == 5)
            checked = request('/api/connections/preview', config)
            assert checked['coverage']['total_records'] == 1
            assert checked['coverage']['metric_coverage']['recorded_reward']['available'] == 1
            doc['completion'] = 'Updated answer'
            snapshot.write_text(json.dumps(doc),encoding='utf-8')
            def revised():
                rows = request('/api/runs')['runs']
                return any((r.get('ingestion') or {}).get('producer')=='snapshot-worker' and
                           r['ingestion']['revision']==1 for r in rows)
            wait_for(revised)
            assert len(request('/api/runs')['runs']) == 5
            print(json.dumps({'result':'passed','checks':['installed assets','automatic port','empty directory',
                'partial write','managed live collection','persisted map and measures','frozen batch import','HTTP revisions',
                'JSON snapshot preflight','JSON snapshot collection and revision','online workspace download','CLI restore','paused restored collectors','restart','append after restart',
                'competing reader rejected','pause and CLI ownership handoff'],
                'platform':sys.platform,'python':sys.version.split()[0]}))
        finally:
            stop(process)
            log.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--container', action='store_true', help='Exercise the container listener against a temporary workspace')
    run(parser.parse_args().container)
