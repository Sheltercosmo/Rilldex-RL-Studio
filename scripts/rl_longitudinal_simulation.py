"""Longitudinal acceptance scenarios with independently authored expected findings.

Uses actual ingestion, monitoring, graph evidence and research interfaces. This
is synthetic observation validation, not a trainer or semantic accuracy test.
Run from a Python environment with the Rilldex package installed.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import platform
import random
import statistics
import time
from urllib.parse import urlencode

import rilldex
from rilldex import Outbox, Workspace, chat_document
from tracker.state_capture import WorkStateRecorder, call_ref, object_version

if __package__:
    from .rl_lifecycle_simulation import Server, LiveEvents, require, wait_for
else:
    from rl_lifecycle_simulation import Server, LiveEvents, require, wait_for

EXPERIMENT = 'longitudinal-behavior-training'
PHASES = ['baseline', 'improvement', 'plateau', 'terminal_regression',
          'costly_recovery', 'reward_and_coverage_gap', 'stable_comparison', 'environment_mix_shift']
# Independently authored denominators: the final failing check has no next check
# and is unknown, not a negative. A later passing retry cannot replace an earlier failure.
EXPECTED = {
    'clean': dict(all=(1,1), changed=(1,1), unchanged=(0,0), unknown=0, success=1),
    'stuck': dict(all=(0,1), changed=(0,1), unchanged=(0,0), unknown=1, success=0),
    'retry_then_fix': dict(all=(1,2), changed=(1,1), unchanged=(0,1), unknown=0, success=1),
    'revise_twice': dict(all=(1,2), changed=(1,2), unchanged=(0,0), unknown=0, success=1),
    'unobserved': dict(all=(0,0), changed=(0,0), unchanged=(0,0), unknown=1, success=0),
}
OPERATIONS = {
    'clean': ['failed', 'edit', 'passed'],
    'stuck': ['failed', 'edit', 'failed'],
    'retry_then_fix': ['failed', 'failed', 'edit', 'passed'],
    'revise_twice': ['failed', 'edit', 'failed', 'edit', 'passed'],
    'unobserved': ['failed'],
}
MEASURES = {
    'all': ('analysis', 'next_check_success', 'First recheck success'),
    'changed': ('analysis', 'next_check_success_changed', 'Recheck success after input change'),
    'unchanged': ('analysis', 'next_check_success_unchanged', 'Recheck success without input change'),
    'success': ('metric', 'recorded_success', 'Source task success'),
    'reward': ('metric', 'recorded_reward', 'Logged reward'),
    'actions': ('metric', 'actions', 'Actions per rollout'),
}


def scenario(steps=64, samples=16, seed=17):
    if steps < 16 or steps % 8 or samples < 16 or samples % 16:
        raise ValueError('Use at least 16 steps (multiple of 8) and 16 samples per step (multiple of 16)')
    rng=random.Random(seed); width=steps//8; result=[]
    for step in range(steps):
        phase=step//width; progress=(step%width)/(width-1)
        terminal=samples//2 if phase!=7 else samples*(3 if progress<.5 else 1)//4
        batch=[]
        for env,count in [('terminal',terminal),('business-workflow',samples-terminal)]:
            if phase==0: template=['clean','stuck','unobserved','retry_then_fix']
            elif phase==1:
                # A gradual change in the generator, not a fitted model claim.
                template=['clean' if i/4 < .25+.5*progress else 'stuck' for i in range(4)]
            elif phase==2: template=['clean']*(3 if env=='terminal' else 2)+['stuck']*(1 if env=='terminal' else 2)
            elif phase==3: template=['stuck']*4 if env=='terminal' else ['clean','clean','stuck','stuck']
            elif phase==4: template=['retry_then_fix','revise_twice','revise_twice','clean'] if env=='terminal' else ['clean','clean','stuck','stuck']
            elif phase==5: template=['stuck','unobserved','clean','stuck'] if env=='terminal' else ['unobserved','unobserved','clean','stuck']
            else: template=['clean','clean','clean','stuck'] if env=='terminal' else ['clean','stuck','stuck','stuck']
            patterns=template*(count//4);rng.shuffle(patterns)
            for index,pattern in enumerate(patterns):
                batch.append(dict(step=step,phase=PHASES[phase],environment=env,index=index,pattern=pattern,
                    producer='sdk' if env=='terminal' else 'files',id=f'batch-{step}/sample-{index}',
                    reward=1 if phase==5 and env=='terminal' else EXPECTED[pattern]['success'],
                    # Stragglers cross step/phase boundaries. Generation and arrival order differ.
                    due=step+2 if env=='terminal' and index==0 and phase in (2,3,4) else step))
        result.append(batch)
    return result


def document(row, partial=False):
    metadata=dict(experiment=EXPERIMENT,environment=row['environment'],environment_version='simulation/2',
        task_id='repair-record',split='train',training_step=row['step'],training_step_basis='generation',
        policy_version=f"policy-{row['step']//4}")
    messages=[dict(role='user',content='Repair the record and confirm it satisfies the validity criterion.')]
    recorder=WorkStateRecorder(environment=row['environment']+'/simulation-2');state=0
    for n,operation in enumerate(['failed'] if partial else OPERATIONS[row['pattern']]):
        cid=f'call-{n}';action=call_ref(cid);result=call_ref(cid,result=True)
        editing=operation=='edit';tool='edit_record' if editing else 'check_record'
        messages.append(dict(role='assistant',content='Correct the record.' if editing else 'Check the record.',
            tool_calls=[dict(id=cid,type='function',function=dict(name=tool,arguments='{}'))]))
        before=recorder.snapshot(action,{'record':object_version(state)})
        if editing:
            state+=1;messages.append(dict(role='tool',tool_call_id=cid,content='Record changed.'))
            after=recorder.snapshot(result,{'record':object_version(state)})
            recorder.edit(action,result,before=before,after=after)
        else:
            messages.append(dict(role='tool',tool_call_id=cid,content=operation))
            recorder.check(action,result,snapshot=before,criterion_id='record-valid',criterion_version='1',
                required_objects=['record'],outcome=operation,state_stable=True)
    return recorder.attach(chat_document(messages,metadata=metadata,
        reward=None if partial else row['reward'],success=None if partial else bool(EXPECTED[row['pattern']]['success'])))


def facts(batch,producer):
    rows=[r for r in batch if r['producer']==producer];records=[]
    for row in rows:
        def record(kind,data):
            return dict(id=kind+'/'+row['id'],revision=0,kind=kind,
                sample=dict(producer=producer,id=row['id']),
                evidence=dict(basis='Authored longitudinal scenario; no optimizer executed'),data=data)
        records.extend([
            record('sample',dict(split='train',group_id=f"group-{row['step']}",group_size=len(rows),
                step=row['step'],step_basis='generation',policy_version=f"policy-{row['step']//4}",
                environment=row['environment'],environment_version='simulation/2',
                source=dict(producer=producer,rollout_id=row['id'],revision=1))),
            record('score',dict(component='validity',definition='simulated-score/2',status='scored',value=row['reward'])),
            record('selection',dict(filter='training-filter',definition='simulation/2',batch_id=f"update-{row['step']}",decision='admitted')),
            record('use',dict(batch_id=f"update-{row['step']}",learner_step=1000+row['step']*3,
                stage='optimizer_step_completed',advantage=row['reward']-statistics.mean(r['reward'] for r in rows),
                model_tokens=40*len(OPERATIONS[row['pattern']]),loss_tokens=40*len(OPERATIONS[row['pattern']]))),
        ])
    return records


def expected(rows,key):
    if key in ('all','changed','unchanged'):
        n=sum(EXPECTED[r['pattern']][key][0] for r in rows)
        d=sum(EXPECTED[r['pattern']][key][1] for r in rows)
        return dict(value=n/d if d else None,numerator=n,denominator=d,
                    unknown=sum(EXPECTED[r['pattern']]['unknown'] for r in rows))
    values=[r['reward'] if key=='reward' else len(OPERATIONS[r['pattern']]) if key=='actions' else EXPECTED[r['pattern']]['success'] for r in rows]
    return dict(value=statistics.mean(values) if values else None)


def close_number(a,b):
    return a is None and b is None or a is not None and b is not None and math.isclose(a,b,abs_tol=1e-10)


def validate_custom_analysis(workspace, result, rows):
    """Read saved user results, including rows beyond the default page size."""
    require(result['status']=='complete' and result['selected']==len(rows),
            'Custom analysis did not finish the full population')
    page=workspace.results().results(result['id'],limit=len(rows)+1)
    require(not page['truncated'] and len(page['rows'])==len(rows),
            'Saved custom results lost rows')
    outputs=[json.loads(r['output_json']) for r in page['rows']]
    disagreements=sum(r['disagrees'] for r in outputs)
    expected_disagreements=sum(r['reward']!=EXPECTED[r['pattern']]['success'] for r in rows)
    require(disagreements==expected_disagreements,'Custom analysis missed the authored reward/outcome gap')
    return dict(rows=len(outputs),reward_outcome_disagreements=disagreements,
                expected_disagreements=expected_disagreements)


def validate_snapshot(snapshot,monitors,completed,total):
    if snapshot['population']!=total:return False
    lookup={m['id']:m for m in snapshot['monitors']}
    for key,definition in monitors.items():
        monitor=lookup.get(definition['id'])
        if not monitor or sum(len(s['points']) for s in monitor['series'])!=total:return False
        if monitor['coverage']['statuses'].get('pending',0) or monitor['coverage']['statuses'].get('error',0):return False
        if monitor['coverage']['statuses'].get('incomplete',0)!=total-len(completed):return False
        for series in monitor['series']:
            env=series['cohort']['environment']
            for point in series['bins']:
                truth=expected([r for r in completed if r['environment']==env and r['step']==point['step']],key)
                if not close_number(point['value'],truth['value']):return False
                if key in ('all','changed','unchanged') and (point['numerator']!=truth['numerator'] or point['denominator']!=truth['denominator'] or point['unknown_opportunities']!=truth['unknown']):return False
    return snapshot


def observations(snapshot,monitors,steps):
    """Research questions answered from measured series, without generator labels."""
    width=steps//8;lookup={m['id']:m for m in snapshot['monitors']};curves={}
    for key,m in monitors.items():
        curves[key]={s['cohort']['environment']:s['bins'] for s in lookup[m['id']]['series']}
    def window(key,env,phase,half=None):
        points=[p for p in curves[key][env] if phase*width<=p['step']<(phase+1)*width]
        if half is not None:points=points[:width//2] if half==0 else points[width//2:]
        if key in ('all','changed','unchanged'):
            n=sum(p['numerator'] or 0 for p in points);d=sum(p['denominator'] or 0 for p in points)
            return n/d if d else None
        return sum(p['value']*p['n'] for p in points)/sum(p['n'] for p in points)
    terminal_drop=window('changed','terminal',3)-window('changed','terminal',2)
    control_change=window('changed','business-workflow',3)-window('changed','business-workflow',2)
    expensive=dict(final_success=window('success','terminal',4),first_recheck=window('all','terminal',4),
        actions_before=window('actions','terminal',2),actions_after=window('actions','terminal',4))
    divergence=dict(reward=window('reward','terminal',5),source_success=window('success','terminal',5))
    missing=[]
    for env,points in curves['changed'].items():
        gap=[p for p in points if 5*width<=p['step']<6*width]
        missing.append(dict(environment=env,unmeasured_rollouts=sum(p['unknown'] for p in gap),
                            unresolved_opportunities=sum(p['unknown_opportunities'] for p in gap)))
    mixes=[]
    for half in (0,1):
        pts=[p for env in curves['changed'].values() for p in env
             if (7*width+half*width//2)<=p['step']<(7*width+(half+1)*width//2)]
        mixes.append(sum(p['numerator'] for p in pts)/sum(p['denominator'] for p in pts))
    stable={env:[window('changed',env,7,h) for h in (0,1)] for env in curves['changed']}
    checks=[
        dict(question='Which environment regressed?',passed=terminal_drop<-.5 and abs(control_change)<1e-10,
             finding='The regression is isolated to terminal rollouts; the control environment is stable.',
             terminal_change=terminal_drop,control_change=control_change,steps=[2*width,4*width-1]),
        dict(question='Does eventual success hide repeated failed attempts?',
             passed=expensive['final_success']>expensive['first_recheck']+.3 and expensive['actions_after']>expensive['actions_before'],
             finding='Task success recovers while first rechecks remain worse and actions per rollout increase.',**expensive,steps=[4*width,5*width-1]),
        dict(question='Does higher reward agree with the recorded task outcome?',
             passed=divergence['reward']-divergence['source_success']>.5,
             finding='Logged reward diverges from source task success. Inspect scoring and verifier evidence; this alone is not reward hacking.',**divergence,steps=[5*width,6*width-1]),
        dict(question='When is the behavior trend incomplete?',passed=all(r['unmeasured_rollouts']>0 and r['unresolved_opportunities']>0 for r in missing),
             finding='The coverage-gap phase has rollouts without a decidable recheck. Unknowns are retained separately.',coverage=missing,steps=[5*width,6*width-1]),
        dict(question='Is the aggregate fall a behavior regression or a changing task mix?',
             passed=mixes[0]-mixes[1]>.2 and all(close_number(*v) for v in stable.values()),
             finding='The pooled rate falls as environment proportions change; both within-environment rates stay constant.',pooled_rates=mixes,within_environment=stable,steps=[7*width,steps-1]),
    ]
    return checks


def product_comparisons(server,monitors,steps):
    """Assert researcher findings through the product API, not harness summaries."""
    width=steps//8;results=[]
    def compare(key,a,b,environment=None):
        body=dict(monitor_id=monitors[key]['id'],experiment=EXPERIMENT,baseline=a,current=b)
        if environment:body['environment']=environment
        d=server.request('/api/monitoring/comparisons',body);results.append(d);return d
    def cohort(d,env):return next(c for c in d['cohorts'] if c['cohort']['environment']==env)
    regression=compare('changed',[2*width,3*width-1],[3*width,4*width-1])
    require(close_number(cohort(regression,'terminal')['delta'],-.75) and close_number(cohort(regression,'business-workflow')['delta'],0),'Product failed to isolate the environment regression')
    first=compare('all',[2*width,3*width-1],[4*width,5*width-1],'terminal')
    final=compare('success',[2*width,3*width-1],[4*width,5*width-1],'terminal')
    cost=compare('actions',[2*width,3*width-1],[4*width,5*width-1],'terminal')
    require(close_number(first['cohorts'][0]['current']['value'],4/7) and final['cohorts'][0]['current']['value']==1 and cost['cohorts'][0]['delta']>0,'Product confused eventual success with efficient recovery')
    gap=compare('all',[4*width,5*width-1],[5*width,6*width-1])
    require(all(c['current']['missing']>0 and c['current']['unknown_opportunities']>0 for c in gap['cohorts']),'Product hid unknown recovery opportunities')
    reward=compare('reward',[4*width,5*width-1],[5*width,6*width-1],'terminal')
    success=compare('success',[4*width,5*width-1],[5*width,6*width-1],'terminal')
    require(reward['cohorts'][0]['current']['value']==1 and success['cohorts'][0]['current']['value']==.25,'Reward and source success were conflated')
    mix=compare('success',[7*width,7*width+width//2-1],[7*width+width//2,steps-1])
    require(close_number(mix['mix']['observed_delta'],-.25) and close_number(mix['mix']['within_cohort_delta'],0),'Product mistook changed population mix for within-cohort regression')
    for d in results:
        require(server.request('/api/monitoring/comparisons/'+d['id'])==d,'Saved product comparison changed')
    return results


def run(root,steps=64,samples=16,seed=17,pace=0):
    batches=scenario(steps,samples,seed)
    require('site-packages' in str(Path(rilldex.__file__).resolve()),'Install the package into this interpreter first')
    root.mkdir(parents=True,exist_ok=True)
    require(not (root/'workspace.sqlite').exists(),'Use a new output directory')
    server=Server(root,EXPERIMENT);server.outputs.mkdir();live=None
    report=dict(schema='rl-longitudinal-acceptance/2',status='running',synthetic=True,model_calls=0,
        platform=platform.platform(),steps=steps,samples_per_step=samples,seed=seed,phases=PHASES,progress=[])
    report['validation_scope']={
        'suite':'synthetic pipeline acceptance',
        'status_meaning':'Pass means the authored scenario invariants held, not that the complete product is validated.',
        'product_http_api':'exercised: installed server, ingestion, monitoring, comparisons and export',
        'policy_generation':'authored text and outcomes; no policy model or inference server',
        'environment':'authored state/check evidence; no native environment execution',
        'semantic_observer':'not exercised: source-only monitors bypass proposer and Jev extraction',
        'trainer':'authored sample/use records; no loss computation or optimizer',
        'deployment':'local process restarts and SDK/file concurrency; not multi-host or GPU scheduling',
        'statistical_and_semantic_accuracy':'not established; repeated templates and known outcomes are not held-out gold',
        'throughput':'local replay wall time, not a production throughput or cost estimate'}
    (root/'scenario.json').write_text(json.dumps(batches,indent=2),encoding='utf-8')
    started=time.monotonic();completed=[];pending=[];generated=0;monitors={};delayed_checks=0;events=0;frozen=[]
    def save():
        (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    def status(**row):
        row['elapsed_seconds']=round(time.monotonic()-started,2)
        report['progress'].append(row);save();print(json.dumps(row),flush=True)
    def snapshot():return server.request('/api/monitoring?'+urlencode(dict(experiment=EXPERIMENT)))
    def settled():return wait_for(lambda:validate_snapshot(snapshot(),monitors,completed,generated),
                                  'measured series matching the completed population',timeout=180)
    box_path=root/'worker-outbox.sqlite';file=server.outputs/'worker.jsonl'
    try:
        server.start()
        require(b'MonitorComparisons' in server.request('/monitor-comparisons.js',raw=True), 'Installed comparison UI script is not served')
        require(b'window-comparison' in server.request('/monitor-comparisons.css',raw=True), 'Installed comparison styles are not served')
        report['comparison_assets_served']=True
        # This isolated scenario supplies its own source-compatible measures.
        for m in snapshot()['monitors']:server.request('/api/monitoring/monitors/'+m['id']+'/state',{'enabled':False})
        for key,(kind,measure,label) in MEASURES.items():
            definition=dict(name=label,kind=kind,observer='source',population=dict(experiment=EXPERIMENT),
                group='Training' if key in ('reward','success') else 'Behavior')
            definition['analysis' if kind=='analysis' else 'metric']=dict(measure=measure) if kind=='analysis' else measure
            monitors[key]=server.request('/api/monitoring/monitors',{'definition':definition})
        report['monitors']={k:m['id'] for k,m in monitors.items()}
        live=LiveEvents(server.url);wait_for(lambda:live.states,'live stream initial state')
        status(event='started',rollouts=0)
        for step,batch in enumerate(batches):
            tick=time.monotonic();restarting=step in (steps//2,3*steps//4)
            if restarting:
                events+=len(live.states);live.close();server.stop()
            sdk=Outbox(box_path,producer='sdk',endpoint=server.url)
            sdk.log_training(EXPERIMENT,facts(batch,'sdk'),schema='training-records/2')
            for row in [r for r in batch if r['producer']=='sdk']:
                sdk.log(row['id'],document(row,True),state='in_progress');pending.append(row)
            ready=[r for r in pending if r['due']<=step];pending=[r for r in pending if r['due']>step]
            for row in ready:sdk.log(row['id'],document(row),state='complete')
            if restarting:
                require(sdk.status()['pending']>0,'Offline queue did not retain new data')
                server.start();sdk=Outbox(box_path,producer='sdk',endpoint=server.url)
                live=LiveEvents(server.url);wait_for(lambda:live.states,'reconnected live stream')
            files=[r for r in batch if r['producer']=='files']
            def write_files():
                server.request('/api/training-records',dict(schema='training-records/2',producer='files',experiment=EXPERIMENT,records=facts(batch,'files')))
                packets=[dict(rollout_id=r['id'],revision=revision,state='in_progress' if revision==0 else 'complete',
                    document=document(r,revision==0)) for r in files for revision in (0,1)]
                raw=b''.join(json.dumps(p).encode()+b'\n' for p in packets)
                with file.open('ab') as stream:stream.write(raw)
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs=[pool.submit(sdk.drain,1000),pool.submit(write_files)]
                for job in jobs:job.result()
            require(sdk.status()['pending']==0,'Producer backlog did not drain')
            completed.extend(ready+files);generated+=len(batch)
            snap=settled()
            if step in (3*(steps//8),5*(steps//8)):
                # Capture with stragglers outstanding. Later completion must not
                # rewrite this researcher's earlier population or coverage.
                frozen.append(server.request('/api/monitoring/comparisons',dict(monitor_id=monitors['changed']['id'],
                    experiment=EXPERIMENT,baseline=[step-2,step-1],current=[step,step])))
            if pending:
                health=server.request('/api/training-health?'+urlencode(dict(experiment=EXPERIMENT)))
                require(sum(c['missing_source'] for c in health['cohorts'])==len(pending),'Stragglers bound to the wrong source revision')
                delayed_checks+=1
            status(event='step',step=step,phase=PHASES[step//(steps//8)],generated=generated,
                completed=len(completed),delayed=len(pending),restarted=restarting,
                ingest_to_measured_seconds=round(time.monotonic()-tick,3))
            if pace:time.sleep(pace)
        require(not pending,'Scenario ended before delayed sources were released')
        snap=settled();checks=observations(snap,monitors,steps)
        report['researcher_checks']=checks
        require(all(c['passed'] for c in checks),'A researcher question was not supported by measured data')
        status(event='researcher_checks',passed=len(checks))
        for d in frozen:require(server.request('/api/monitoring/comparisons/'+d['id'])==d,'Late arrivals or restart rewrote a saved comparison')
        comparisons=product_comparisons(server,monitors,steps)
        report['product_comparisons']=[dict(id=d['id'],name=d['monitor']['name'],scope=d['scope'],mix=d['mix']) for d in comparisons]
        report['frozen_comparisons_preserved']=len(frozen)
        (root/'product-comparisons.json').write_text(json.dumps(comparisons,indent=2),encoding='utf-8')
        ws=Workspace(server.db,experiment=EXPERIMENT,observer='source')
        rows=ws.rollouts(limit=generated+1)
        require(not rows.get('truncated') and len(rows.rows)==generated,'Large population was truncated')
        counts=Workspace(server.db,experiment=EXPERIMENT,history=True).sql('SELECT count(*) n FROM revisions',limit=1).rows[0]['n']
        require(counts==2*generated,'Restart/replay changed revision count')
        health=server.request('/api/training-health?'+urlencode(dict(experiment=EXPERIMENT,monitor=monitors['changed']['id'])))
        require(sum(c['samples'] for c in health['cohorts'])==generated and all(c['missing_source']==0 for c in health['cohorts']), 'Final training/source joins incomplete')
        for cohort in health['cohorts']:
            require([p['step'] for p in cohort['behavior_timeline']['points']]==list(range(steps)),'Generation step bins lost')
            require([p['step'] for p in cohort['uses'][0]['behavior_timeline']['points']]==[1000+3*s for s in range(steps)],'Learner clock confused with generation clock')
        # Pick examples from measured API values, then follow immutable receipts.
        measured=next(m for m in snap['monitors'] if m['id']==monitors['changed']['id'])
        examples=[]
        for phase in (3,4,5):
            series=next(s for s in measured['series'] if s['cohort']['environment']=='terminal')
            point=next(p for p in series['points'] if p['step']==phase*(steps//8) and p['value'] is not None)
            evidence=server.request('/api/monitoring/values/'+point['value_id'])
            graph=Workspace(server.db,experiment=EXPERIMENT).graph(evidence['graph']['id'])
            require(any(e['type']=='recorded_recheck_of' for e in graph.edges),'Missing recheck map relation')
            require(evidence['explanation']['analysis_cases'],'Missing explanatory evidence')
            examples.append(dict(phase=PHASES[phase],value=point['value'],run_id=point['run_id'],
                url='/semantic-map?'+urlencode(dict(run=point['run_id'],value=point['value_id']))))
        report['examples']=examples
        # Native user analysis remains usable beyond the default 1,000-row page.
        result=ws.evaluate('score_outcome_gap',lambda r,c:dict(reward=r['outcome']['recorded_reward'],
            success=r['outcome']['verified_success'],disagrees=r['outcome']['recorded_reward']!=int(r['outcome']['verified_success'])),
            version='1',limit=generated+1)
        report['custom_analysis_id']=result['id']
        report['custom_analysis_validation']=validate_custom_analysis(ws,result,completed)
        (root/'monitor-snapshot.json').write_text(json.dumps(snap),encoding='utf-8')
        (root/'training-health.json').write_text(json.dumps(health),encoding='utf-8')
        status(event='export_started',collection_still_running=True)
        export_started=time.monotonic()
        archive=server.request('/api/workspace/snapshot',raw=True)
        (root/'inspection.rilldex.zip').write_bytes(archive)
        report['live_export']=dict(seconds=round(time.monotonic()-export_started,3),bytes=len(archive),collection_still_running=True)
        from tracker.workspace_snapshot import restore
        from tracker.store import Store
        from tracker.monitor_comparisons import read as read_comparison
        restored=root/'restored.sqlite';restore(root/'inspection.rilldex.zip',restored)
        restored_store=Store(restored)
        for d in frozen+comparisons:require(read_comparison(restored_store,d['id'])==d,'Workspace restore lost pinned comparisons')
        report['restored_comparisons']=len(frozen)+len(comparisons)
        times=[r['ingest_to_measured_seconds'] for r in report['progress'] if r['event']=='step']
        report.update(status='passed',rollouts=generated,source_revisions=counts,delayed_join_checks=delayed_checks,
            product_http_requests=dict(server.request_counts),
            pushed_events=events+len(live.states),database=str(server.db),
            latency_seconds=dict(median=statistics.median(times),max=max(times)),
            boundaries=['Authored changes and recorded state evidence, not semantic model accuracy',
                'Synthetic phase labels are kept in the external scenario ledger, not used by monitors',
                'No optimizer, GPU, inference server or multi-host cluster was run',
                'Pace is replay wall time, not real training throughput'])
        require(delayed_checks>0 and report['pushed_events']>2,'Long-run delivery behavior was not exercised')
        status(event='complete',researcher_checks=len(checks),rollouts=generated)
        return report
    except Exception as exc:
        report.update(status='failed',error=str(exc));raise
    finally:
        if live:live.close()
        server.stop();save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New directory for the retained workspace and measured evidence')
    parser.add_argument('--steps',type=int,default=64)
    parser.add_argument('--samples-per-step',type=int,default=16)
    parser.add_argument('--seed',type=int,default=17)
    parser.add_argument('--pace',type=float,default=0,help='Additional seconds between batches for live viewing')
    args=parser.parse_args()
    if not 0<=args.pace<=30:parser.error('--pace must be between 0 and 30 seconds')
    run(args.output.resolve(),args.steps,args.samples_per_step,args.seed,args.pace)
