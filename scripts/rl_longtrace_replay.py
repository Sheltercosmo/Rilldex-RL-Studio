"""End-to-end replay of three retained real long traces through the installed SDK.

This exercises collection, revisions, the durable Outbox, live events, source
metrics, declared cohorts and training lineage. Replay clocks and test-only
training facts are synthetic; this is not a trainer run or a semantic-accuracy
evaluation. Trace text is recorded as data and is never executed.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import tempfile
import time
from urllib.request import Request, urlopen

import rilldex
from rilldex import Outbox, Workspace

try:
    from .rl_lifecycle_simulation import LiveEvents, Server, require, wait_for
except ImportError:
    from rl_lifecycle_simulation import LiveEvents, Server, require, wait_for


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'longtrace-replay'
PRODUCER = 'longtrace-replay'
PREFIX_COUNT = 8
MONITORS = {
    'actions': ('metric', 'actions', 'Recorded actions'),
    'repeats': ('metric', 'exact_dispatch_repeat_rate', 'Exact repeated dispatches'),
    'reward': ('metric', 'recorded_reward', 'Source reward'),
    'success': ('metric', 'recorded_success', 'Source success'),
}

SOURCES = {
    'swe-druid': dict(
        run_id='68f4f4de60c1226d7d896ae8',
        path='research/public-rl-2026-10-06/sweagent--iter2-rl-rollouts/archive-prefix-sample/apache__druid-15402_1400000.json',
        format='swe-rl', environment='swe-rl', task_id='apache__druid-15402',
        source_collection='sweagent/iter2-rl-rollouts',
        annotations={
            'retained_run':'research/base-unit-content-v2-2026-10-07/runs/68f4f4de60c1226d7d896ae8.json',
            'curated_candidate':'research/base-unit-content-v2-2026-10-07/observations/68f4f4de60c1226d7d896ae8-u9c28aa621a517badef73.json',
            'coverage':'One curated observation only; no whole-run semantic coverage or stable observer ID.',
            'reference_boundary':'A separate normalized snapshot has caller-paired grading, but the native replay source has no target/reward field; grading is not propagated.'}),
    'devai-openhands': dict(
        run_id='23a6f4b7c76c919e74ae6d50',
        path='research/work-paths-2026-10-07/runs/23a6f4b7c76c919e74ae6d50.json',
        format='devai', environment='devai-openhands', task_id='DevAI:39_Drug_Response_Prediction_SVM_GDSC_ML',
        source_collection='DevAI/OpenHands',
        annotations={
            'retained_extraction':'research/semantic-extraction-2026-10-07/results/23a6f4b7c76c919e74ae6d50.json',
            'unit_coverage':'68 selected units over 67 windows; whole-run local extraction; behavioral-unit-standard/2.',
            'relationships':['13 plan-stage correspondences in research/work-paths-2026-10-07/plan_relations/23a6f4b7c76c919e74ae6d50/plan-stage-correspondence-2/ea8e90d6ae81714517590fe7fc5405686c6110452a6412b4f6332bc196e91dd6.json',
                '12 action-target correspondences in research/work-paths-2026-10-07/action_targets/23a6f4b7c76c919e74ae6d50/action-target-correspondence-4/target-meaning-and-shared-tools-1/ea8e90d6ae81714517590fe7fc5405686c6110452a6412b4f6332bc196e91dd6.json'],
            'provenance':'Assistant-authored selected candidates and implementation-assistant source review; not independent labels or live observer output.'}),
    'tau2-airline': dict(
        run_id='d8c0e38f633a068fbc7aed74',
        path='research/contribution-boundaries-2026-10-07/runs/d8c0e38f633a068fbc7aed74.json',
        format='agent-process-bench', environment='tau2_airline', task_id='tau2_airline:query-750',
        source_collection='AgentProcessBench', source_record_id=750,
        annotations={
            'retained_extraction':'research/work-purpose-2026-10-08/airline/results/d8c0e38f633a068fbc7aed74.json',
            'unit_coverage':'30 selected units over 29 windows; extraction is a selected model-candidate set, not whole-run coverage.',
            'relationship':'8 action-target correspondences in research/work-purpose-2026-10-08/airline/action_targets/d8c0e38f633a068fbc7aed74/action-target-correspondence-3/target-meaning-and-shared-tools-1/9c0151e1eb0f17ef2c00a60b7300ea74cb38e2e35290029881b8916ffc320937.json',
            'reference_boundary':'Original AgentProcessBench step/final labels are retained as source reference annotations; they are not semantic activity labels, rewards or verified-success fields.'}),
}


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_source(name, spec):
    path = ROOT / spec['path']
    if not path.is_file():
        raise FileNotFoundError(f"Missing retained source for {name}: {path}")
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    spec = {**spec, 'sha256': sha256(path), 'file_bytes': path.stat().st_size}
    if name == 'devai-openhands':
        native = {'trajectory_format':'devai/1', 'trajectory':value['raw']['trajectory']}
        total = len(native['trajectory'])
        events = value['events']
        prefixes = [max(1, round(total * (i + 1) / PREFIX_COUNT)) for i in range(PREFIX_COUNT)]
        get_doc = lambda n: {**native, 'trajectory':native['trajectory'][:n]}
        event_count = lambda n: sum(1 for e in events if pointer_index(e) < n)
        raw_events = events
    elif name == 'tau2-airline':
        native = value['raw']
        total = len(native['messages'])
        prefixes = [max(1, round(total * (i + 1) / PREFIX_COUNT)) for i in range(PREFIX_COUNT)]
        events = value['events']
        def get_doc(n):
            doc = dict(native)
            doc['messages'] = native['messages'][:n]
            doc['step_labels'] = {k:v for k,v in native['step_labels'].items() if int(k) < n}
            if n != total:
                doc.pop('final_label', None)
            return doc
        event_count = lambda n: sum(1 for e in events if pointer_index(e) < n)
        raw_events = events
    else:
        # This workspace retains both the original native SWE-RL archive record
        # and its normalized trace. Replay the original messages, preserving all
        # source fields at completion and withholding terminal-only fields from
        # earlier prefixes.
        native = value
        total = len(native['messages'])
        prefixes = [max(1, round(total * (i + 1) / PREFIX_COUNT)) for i in range(PREFIX_COUNT)]
        norm_path = ROOT / 'research/base-unit-content-v2-2026-10-07/runs/68f4f4de60c1226d7d896ae8.json'
        normalized = json.loads(norm_path.read_text(encoding='utf-8'))
        events = normalized['events']
        def get_doc(n):
            doc = dict(native)
            doc['messages'] = native['messages'][:n]
            doc['n_steps'] = sum(m.get('role') == 'assistant' for m in doc['messages'])
            if n != total:
                for key in ('model_patch','exit_status','all_tokens_length','prompt_token_ids','response_token_ids','loss_mask','env_creation_time'):
                    doc.pop(key, None)
                doc['exit_status'] = None
            return doc
        event_count = lambda n: sum(1 for e in events if pointer_index(e) < n)
        raw_events = events
    spec.update(source_messages=total, source_events=len(raw_events),
        source_event_bytes=sum(len(json.dumps(e,ensure_ascii=False,separators=(',',':')).encode('utf-8')) for e in raw_events),
        approximate_tokens=round(sum(len(json.dumps(e,ensure_ascii=False,separators=(',',':')).encode('utf-8')) for e in raw_events)/4),
        source_event_text_hash=source_hash_text(raw_events),
        prefix_messages=prefixes, prefix_events=[event_count(n) for n in prefixes])
    return spec, get_doc, prefixes


def pointer_index(event):
    match = re.match(r'^/(?:trajectory|messages)/(\d+)(?:/|$)', event.get('source_pointer',''))
    return int(match.group(1)) if match else 0


def outbox_snapshot(name, twin, doc, fmt, prefix_index):
    doc = dict(doc)
    md = dict(experiment=EXPERIMENT, training_clock='replay/arrival',
        training_step=twin, training_step_basis='replay batch',
        task_id=SOURCES[name]['task_id'], source_run_id=SOURCES[name]['run_id'],
        source_window=f'prefix-{prefix_index+1}-of-{PREFIX_COUNT}',
        replay_role='baseline' if twin == 0 else 'current',
        replay_notice='Synthetic ordered replay window; no trainer or optimizer executed.')
    rollout = f'{name}-step-{twin}'
    return dict(rollout_id=rollout, document=doc,
        state='complete' if prefix_index == PREFIX_COUNT-1 else 'in_progress',
        format=fmt, metadata=md)


def source_hash_text(events):
    return hashlib.sha256(json.dumps([
        (e.get('kind'),e.get('actor'),e.get('tool'),e.get('text'),e.get('arguments'))
        for e in events],ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def source_training_records(name, spec, producer):
    rows=[]
    for step in (0,1):
        rid=f'{name}-step-{step}'; sample=f'{name}-window-{step}'
        env=spec['environment']
        def rec(kind,data):
            return dict(id=f'{kind}/{sample}',revision=0,kind=kind,
                sample=dict(producer=producer,id=sample),
                evidence=dict(basis='Synthetic replay lineage fact; no trainer or optimizer executed.'),data=data)
        data=dict(split='train',group_id=f'{name}-paired-source',group_size=2,
            step=step,step_basis='replay batch',policy_version=f'replay-window-{step}',
            environment=env,source=dict(producer=f'{producer}-{step}',rollout_id=rid,revision=PREFIX_COUNT-1))
        if spec.get('source_record_id') is not None: data['task_id']=spec['task_id']
        rows.append(rec('sample',data))
        rows.append(rec('selection',dict(filter='replay-control',definition='synthetic-replay/1',
            decision='admitted',batch_id=f'{name}-paired-source')))
        # Explicit test-only optimizer-use facts are symmetric across twins and
        # intentionally absent for other source pairs.
        if name=='swe-druid':
            rows.append(rec('use',dict(batch_id=f'{name}-test-only-use',learner_step=step,
                stage='optimizer_step_completed',model_tokens=0,loss_tokens=0,advantage=0.0)))
    return rows


def report_prefix(root, report):
    path=root/'report.json'
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')


def run(root=None, keep_server=False, pause_after_partial=False):
    require('site-packages' in str(Path(rilldex.__file__).resolve()),
        'Install the wheel into a clean venv, then run this script with that interpreter.')
    if root is None:
        root=Path(tempfile.mkdtemp(prefix='rl-longtrace-replay-'))
    else:
        root=Path(root).resolve()
        require(not root.exists() or not any(root.iterdir()), 'Use a new or empty work directory; existing files are preserved.')
    root.mkdir(parents=True,exist_ok=True)
    output=root/'outputs';output.mkdir()
    loaded={name:read_source(name,spec) for name,spec in SOURCES.items()}
    report=dict(schema='rl-longtrace-replay/1',synthetic_scheduler=True,
        no_trainer_executed=True,no_model_or_inference_calls=True,
        package=str(Path(rilldex.__file__).resolve()),python=platform.python_version(),
        experiment=EXPERIMENT,training_clock='replay/arrival',training_step_basis='replay batch',
        source_fixtures={k:v[0] for k,v in loaded.items()},
        logical_rollouts=6,expected_final_events=sum(v[0]['source_events']*2 for v in loaded.values()),
        prefix_deliveries=0,phases=[],unknowns=['No fresh semantic model call was made.','APB reference labels are not reward or verified-success fields.',
        'SWE-RL native source lacks a target/reward; a separate caller-paired grading annotation is excluded from replay.'])
    started=time.monotonic()
    def phase(name,**extra):
        row=dict(name=name,seconds=round(time.monotonic()-started,3),**extra)
        report['phases'].append(row);report_prefix(root,report);print(json.dumps(row),flush=True)
    server=Server(root,experiment=EXPERIMENT)
    live=None
    boxes={}
    try:
        server.start()
        require(server.request('/api/health')['ready'],'Installed collector did not become ready')
        live=LiveEvents(server.url);wait_for(lambda:live.states,'initial SSE state')
        monitors={}
        for key,(kind,metric,label) in MONITORS.items():
            definition=dict(name='Long trace · '+label,kind=kind,observer='source',
                population=dict(experiment=EXPERIMENT),group='Behavior')
            definition['metric']=metric
            monitors[key]=server.request('/api/monitoring/monitors',{'definition':definition})
        report['monitor_ids']={k:v['id'] for k,v in monitors.items()}
        for name in SOURCES:
            for twin in (0,1):
                producer=f'{PRODUCER}-{name}-{twin}'
                boxes[(name,twin)]=Outbox(root/'outboxes'/producer/'outbox.sqlite',producer=producer,endpoint=server.url)
        lag_key=('tau2-airline',1); reordered_key=('devai-openhands',0)
        queued={k:[] for k in boxes};first_live=len(live.states);reordered=False;lagged=False
        for prefix_index in range(PREFIX_COUNT):
            for name,(spec,get_doc,prefixes) in loaded.items():
                for twin in (0,1):
                    key=(name,twin);box=boxes[key]
                    snapshot=outbox_snapshot(name,twin,get_doc(prefixes[prefix_index]),spec['format'],prefix_index)
                    receipt=box.log(**snapshot);queued[key].append(receipt['revision'])
                    report['prefix_deliveries']+=1
                    # Leave one producer behind through five windows, then let
                    # its intact durable queue catch up after other traces move.
                    if key==lag_key and prefix_index<4:
                        lagged=True;continue
                    # Deliver a future revision early using the exact queued
                    # Outbox envelope; later Outbox drain retries it as a
                    # duplicate after older revisions arrive.
                    if key==reordered_key and prefix_index==2:
                        with box.connect() as c:
                            payload=c.execute('SELECT payload FROM queue WHERE rollout=? AND revision=2',
                                (snapshot['rollout_id'],)).fetchone()[0]
                        envelope=json.loads(payload)
                        early_receipt=server.request('/api/ingest',envelope)
                        require(early_receipt.get('revision')==2,'Out-of-order future revision was not acknowledged')
                        reordered=True
                    result=box.drain(limit=100)
                    require(result['pending']==0 or key==reordered_key,
                        f'Outbox did not drain {key}: {result}')
                if prefix_index==3:
                    # Stop and restart the installed server while its durable
                    # producer queues are still active; retain the same DB and
                    # Outbox files, then reconnect SSE.
                    live.close();live=None;server.stop();server.start()
                    live=LiveEvents(server.url);wait_for(lambda:live.states,'SSE reconnect after server restart')
                    # Outbox instances retain their original endpoint; reopen
                    # their durable queues against the restarted listener.
                    boxes={key:Outbox(root/'outboxes'/f'{PRODUCER}-{key[0]}-{key[1]}'/'outbox.sqlite',
                        producer=f'{PRODUCER}-{key[0]}-{key[1]}',endpoint=server.url) for key in boxes}
                if prefix_index==4:
                    result=boxes[lag_key].drain(limit=100)
                    require(result['pending']==0,'Lagging producer did not catch up')
            phase('prefix_round',prefix=prefix_index+1,
                current_prefix_events={name:spec['prefix_events'][prefix_index] for name,(spec,_,_) in loaded.items()},
                lagged_producer_caught_up=prefix_index>=4,server_restarted=prefix_index==3)
            if prefix_index==PREFIX_COUNT-2:
                active=server.request('/api/monitoring?experiment='+EXPERIMENT)['active_captures']
                expected=Counter(spec['prefix_events'][prefix_index]
                    for spec,_,_ in loaded.values() for _ in (0,1))
                actual=Counter(row['event_count'] for row in active['rows'])
                require(active['total']==6 and len(active['rows'])==6,
                    f'Expected six active source prefixes, got {active["total"]} total/{len(active["rows"])} rows')
                require(actual==expected,f'Active prefix event counts differ: {actual} != {expected}')
                report['active_prefix_check']={'total':active['total'],'rows':active['rows'],
                    'expected_event_counts':dict(expected),'checked_at':'penultimate source prefix'}
            if pause_after_partial and prefix_index==PREFIX_COUNT-2:
                pause_path=root/'pause.json';continue_path=root/'continue.json'
                pause_path.write_text(json.dumps({'preview_url':server.url,
                    'state':'all six rollouts have the penultimate source prefix; final prefix not delivered',
                    'continue_file':str(continue_path)},indent=2)+'\n',encoding='utf-8')
                print(json.dumps({'name':'paused_for_browser_review','preview_url':server.url,
                    'state':'penultimate prefixes visible; create continue.json to deliver final prefixes',
                    'continue_file':str(continue_path),'timeout_seconds':300}),flush=True)
                deadline=time.monotonic()+300
                while not continue_path.exists() and time.monotonic()<deadline:time.sleep(.25)
                require(continue_path.exists(),'Timed out waiting for browser-review continuation file')
                report['browser_review_resume']=continue_path.read_text(encoding='utf-8')[:2000]
                phase('browser_review_resumed')
        # Flush all remaining queues; the out-of-order revision is delivered
        # again by Outbox, which verifies idempotent duplicate transport.
        for key,box in boxes.items():
            result=box.drain(limit=100)
            require(result['pending']==0 and result['blocked']==0,f'Outbox remains undelivered for {key}: {result}')
        require(reordered and lagged,'Transport controls were not exercised')
        final_active=server.request('/api/monitoring?experiment='+EXPERIMENT)['active_captures']
        require(final_active['total']==0,f'Completed source rollouts remain active: {final_active["total"]}')
        report['active_prefix_completion_check']={'total':final_active['total'],'checked_after_final_prefix':True}
        report['transport_controls']={'temporary_lag':'tau2-airline-step-1 held through prefix 4 then drained',
            'out_of_order_duplicate':'devai-openhands-step-0 revision 2 sent ahead of revisions 0–1, then resent by Outbox',
            'server_restart':'same workspace SQLite and Outbox files retained at prefix round 4'}
        wait_for(lambda:len(live.states)>first_live+2,'SSE events after resumed replay')
        report['sse_events']=len(live.states)

        # Send declared completed cohorts only after all six sources reached
        # their complete revision. Their scheduler clock is explicitly replay.
        cohort_producer=PRODUCER+'-scheduler'
        cohorts=[]
        for name,spec in ((k,v[0]) for k,v in loaded.items()):
            for twin in (0,1):
                cohorts.append(dict(id=f'{name}-batch-{twin}',revision=0,label=f'{name} replay batch {twin}',
                    coordinate=dict(clock='replay/arrival',basis='replay batch',index=twin),
                    context=dict(split='train',environment=spec['environment']),sealed=True,
                    members=[dict(producer=f'{PRODUCER}-{name}-{twin}',rollout_id=f'{name}-step-{twin}',
                        generation_state='completed',context=dict(task_id=spec['task_id'],environment=spec['environment']))],
                    evidence='Synthetic replay scheduler declaration; not actual training membership.'))
        cohort_box=Outbox(root/'outboxes'/cohort_producer/'outbox.sqlite',producer=cohort_producer,endpoint=server.url)
        cohort_box.log_cohorts(EXPERIMENT,cohorts);cohort_box.drain(limit=20)

        training_producer=PRODUCER+'-lineage'
        training_box=Outbox(root/'outboxes'/training_producer/'outbox.sqlite',producer=training_producer,endpoint=server.url)
        # Each training record source must use the same producer identity as its
        # rollout. Keep one packet per trace pair so exact source joins work.
        for name,(spec,_,_) in loaded.items():
            prod=f'{PRODUCER}-{name}'
            rows=source_training_records(name,spec,prod)
            training_box.log_training(EXPERIMENT,rows,schema='training-records/2')
        training_box.drain(limit=20)

        rows=[];event_summaries={};content_fingerprints={}
        db=sqlite3.connect(f'file:{server.db}?mode=ro',uri=True)
        db.row_factory=sqlite3.Row
        revisions=db.execute("SELECT producer,rollout_id,revision,state,run_id FROM rollout_revisions ORDER BY producer,rollout_id,revision").fetchall()
        require(len(revisions)==PREFIX_COUNT*6,'Not all ordered prefix revisions reached server')
        for name,(spec,_,_) in loaded.items():
            twin_rows=[]
            for twin in (0,1):
                producer=f'{PRODUCER}-{name}-{twin}';rollout=f'{name}-step-{twin}'
                latest=db.execute('''SELECT r.document,r.analysis,rr.revision,rr.state FROM runs r JOIN rollout_revisions rr ON r.id=rr.run_id
                    WHERE rr.producer=? AND rr.rollout_id=? ORDER BY rr.revision DESC LIMIT 1''',(producer,rollout)).fetchone()
                require(latest is not None and latest['revision']==PREFIX_COUNT-1 and latest['state']=='complete',f'Missing complete source {rollout}')
                doc=json.loads(latest['document']);analysis=json.loads(latest['analysis']);events=doc['events']
                expected_event_count=spec['source_events']
                require(len(events)==expected_event_count,f'Final event count changed for {rollout}: {len(events)} != {expected_event_count}')
                text_hash=source_hash_text(events);content_fingerprints[rollout]=text_hash
                expected_hash=spec['source_event_text_hash']
                require(text_hash==expected_hash,f'Final event text/action projection changed for {rollout}')
                server.request('/api/monitoring/rollout/'+doc['id']+'?observer=source')
                source_row=dict(run_id=doc['id'],events=len(events),revision=latest['revision'],state=latest['state'],
                    metadata=doc['metadata'],outcome=doc['outcome'],text_hash=text_hash,
                    analysis_metrics=analysis.get('metrics',{}))
                rows.append(source_row);twin_rows.append(source_row)
                event_summaries[rollout]=dict(events=len(events),actions=sum(e.get('kind')=='action' and e.get('actor')=='agent' for e in events),
                    agent_event_bytes=sum(len(e.get('text','').encode('utf-8')) for e in events if e.get('actor')=='agent'),
                    repeated_actions=analysis.get('metrics',{}).get('exact_repeats'),
                    source_success=analysis.get('metrics',{}).get('recorded_success'),
                    source_reward=analysis.get('metrics',{}).get('recorded_reward'))
            require(twin_rows[0]['text_hash']==twin_rows[1]['text_hash'],f'No-change twins differ in event text: {name}')
            require(twin_rows[0]['analysis_metrics']['actions']==twin_rows[1]['analysis_metrics']['actions'],f'Action monitor differs for twin pair {name}')
            require(twin_rows[0]['analysis_metrics']['exact_repeats']==twin_rows[1]['analysis_metrics']['exact_repeats'],f'Repeat monitor differs for twin pair {name}')
        db.close()
        report['final_rollouts']=rows;report['source_metrics']=event_summaries
        report['content_fingerprints']=content_fingerprints
        report['twin_checks']='All baseline/current pairs have identical event-text/action/repeat evidence; monitor compares are no-change controls.'
        report['cohort_count']=len(cohorts)
        report['lineage_records']=sum(len(source_training_records(name,spec,f'{PRODUCER}-{name}')) for name,(spec,_,_) in loaded.items())
        report['training_facts_boundary']='Synthetic sample, selection and symmetric test-only optimizer-use records. No score was created because native sources have no reward; no optimizer actually ran.'

        comparisons=[]
        for name,spec in ((k,v[0]) for k,v in loaded.items()):
            for key in ('actions','repeats','reward','success'):
                comparison=server.request('/api/monitoring/comparisons',dict(monitor_id=monitors[key]['id'],
                    experiment=EXPERIMENT,environment=spec['environment'],baseline=[0,0],current=[1,1]))
                saved=server.request('/api/monitoring/comparisons/'+comparison['id'])
                require(saved==comparison,'Saved comparison changed after retrieval')
                if key in ('actions','repeats'):
                    require(comparison['mix'].get('available') is True and comparison['mix'].get('observed_delta')==0,
                        f'No-change twin comparison reported a change for {name}/{key}')
                if key in ('reward','success'):
                    require(comparison['mix'].get('available') is False,
                        f'Unavailable source reward/success became available for {name}/{key}')
                comparisons.append(dict(source=name,monitor=key,id=comparison['id'],
                    population=comparison['population'],cohorts=len(comparison.get('cohorts',[])),
                    baseline=comparison['mix'].get('baseline'),current=comparison['mix'].get('current'),
                    observed_delta=comparison['mix'].get('observed_delta'),
                    measured_coverage=comparison['mix'].get('available')))
        report['api_comparisons']=comparisons
        health=server.request('/api/training-health?'+__import__('urllib.parse').parse.urlencode({'experiment':EXPERIMENT}))
        report['training_health']=health
        report['declared_population']=server.request('/api/generation-cohorts?'+__import__('urllib.parse').parse.urlencode({'experiment':EXPERIMENT}))
        report['timings']={'total_seconds':round(time.monotonic()-started,3),'server_starts':server.starts,
            'request_counts':server.request_counts}
        report['preview_url']=server.url+'/?experiment='+EXPERIMENT if keep_server else None
        report['work_dir']=str(root)
        report['status']='passed'
        report_prefix(root,report)
        print(json.dumps(report,indent=2,ensure_ascii=True),flush=True)
        if keep_server:
            print('Server kept alive; stop it with Ctrl+C only if launched interactively.',flush=True)
            return report
        return report
    except Exception as exc:
        report['status']='failed';report['error']=f'{type(exc).__name__}: {exc}'
        report['timings']={'total_seconds':round(time.monotonic()-started,3),'server_starts':server.starts}
        report_prefix(root,report)
        raise
    finally:
        if live and not keep_server:live.close()
        if not keep_server:server.stop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir',help='New or empty directory for isolated DB, logs and JSON report')
    parser.add_argument('--keep-server',action='store_true',help='Keep collector live and include its preview URL')
    parser.add_argument('--pause-after-partial',action='store_true',help='Pause at penultimate prefixes for browser review; create continue.json in work dir to resume (300s timeout)')
    args=parser.parse_args()
    run(args.work_dir,args.keep_server,args.pause_after_partial)


if __name__=='__main__':
    main()
