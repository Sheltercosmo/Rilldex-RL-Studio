"""Installed-package RL lifecycle acceptance test. No trainer, GPU or model API.

Three authored training batches have a known recovery regression and recovery.
The real collector, worker outbox, monitor service, graph store, HTTP endpoints,
research API and snapshot/export code run unchanged. Synthetic evidence validates
plumbing and arithmetic, not semantic-extraction accuracy or RL effectiveness.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile

import rilldex
from rilldex import Outbox, Workspace, chat_document
from tracker.analytics import Analysis
from tracker.analysis_mirror import FeedMirror
from tracker.state_capture import WorkStateRecorder, call_ref, object_version


EXPERIMENT = 'simulated-recovery-training'
PATTERNS = [('recovered', 'failed', 'failed', 'unobserved'),
            ('failed', 'failed', 'failed', 'unobserved'),
            ('recovered', 'recovered', 'recovered', 'unobserved')]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def wait_for(fn, description, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(.1)
    raise AssertionError('Timed out: ' + description)


def dashboard_ready(result, monitor_ids, expected):
    # An incomplete snapshot can already have a measured (unavailable) result.
    # Wait for final source delivery as well as monitor materialization before
    # asserting the training samples' exact final-revision joins.
    rows = [m for m in result['monitors'] if m['id'] in monitor_ids]
    return (result['population'] == expected and len(result['runs']) == expected
        and all(r['state'] == 'complete' for r in result['runs'])
        and len(rows) == len(monitor_ids) and all(
        sum(len(s['points']) for s in m['series']) == expected
        and m['coverage']['statuses'].get('pending', 0) == 0 for m in rows))


def document(step, index, environment, *, partial=False):
    """Known state changes and check results, recorded through the producer SDK."""
    pattern = PATTERNS[step][index]
    metadata = dict(experiment=EXPERIMENT, environment=environment,
                    environment_version='simulation/1', task_id='repair-record', split='train',
                    training_step=step, training_step_basis='generation', policy_version=f'policy-{step}')
    messages = [dict(role='user', content='Make the record valid, then check it.')]
    recorder = WorkStateRecorder(environment=environment + '/simulation-1')
    state = 0
    operations = ['check'] if partial or pattern == 'unobserved' else ['check', 'edit', 'check']
    for n, operation in enumerate(operations):
        cid = f'call-{n}'
        action, result = call_ref(cid), call_ref(cid, result=True)
        messages.append(dict(role='assistant', content='Check the record.' if operation == 'check' else 'Correct the record.',
                             tool_calls=[dict(id=cid, type='function', function=dict(name=operation, arguments='{}'))]))
        before = recorder.snapshot(action, {'record': object_version(state)})
        if operation == 'edit':
            state = 1
            messages.append(dict(role='tool', tool_call_id=cid, content='Record changed.'))
            after = recorder.snapshot(result, {'record': object_version(state)})
            recorder.edit(action, result, before=before, after=after)
        else:
            outcome = 'passed' if n > 0 and pattern == 'recovered' else 'failed'
            messages.append(dict(role='tool', tool_call_id=cid, content=outcome))
            recorder.check(action, result, snapshot=before, criterion_id='record-valid', criterion_version='1',
                           required_objects=['record'], outcome=outcome, state_stable=True)
    reward = None if partial else int(pattern == 'recovered')
    return recorder.attach(chat_document(messages, metadata=metadata, reward=reward,
                                         success=None if partial else bool(reward)))


def facts(step, index, producer, environment):
    name = f'batch-{step}/sample-{index}'
    reward = int(PATTERNS[step][index] == 'recovered')
    def record(kind, data):
        return dict(id=f'{kind}/{name}', revision=0, kind=kind,
                    sample=dict(producer=producer, id=name),
                    evidence=dict(basis='Authored lifecycle simulation; no optimizer executed'), data=data)
    return [
        record('sample', dict(split='train', group_id=f'group-{step}', group_size=4,
               step=step, step_basis='generation', policy_version=f'policy-{step}',
               environment=environment, environment_version='simulation/1',
               source=dict(producer=producer, rollout_id=name, revision=1))),
        record('score', dict(component='validity', definition='simulated-verifier/1', status='scored', value=reward)),
        record('selection', dict(filter='training-filter', definition='simulation/1',
               batch_id=f'update-{step}', decision='admitted')),
        record('use', dict(batch_id=f'update-{step}', learner_step=100 + step * 10,
               stage='optimizer_step_completed', advantage=reward - sum(p == 'recovered' for p in PATTERNS[step])/4,
               model_tokens=80, loss_tokens=80)),
    ]


class Server:
    def __init__(self, root, experiment=EXPERIMENT):
        self.root = root
        self.experiment = experiment
        self.db = root/'workspace.sqlite'
        self.outputs = root/'outputs'
        self.env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'JEV_API_KEY'}}
        self.env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1')
        self.process = None
        self.starts = 0
        self.request_counts = {}

    def start(self):
        self.starts += 1
        path = self.root/f'server-{self.starts}.log'
        self.log = path.open('w', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable, '-I', '-m', 'rilldex', '--db', str(self.db),
            'start', '--port', '0', '--watch', str(self.outputs), '--mode', 'exports',
            '--experiment', self.experiment, '--producer', 'files', '--interval', '.2'],
            cwd=self.root, env=self.env, stdout=self.log, stderr=self.log)
        def ready():
            text = path.read_text(encoding='utf-8')
            require(self.process.poll() is None, text)
            match = re.search(r'Rilldex: (http://127\.0\.0\.1:\d+)', text)
            if match:
                self.url = match[1]
                return self.request('/api/health')['ready']
        wait_for(ready, 'installed server startup')

    def stop(self):
        if self.process and self.process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                self.process.kill()  # Exercise ungraceful collector loss, not only clean shutdown.
            self.process.wait(timeout=15)
        if hasattr(self, 'log'):
            self.log.close()

    def request(self, path, body=None, raw=False):
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=40) as response:
            data = response.read()
        key=request.get_method()+' '+path.split('?')[0]
        self.request_counts[key]=self.request_counts.get(key,0)+1
        return data if raw else json.loads(data)

    def cli(self, *args):
        run = subprocess.run([sys.executable, '-I', '-m', 'rilldex', *map(str, args)],
                             cwd=self.root, env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=60)
        require(run.returncode == 0, run.stderr + run.stdout)
        return json.loads(run.stdout)


class LiveEvents:
    def __init__(self, url):
        self.states = []
        self.error = None
        self.stop = threading.Event()
        def listen():
            try:
                with urlopen(url + '/api/live/events', timeout=5) as response:
                    while not self.stop.is_set():
                        line = response.readline().decode()
                        if not line:
                            break
                        if line.startswith('data:'):
                            self.states.append(json.loads(line[5:]))
            except OSError as exc:
                if not self.stop.is_set():
                    self.error = str(exc)
        self.thread = threading.Thread(target=listen, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=6)


def run(root):
    require('site-packages' in str(Path(rilldex.__file__).resolve()),
            'Install the wheel into a clean venv, then run this script with that interpreter.')
    root.mkdir(parents=True, exist_ok=True)
    require(not (root/'workspace.sqlite').exists(), 'Use a new output directory; never overwrite an existing workspace.')
    server = Server(root)
    report = dict(schema='rl-lifecycle-acceptance/1', platform=platform.platform(), python=platform.python_version(),
                  package=str(Path(rilldex.__file__).resolve()), synthetic=True, model_calls=0, phases=[])
    started = time.monotonic()
    def phase(name, **details):
        row = dict(name=name, seconds=round(time.monotonic()-started, 3), **details)
        report['phases'].append(row)
        (root/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(row), flush=True)
    live = None
    try:
        # `start --watch` intentionally requires an existing mount. An empty
        # directory is the supported before-training path; never create a lost mount.
        server.outputs.mkdir()
        server.start()
        require(server.request('/api/runs')['runs'] == [], 'Before-training workspace must be empty')
        live = LiveEvents(server.url)
        wait_for(lambda: live.states, 'initial server-push state')
        baseline_revision = live.states[-1]['source_revision']
        monitors = {}
        for measure in ['next_check_success', 'next_check_success_changed']:
            monitors[measure] = server.request('/api/monitoring/monitors', {'definition':dict(
                name='Simulation · '+measure.replace('_', ' '), kind='analysis', observer='source',
                analysis=dict(measure=measure))})
        phase('before_training', monitors=len(monitors), empty_source_waits=True)
        file = server.outputs/'worker.jsonl'
        box_path = root/'worker outbox.sqlite'
        early = Outbox(box_path, producer='sdk', endpoint=server.url)
        early.log_training(EXPERIMENT, facts(0,0,'sdk','terminal'), schema='training-records/2')
        early.drain()
        early_health=server.request('/api/training-health?experiment='+EXPERIMENT)
        require(sum(c['missing_source'] for c in early_health['cohorts'])==1, 'Undelivered source was silently matched')
        require(early_health['cohorts'][0]['rewards'][0]['group_states']=={'incomplete':1}, 'Partial group treated as complete')
        phase('training_before_sources', missing_source=1, partial_group_excluded=True)

        def send_sdk(step):
            box = Outbox(box_path, producer='sdk', endpoint=server.url)
            for index in range(4):
                name = f'batch-{step}/sample-{index}'
                box.log_training(EXPERIMENT, facts(step, index, 'sdk', 'terminal'), schema='training-records/2')
                for partial, state in [(True, 'in_progress'), (False, 'complete')]:
                    box.log(name, document(step,index,'terminal',partial=partial), state=state)
            result = box.drain(limit=100)
            require(box.status()['pending'] == 0, str(result))

        def write_files(step, partial_tail=False):
            for index in range(4):
                name = f'batch-{step}/sample-{index}'
                server.request('/api/training-records', dict(schema='training-records/2', producer='files',
                    experiment=EXPERIMENT, records=facts(step,index,'files','business-workflow')))
                for revision in (0,1):
                    packet = dict(rollout_id=name, revision=revision, state='in_progress' if revision==0 else 'complete',
                                  document=document(step,index,'business-workflow',partial=revision==0))
                    raw = json.dumps(packet, ensure_ascii=False).encode()
                    with file.open('ab') as stream:
                        stream.write(raw if partial_tail and index==3 and revision==1 else raw+b'\n')

        def dashboard(expected):
            result = server.request('/api/monitoring?' + urlencode(dict(experiment=EXPERIMENT)))
            wanted = {m['id'] for m in monitors.values()}
            return result if dashboard_ready(result, wanted, expected) else None

        for step in range(3):
            if step == 2:
                # Queue while disconnected; no network or training process is required to retain it.
                live.close()
                server.stop()
                offline = Outbox(box_path, producer='sdk', endpoint=server.url)
                offline.log('batch-2/sample-0', document(2,0,'terminal',partial=True), state='in_progress')
                require(offline.status()['pending']==1, 'Offline capture was not durable')
                phase('interruption', queued_while_down=1)
                server.start()
                require(len(Workspace(server.db,experiment=EXPERIMENT).rollouts().rows)==16, 'Restart duplicated old rollouts')
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(send_sdk,step),pool.submit(write_files,step,step==1)]
                for future in futures:
                    future.result()
            if step == 1:
                wait_for(lambda:len(Workspace(server.db,experiment=EXPERIMENT).rollouts().rows)==16, 'partial tail population')
                # The unfinished final record must not be accepted before the newline.
                rows=Workspace(server.db,experiment=EXPERIMENT).rollouts().rows
                pending=[r for r in rows if r['metadata'].get('environment')=='business-workflow' and r['metadata'].get('training_step')==1]
                require(any(r['outcome'].get('recorded_reward') is None for r in pending), 'Partial JSONL tail was consumed')
                with file.open('ab') as stream:stream.write(b'\n')
            expected=(step+1)*8
            snap=wait_for(lambda:dashboard(expected), 'live graph measurements for batch '+str(step), timeout=90)
            # Every environment has 3 observed retry opportunities and 1 unobserved case.
            target=[1/3,0,1][step]
            for monitor in snap['monitors']:
                if monitor['id'] not in {m['id'] for m in monitors.values()}:continue
                bins=[b for series in monitor['series'] for b in series['bins'] if b['step']==step]
                require(len(bins)==2, 'Environments were incorrectly mixed or a training batch was lost')
                for b in bins:
                    require(b['value']==target and b['denominator']==3, 'Wrong retry rate or denominator: '+str(b))
                    require(b['unknown_opportunities']>0, 'Unobserved retries were converted to failures')
            health=server.request('/api/training-health?'+urlencode(dict(experiment=EXPERIMENT,monitor=monitors['next_check_success_changed']['id'])))
            require(sum(c['samples'] for c in health['cohorts'])==expected, 'Training sample joins lost members')
            for cohort in health['cohorts']:
                require(cohort['missing_source']==0, 'A training sample did not bind to its exact rollout revision')
                behavior=cohort['behavior_timeline']['points']
                require([p['step'] for p in behavior]==list(range(step+1)), 'Generation clock is incorrect')
                require(behavior[-1]['pooled_opportunities']['value']==target, 'Training view disagrees with monitor')
                rewards=cohort['rewards'][0]['points']
                require(rewards[-1]['constant_groups']['value']==int(step==1), 'Constant-reward group diagnosis is incorrect')
                uses=cohort['uses'][0]['behavior_timeline']['points']
                require([p['step'] for p in uses]==[100+10*n for n in range(step+1)], 'Learner and generation clocks were mixed')
            phase('batch_'+str(step), rollouts=expected, next_check_success_after_change=target,
                  opportunities_per_environment=3, missing_retry_kept_unknown=True)
            if step==0:
                wait_for(lambda:any(s['source_revision']!=baseline_revision for s in live.states), 'pushed source change')
                phase('server_push', events=len(live.states), changed_without_dashboard_poll=True)

        ws=Workspace(server.db,experiment=EXPERIMENT,observer='source')
        rows=ws.rollouts().rows
        require(len(rows)==24, 'Final population mismatch')
        require(not ws.units().rows, 'Source-only ingestion must not invent semantic tags')
        # Reading the actual UI data contract must expose the metric and its exact graph evidence.
        snapshot=wait_for(lambda:dashboard(24),'final dashboard')
        changed=next(m for m in snapshot['monitors'] if m['id']==monitors['next_check_success_changed']['id'])
        point=next(p for s in changed['series'] for p in s['points'] if p['step']==2 and p['value']==1)
        evidence=server.request('/api/monitoring/values/'+point['value_id'])
        require(evidence['explanation']['analysis_cases'], 'No evidence behind the displayed measurement')
        view=server.request('/api/monitoring/rollout/'+point['run_id']+'?observer=source')
        # A measurement links its versioned derived evidence graph, not the
        # plain source-only graph. Read the same graph that its UI link opens.
        graph=Workspace(server.db,experiment=EXPERIMENT).graph(evidence['graph']['id'])
        require(any(e['type']=='recorded_recheck_of' for e in graph.edges), 'Recovery cannot be followed in the map')
        before_values=[p['value_id'] for s in changed['series'] for p in s['points']]
        mirror=FeedMirror(Analysis(server.db),root/'consumer.sqlite')
        first=mirror.sync(feeds=['revisions'])
        require(mirror.sync(feeds=['revisions'])['feeds'][0]['inserted']==0, 'Feed resume duplicated receipts')
        require(first['feeds'][0]['inserted']==48, 'History should retain both lifecycle revisions of all rollouts')
        custom=ws.evaluate('simulation_summary',lambda row,config:dict(reward=row['outcome'].get('recorded_reward')),version='1')
        require(server.request('/api/analysis/custom/'+custom['id'])['rows'], 'Custom Python results not exposed through HTTP')
        require(server.request('/api/analysis/compute?function=recorded_outcomes&experiment='+EXPERIMENT)['rows']==ws.recorded_outcomes().rows,
                'HTTP and Python disagree on recorded outcomes')
        cli=server.cli('--db',server.db,'analysis','table','rollouts','--experiment',EXPERIMENT)
        require(len(cli['rows'])==24, 'CLI output population mismatch')
        for fmt in ['jsonl','csv']:
            raw=server.request('/api/analysis/export?'+urlencode(dict(experiment=EXPERIMENT,format=fmt)),raw=True)
            (root/f'analysis-{fmt}.zip').write_bytes(raw)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                manifest=json.loads(archive.read('manifest.json'))
                require(manifest['tables']['rollouts']['rows']==24, 'Export lost rollout rows')
        # Duplicate delivery and older revisions must leave measurements unchanged.
        duplicate=dict(producer='sdk',rollout_id='batch-2/sample-0',revision=1,state='complete',document=document(2,0,'terminal'))
        require(not server.request('/api/ingest',duplicate)['received'],'Duplicate HTTP delivery created a revision')
        new=wait_for(lambda:dashboard(24),'idempotent final dashboard')
        after=next(m for m in new['monitors'] if m['id']==changed['id'])
        require(before_values==[p['value_id'] for s in after['series'] for p in s['points']], 'Replay changed immutable measurement receipts')
        phase('diagnose_and_analyze', exact_case_links=True, typed_map_edges=len(graph.edges),
              python_http_cli_agree=True, custom_result=custom['id'], retained_revisions=48,
              semantic_extraction='not run; missing tags remain missing')
        archive=root/'inspection.rilldex.zip'
        archive.write_bytes(server.request('/api/workspace/snapshot',raw=True))
        restored=root/'restored.sqlite'
        receipt=server.cli('--db',restored,'workspace','restore',archive)
        require(receipt['status']=='restored' and not receipt['inference_started'], 'Restore unexpectedly started inference')
        copy=Workspace(restored,experiment=EXPERIMENT,observer='source')
        require(copy.rollouts().rows==rows, 'Workspace transfer changed sources')
        require(Workspace(restored,experiment=EXPERIMENT).graph(graph.graph_id).edges==graph.edges, 'Workspace transfer changed graph evidence')
        phase('post_training', snapshot_restored=True, graph_identity_preserved=True, outputs=['live SQL/Python','HTTP','CLI','JSONL','CSV','workspace archive'])
        report.update(status='passed', rollouts=24, source_revisions=48, database=str(server.db),
                      map_run=point['run_id'], map_graph=graph.graph_id, value_id=point['value_id'], monitor=changed['id'], expected_retry_curve=[1/3,0,1],
                      boundaries=['Synthetic state evidence; semantic model accuracy is untested',
                                  'No optimizer, inference server, GPU or multi-host cluster was executed',
                                  'OS coverage is the recorded platform only'])
        return report
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        if live:live.close()
        server.stop()
        (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='New directory in which to retain the workspace, evidence, exports and report')
    args=parser.parse_args()
    if args.output:
        print(json.dumps(run(args.output.resolve()),indent=2))
    else:
        with tempfile.TemporaryDirectory(prefix='rilldex RL simulation ') as tmp:
            print(json.dumps(run(Path(tmp)/'Unicode Ω workspace'),indent=2))
