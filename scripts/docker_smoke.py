"""Real Docker lifecycle check. Run on a host with Docker Compose v2 installed."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen
import uuid

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='jev-docker-') as tmp:
    output = Path(tmp)
    output.chmod(0o755)  # The image's non-root UID must be able to read the fixture mount.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'RILLDEX_PORT': str(port), 'RILLDEX_OUTPUT_DIR': str(output),
           'RILLDEX_PRODUCER': 'docker-smoke/exports', 'RILLDEX_EXPERIMENT': 'authored-docker-smoke', 'RILLDEX_INPUT_MODE': 'exports'}
    command = ['docker', 'compose', '-p', 'jev-smoke-' + uuid.uuid4().hex[:12], '-f', str(repo / 'compose.yaml')]
    def compose(*args):
        return subprocess.run([*command, *args], cwd=repo, env=env, check=True, timeout=600)
    def get(path):
        with urlopen(f'http://127.0.0.1:{port}' + path, timeout=5) as response:
            return json.loads(response.read())
    def wait_count(count):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if len(get('/api/runs')['runs']) == count: return
            time.sleep(.2)
        raise AssertionError('Expected ' + str(count) + ' captured rollouts')
    raw = json.dumps(dict(input='Q', output='A', step=1, score=1)).encode() + b'\n'
    (output / 'worker.jsonl').write_bytes(raw)  # Mid-training: already-written output.
    try:
        compose('up', '--build', '-d', '--wait')
        assert get('/api/health')['ready']
        wait_count(1)
        first = get('/api/runs')['runs'][0]['id']
        with (output / 'worker.jsonl').open('ab') as f: f.write(raw[:-1])
        time.sleep(3)
        wait_count(1)
        with (output / 'worker.jsonl').open('ab') as f: f.write(b'\n')
        wait_count(2)
        compose('stop')
        with (output / 'worker.jsonl').open('ab') as f: f.write(raw)
        compose('up', '-d', '--wait')
        wait_count(3)
        assert first in {r['id'] for r in get('/api/runs')['runs']}
        # Container recreation must also retain database and cursor volume.
        compose('down')
        compose('up', '-d', '--wait')
        wait_count(3)
        assert get('/api/monitoring/rollout/' + first + '?observer=source')['graph']['nodes']
        # Exercise the full simulation inside the actual non-root image too,
        # without shipping test code in the production wheel or using a GPU.
        subprocess.run([*command,'exec','-T','tracker','python','-'],
                       input=(repo/'scripts/rl_lifecycle_simulation.py').read_text(encoding='utf-8'),
                       text=True,encoding='utf-8',cwd=repo,env=env,check=True,timeout=180)
        print(json.dumps({'result': 'passed', 'checks': ['existing output', 'new output', 'partial line', 'stop and catch up', 'container recreation', 'map evidence', 'full RL lifecycle simulation']}))
    finally:
        # Only the uniquely named test project and its disposable volume.
        compose('down', '--volumes')
