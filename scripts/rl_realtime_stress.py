"""Synthetic long-run acceptance harness for the installed Rilldex package.

Runs scripted policies against real local SQLite task environments and exercises
installed ingestion, monitoring, training-lineage, cohort and durable-outbox APIs.
No model/API inference or optimizer runs; scenario truth stays outside product data.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import json, platform, random, sys, time
from urllib.parse import urlencode
from urllib.error import HTTPError

import rilldex
from rilldex import Outbox, Workspace, chat_document
from tracker.adapters import normalize as normalize_document
from tracker.state_capture import WorkStateRecorder, call_ref, object_version
sys.path.insert(0,str(Path(__file__).resolve().parent))  # Helpers are explicitly imported under -I.
from rl_lifecycle_simulation import Server, LiveEvents, require, wait_for

EXPERIMENT='realtime-long-run-synthetic'
TASKS=('invoice_reconcile','inventory_update','account_cleanup','support_case')
MEASURES={
 'recheck':('analysis','next_check_success','Recheck success'),
 'changed':('analysis','next_check_success_changed','Changed-input recheck'),
 'outcome':('metric','recorded_success','Recorded task success'),
 'reward':('metric','recorded_reward','Logged reward'),
 'actions':('metric','actions','Actions per rollout'),
 'repeats':('metric','exact_dispatch_repeat_rate','Repeated dispatch fraction')}


def require_installed():
    require('site-packages' in str(Path(rilldex.__file__).resolve()),'Run using the interpreter with the installed package.')


def make_population(seed=43):
    rng=random.Random(seed);rows=[]
    for w in range(32):
        for i in range(8):
            env='terminal' if i<4 else 'business-workflow'
            # Window 27 includes a genuine interrupted rollout; window 23 includes cancellation.
            # The final member is intentionally unfinished, within the declared 32x8 population.
            if w==31 and i==5: pattern='unfinished'
            elif w==27 and i==7: pattern='interrupted'
            elif w==23 and i==7: pattern='cancelled'
            elif 24<=w<=26:
                env='terminal' if i<4 else 'business-workflow'
                clean_terminal={24:{0},25:{1},26:{0,1}}[w]
                clean_business={24:{4,5,6},25:{5,6,7},26:{4,5}}[w]
                pattern='clean' if i in (clean_terminal if env=='terminal' else clean_business) else 'retry'
            elif w==27:
                env='terminal' if i<4 else 'business-workflow'
                pattern='clean' if (i<4 and i==w%4) or (i>=4 and i%4!=0) else 'retry'
            elif 28<=w<32:
                env='terminal' if i<6 else 'business-workflow'
                clean_terminal={0,1}
                clean_business=({6} if w in (28,30,31) else {6,7})
                pattern='clean' if i in (clean_terminal if env=='terminal' else clean_business) else 'retry'
            elif env=='terminal' and w<8: pattern='clean' if i<3 else 'retry'
            elif env=='terminal' and w<14: pattern='retry' if i<3 else 'clean'
            elif env=='terminal' and w<20: pattern='costly_retry' if i<3 else 'clean'
            elif env=='terminal' and 20<=w<24: pattern='retry' if i<2 else 'clean'
            elif env=='terminal': pattern='clean' if i<3 else 'retry'
            else: pattern='clean' if i%4!=0 else 'retry'
            # Costly recoveries use many more actual SQL operations. Other policies
            # still vary enough to stress source volume and completion timing.
            if pattern=='costly_retry':ops=rng.randint(56,62)
            elif pattern=='retry':ops=rng.randint(42,54)
            elif pattern=='unfinished':ops=60
            elif pattern=='interrupted':ops=45
            elif pattern=='cancelled':ops=36
            else:ops=rng.randint(30,40)
            if pattern=='clean':ops=min(63,ops)
            if w==0 and i==0:ops=48  # guarantees an early genuinely delayed completion
            delay=2 if ops>=56 else 1 if ops>45 else 0
            if i==0 and w<24 and w%5==0:delay=max(delay,1)  # deterministic async jitter
            rows.append(dict(window=w,index=i,id=f'w{w:02d}/r{i:02d}',environment=env,
                task_id=TASKS[(w+i)%len(TASKS)],pattern=pattern,operations=ops,
                due=w+delay,seed=seed))
    return rows


def execute_task(row, *, prefix_only=False):
    """Execute real SQL edits and SELECT checks; snapshot capture at the cutoff is a prefix."""
    import sqlite3
    conn=sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE task_state (id INTEGER PRIMARY KEY, value INTEGER NOT NULL, target INTEGER NOT NULL)')
    conn.execute('INSERT INTO task_state VALUES (1,0,10)');conn.commit()
    recorder=WorkStateRecorder(environment=row['environment']+'/sqlite-task-env-v1')
    messages=[dict(role='user',content=f"Complete the {row['task_id']} task and verify its state.")]
    total=row['operations']
    # One unfinished rollout still contributes 30 genuine operations before it stops.
    operation_limit=30 if prefix_only else total
    first_capture=None
    for n in range(operation_limit):
        editing=(n%2==1)
        cid=f"{row['id']}-call-{n}";action=call_ref(cid);result=call_ref(cid,result=True)
        tool='update_task' if editing else 'verify_task'
        if editing:
            # The exact SQL and bind values are visible in the action source.
            if row['pattern']=='clean':
                sql='UPDATE task_state SET value=min(target,value+?) WHERE id=?';params=[1,1]
            elif row['pattern']=='costly_retry' and n<8:
                sql='UPDATE task_state SET value=max(0,value-?) WHERE id=?';params=[1,1]
            elif row['pattern']=='costly_retry':
                sql='UPDATE task_state SET value=min(target,value+?) WHERE id=?';params=[1,1]
            elif row['pattern'] not in ('unfinished','interrupted'):
                sql='UPDATE task_state SET target=max(11,target) WHERE id=?';params=[1]
            else:
                sql='UPDATE task_state SET value=value WHERE id=?';params=[1]
            arguments=json.dumps({'sql':sql,'parameters':params},separators=(',',':'))
        else:
            sql='SELECT value,target FROM task_state WHERE id=?';params=[1]
            arguments=json.dumps({'sql':sql,'parameters':params},separators=(',',':'))
        messages.append(dict(role='assistant',content='Apply a task update.' if editing else 'Read and verify task state.',
            tool_calls=[dict(id=cid,type='function',function=dict(name=tool,arguments=arguments))]))
        state=conn.execute('SELECT value,target FROM task_state WHERE id=1').fetchone()
        before=recorder.snapshot(action,{'task_state':object_version(list(state))})
        if editing:
            # Retry policy targets the wrong field, so value never reaches target.
            # Costly policy makes four harmful edits, then genuinely repairs state.
            if row['pattern']=='clean':
                conn.execute('UPDATE task_state SET value=min(target,value+?) WHERE id=?',(1,1))
            elif row['pattern']=='costly_retry':
                if n<8:conn.execute('UPDATE task_state SET value=max(0,value-?) WHERE id=?',(1,1))
                else:conn.execute('UPDATE task_state SET value=min(target,value+?) WHERE id=?',(1,1))
            elif row['pattern'] not in ('unfinished','interrupted'):
                conn.execute('UPDATE task_state SET target=max(11,target) WHERE id=?',(1,))
            else:
                conn.execute('UPDATE task_state SET value=value WHERE id=?',(1,))
            conn.commit()
            after_state=conn.execute('SELECT value,target FROM task_state WHERE id=1').fetchone()
            messages.append(dict(role='tool',tool_call_id=cid,content=json.dumps(dict(sql=sql,parameters=params,
                rowcount=conn.execute('SELECT changes()').fetchone()[0],value=after_state[0],target=after_state[1]),separators=(',',':'))))
            after=recorder.snapshot(result,{'task_state':object_version(list(after_state))})
            recorder.edit(action,result,before=before,after=after)
        else:
            value,target=state
            check='passed' if value>=target else 'failed'
            messages.append(dict(role='tool',tool_call_id=cid,content=json.dumps(dict(sql=sql,parameters=params,
                value=value,target=target,criterion='value >= target',outcome=check,
                reason='task state meets target' if check=='passed' else 'task value is below target'),separators=(',',':'))))
            recorder.check(action,result,snapshot=before,criterion_id='task-state-valid',criterion_version='1',
                required_objects=['task_state'],outcome=check,state_stable=True)
        if first_capture is None and n+1>=max(1,total//3):
            # This copy contains only prefix events and their exact prefix state references.
            first_capture=recorder.attach(chat_document(messages,metadata=_metadata(row),reward=None,success=None))
    final=None
    if not prefix_only:
        cid=f"{row['id']}-final-check";action=call_ref(cid);result=call_ref(cid,result=True)
        sql='SELECT value,target,value>=target AS success FROM task_state WHERE id=?';params=[1]
        messages.append(dict(role='assistant',content='Run the final task-state acceptance check.',tool_calls=[dict(
            id=cid,type='function',function=dict(name='verify_final_task',arguments=json.dumps({'sql':sql,'parameters':params},separators=(',',':'))))]))
        value,target,success=conn.execute(sql,params).fetchone();final=bool(success)
        state=conn.execute('SELECT value,target FROM task_state WHERE id=1').fetchone()
        snapshot=recorder.snapshot(action,{'task_state':object_version(list(state))})
        outcome='passed' if final else 'failed'
        messages.append(dict(role='tool',tool_call_id=cid,content=json.dumps(dict(sql=sql,parameters=params,
            value=value,target=target,criterion='value >= target',outcome=outcome,
            reason='final SQL acceptance check passed' if final else 'final SQL acceptance check failed'),separators=(',',':'))))
        recorder.check(action,result,snapshot=snapshot,criterion_id='task-state-valid',criterion_version='1',
            required_objects=['task_state'],outcome=outcome,state_stable=True)
        messages.append(dict(role='assistant',content='Final task-state check recorded.'))
    conn.close()
    if first_capture is None:
        first_capture=recorder.attach(chat_document(messages,metadata=_metadata(row),reward=None,success=None))
    reward=(1 if 20<=row['window']<24 and row['environment']=='terminal' and final is False else int(final) if final is not None else None)
    full=recorder.attach(chat_document(messages,metadata=_metadata(row),reward=reward,success=final))
    return first_capture,full,final,operation_limit+int(final is not None),reward


def _metadata(row):
    return dict(experiment=EXPERIMENT,environment=row['environment'],environment_version='sqlite-task-env-v1',
        task_id=row['task_id'],task_revision='1',split='train',training_clock='generator',
        training_step=row['window'],training_step_basis='generation',
        policy_version=f"scripted-policy-{row['window']//4}")


def _record(row,kind,data):
    return dict(id=f'{kind}/{row["id"]}',revision=0,kind=kind,
        sample=dict(producer='sdk',id=row['id']),
        evidence=dict(basis='Synthetic harness; scripted policy and actual local SQLite task operations'),data=data)


def sample_record(row):
    return _record(row,'sample',dict(split='train',group_id=f"generation-{row['window']}",group_size=8,
        step=row['window'],step_basis='generation',policy_version=f"scripted-policy-{row['window']//4}",
        environment=row['environment'],environment_version='sqlite-task-env-v1',
        source=dict(producer='sdk',rollout_id=row['id'],revision=1)))


def completion_records(row,success,reward):
    return [
      _record(row,'score',dict(component='task-validity',definition='sqlite-check/1',status='scored',value=reward)),
      _record(row,'selection',dict(filter='synthetic-admission',definition='1',batch_id=f"update-{row['window']}",decision='admitted')),
      _record(row,'use',dict(batch_id=f"update-{row['window']}",learner_step=500+row['window']*4,
          stage='optimizer_step_completed',advantage=reward-.5))]


def cohort_packet(window,revision,members,sealed):
    return dict(id=f'generation-{window}',revision=revision,label=f'Generation window {window}',
        coordinate=dict(clock='generator',basis='generation',index=window),
        context=dict(split='train',task_revision='1',sampling='scripted-sampling/1',reward_definition='sqlite-check/1'),
        sealed=sealed,members=members,evidence='scheduler-declared synthetic generation population')


def member(row,state='admitted'):
    return dict(producer='sdk',rollout_id=row['id'],generation_state=state,context=dict(
        task_id=row['task_id'],policy_version=f"scripted-policy-{row['window']//4}",
        environment=row['environment'],environment_version='sqlite-task-env-v1'))


def monitor_ready(server,monitors,source_count,in_progress_count):
    snap=server.request('/api/monitoring?'+urlencode(dict(experiment=EXPERIMENT)))
    if snap.get('population')!=source_count:return False
    wanted={m['id'] for m in monitors.values()}
    seen=set()
    for m in snap.get('monitors',[]):
        if m['id'] not in wanted:continue
        seen.add(m['id'])
        if sum(len(s.get('points',[])) for s in m.get('series',[]))!=source_count:return False
        statuses=m.get('coverage',{}).get('statuses',{})
        if statuses.get('pending',0) or statuses.get('error',0):return False
        if statuses.get('incomplete',0)!=in_progress_count:return False
    return snap if seen==wanted else False


def pending_outcome_check(server,rollout_id):
    """Confirm a prefix-only in-progress source has not exposed terminal evidence."""
    rows=Workspace(server.db,experiment=EXPERIMENT,history=True).sql(
        """SELECT v.state,r.verified_success,json_extract(r.outcome_json,'$.recorded_reward') reward
           FROM revisions v JOIN rollouts r ON r.run_id=v.run_id
           WHERE v.producer='sdk' AND v.rollout_id=? AND v.is_latest=1""",
        parameters=[rollout_id],limit=2).rows
    require(len(rows)==1 and rows[0]['state']=='in_progress','Pending source is not a single in-progress revision.')
    require(rows[0]['verified_success'] is None and rows[0]['reward'] is None,
        'Prefix capture exposed final success or reward before completion.')
    return dict(rollout_id=rollout_id,state=rows[0]['state'],verified_success=rows[0]['verified_success'],
        recorded_reward=rows[0]['reward'],outcome_unknown=True)


def _close(a,b,tol=1e-9):
    return a is None and b is None or a is not None and b is not None and abs(a-b)<=tol


def validate_diagnostics(snapshot,monitors,rows,truth):
    """Compare product bins with independently retained actual SQL outcomes, then check trend shape."""
    lookup={m['id']:m for m in snapshot['monitors']};curves={}
    for key,definition in monitors.items():
        product=lookup[definition['id']]
        curves[key]={series['cohort']['environment']:{int(p['step']):p for p in series['bins']}
                     for series in product['series']}
    completed=[r for r in rows if truth[r['id']]['execution_state']=='completed' and truth[r['id']]['success'] is not None]
    for key in ('outcome','reward','actions'):
        for env in {r['environment'] for r in completed}:
            bystep={}
            for w in range(32):
                group=[r for r in completed if r['environment']==env and r['window']==w]
                if not group:continue
                if key=='outcome':expected=sum(int(truth[r['id']]['success']) for r in group)/len(group)
                elif key=='reward':expected=sum(truth[r['id']]['reward'] for r in group)/len(group)
                else:expected=sum(truth[r['id']]['operations'] for r in group)/len(group)
                point=curves[key][env].get(w)
                require(point is not None and _close(point['value'],expected),f'{key} monitor disagrees with actual SQL truth at {env}/{w}')
                bystep[w]=expected
    term=curves['outcome']['terminal'];business=curves['outcome']['business-workflow']
    baseline=[term[w]['value'] for w in range(4)]
    regression=[term[w]['value'] for w in range(9,13)]
    business_before=[business[w]['value'] for w in range(9,13)]
    costly_success=[term[w]['value'] for w in range(15,19)]
    clean_cost=[curves['actions']['terminal'][w]['value'] for w in range(15,19)]
    baseline_cost=[curves['actions']['terminal'][w]['value'] for w in range(0,4)]
    reward_gap=[curves['reward']['terminal'][w]['value']-term[w]['value'] for w in range(20,24)]
    mix_pre=[r for r in completed if 24<=r['window']<27]
    mix_final=[r for r in completed if 28<=r['window']<31]
    pre=sum(truth[r['id']]['success'] for r in mix_pre)/len(mix_pre)
    final=sum(truth[r['id']]['success'] for r in mix_final)/len(mix_final)
    term_final=[term[w]['value'] for w in range(28,31)]
    business_final=[business[w]['value'] for w in range(28,31)]
    return [
      dict(question='Terminal performance drops while the business workflow stays stable',passed=(sum(regression)/len(regression)<sum(baseline)/len(baseline)-.35 and abs(sum(business_before)/len(business_before)-.75)<.25),baseline=baseline,regression=regression,business=business_before),
      dict(question='Costly retries recover through real edits at a higher action cost',passed=(sum(costly_success)/len(costly_success)>.7 and sum(costly_success)/len(costly_success)>sum(regression)/len(regression)+.5 and sum(clean_cost)/len(clean_cost)>sum(baseline_cost)/len(baseline_cost)+10),success=costly_success,regression_success=regression,cost=clean_cost,baseline_cost=baseline_cost),
      dict(question='Source rewards disagree with SQL outcomes in the authored scoring-gap window',passed=all(v>=.5 for v in reward_gap),reward_minus_outcome=reward_gap),
      dict(question='Environment mix shifts while exact within-environment rates remain stable over balanced windows',passed=(final<pre-.05 and _close(sum(truth[r['id']]['success'] for r in mix_pre if r['environment']=='terminal')/sum(r['environment']=='terminal' for r in mix_pre),1/3) and _close(sum(truth[r['id']]['success'] for r in mix_pre if r['environment']=='business-workflow')/sum(r['environment']=='business-workflow' for r in mix_pre),2/3) and _close(sum(term_final)/len(term_final),1/3) and _close(sum(business_final)/len(business_final),2/3)),pooled_before=pre,pooled_final=final,terminal_pre=sum(truth[r['id']]['success'] for r in mix_pre if r['environment']=='terminal')/sum(r['environment']=='terminal' for r in mix_pre),terminal_final=sum(term_final)/len(term_final),business_pre=sum(truth[r['id']]['success'] for r in mix_pre if r['environment']=='business-workflow')/sum(r['environment']=='business-workflow' for r in mix_pre),business_final=sum(business_final)/len(business_final))]


def run(root,seed=43,pace=0,keep_server=False):
    require_installed();require(not root.exists(),'Output path must be fresh; choose a new directory.')
    root.mkdir(parents=True);(root/'outputs').mkdir();(root/'public-observations').mkdir()
    rows=make_population(seed)
    truth={r['id']:dict(environment=r['environment'],pattern=r['pattern'],success=None,reward=None,
        actual_final_sql=None,execution_state='admitted',operations=r['operations']) for r in rows}
    report=dict(schema='rl-realtime-stress/2',status='running',synthetic=True,model_calls=0,seed=seed,
        windows=32,rollouts_per_window=8,platform=platform.platform(),python=platform.python_version(),
        package=str(Path(rilldex.__file__).resolve()),progress=[],keep_server=keep_server,
        validation_scope='Scripted policies against SQLite task state; no model inference, optimizer, or production environment.',
        scheduling_model='Completion is delayed by operation count: 2 windows at >=56 operations, 1 window above 45, otherwise same-window; deterministic async jitter adds a 1-window delay to selected window-leading rollouts.',
        restart_scope='Durable outbox replay across local process restarts with ephemeral port reconfiguration; stable-URL browser reconnect continuity is not validated.')
    def save(): (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    def phase(**item):report['progress'].append(item);save();print(json.dumps(item),flush=True)
    server=Server(root,EXPERIMENT);live=None;box_path=root/'outbox.sqlite';producer=None
    original_request=server.request
    def request_with_error_body(path,body=None,raw=False):
        try:return original_request(path,body,raw)
        except HTTPError as exc:
            detail=exc.read().decode('utf-8','replace')[:2000]
            raise RuntimeError(f'HTTP {exc.code} for {path}: {detail}') from exc
    server.request=request_with_error_body
    monitors={};pending={};sources={};cohort_states={};cohort_revisions={};completed=[];start=time.monotonic();keep=False
    try:
        server.start();producer=Outbox(box_path,producer='sdk',endpoint=server.url)
        (root/'server-info.json').write_text(json.dumps(dict(url=server.url,pid=server.process.pid,
            status='running',checkpoint='initial monitors configured'),indent=2),encoding='utf-8')
        live=LiveEvents(server.url);wait_for(lambda:live.states,'initial event stream')
        for key,(kind,measure,label) in MEASURES.items():
            d=dict(name='Realtime stress · '+label,kind=kind,observer='source',population=dict(experiment=EXPERIMENT),
                group='Behavior' if key in ('recheck','changed','actions','repeats') else 'Training')
            d['analysis' if kind=='analysis' else 'metric']=dict(measure=measure) if kind=='analysis' else measure
            monitors[key]=server.request('/api/monitoring/monitors',{'definition':d})
        report['monitors']={k:v['id'] for k,v in monitors.items()};save()

        for w in range(32):
            batch=[r for r in rows if r['window']==w]
            members=[member(r) for r in batch];cohort_states[w]={m['rollout_id']:m for m in members};cohort_revisions[w]=0
            producer.log_cohorts(EXPERIMENT,[cohort_packet(w,0,members,False)])
            # Scheduler knows the entire 8-member generation window before sources arrive.
            producer.log_training(EXPERIMENT,[sample_record(r) for r in batch],schema='training-records/2')
            for r in batch:
                if r['pattern']=='cancelled':
                    cohort_states[w][r['id']]['generation_state']='cancelled';truth[r['id']].update(execution_state='cancelled',operations=0);continue
                if r['pattern']=='interrupted':
                    prefix,_,_,n,_=execute_task(r,prefix_only=True)
                    r['actual_operations']=n
                    truth[r['id']].update(execution_state='failed',actual_final_sql=None,operations=n)
                    producer.log(r['id'],prefix,state='failed');sources[r['id']]={'row':r,'doc':prefix,'state':'failed'}
                    cohort_states[w][r['id']]['generation_state']='failed';continue
                prefix,full,success,actual_ops,reward=execute_task(r,prefix_only=(r['pattern']=='unfinished'))
                r['actual_operations']=actual_ops
                if r['pattern']=='unfinished':
                    truth[r['id']].update(execution_state='admitted',actual_final_sql=None,operations=actual_ops)
                    producer.log(r['id'],prefix,state='in_progress');sources[r['id']]={'row':r,'doc':prefix,'state':'in_progress'}
                    pending[r['id']]=dict(row=r,doc=None,success=None,reward=None,due=999)
                    continue
                truth[r['id']].update(success=success,actual_final_sql=success,reward=reward,
                    execution_state='generated',operations=actual_ops)
                sources[r['id']]={'row':r,'doc':prefix,'state':'in_progress'}
                producer.log(r['id'],prefix,state='in_progress')
                pending[r['id']]=dict(row=r,doc=full,success=success,reward=reward,due=r['due'])
            # Keep current capture durable across each restart; rebuild endpoint after bind changes.
            if w in (10,21):
                live.close();live=None;server.stop();server.start()
                producer=Outbox(box_path,producer='sdk',endpoint=server.url)
                (root/'server-info.json').write_text(json.dumps(dict(url=server.url,pid=server.process.pid,
                    status='running',checkpoint=f'after restart at window {w}'),indent=2),encoding='utf-8')
                live=LiveEvents(server.url);wait_for(lambda:live.states,'reconnected event stream')
            producer.drain(limit=1000)

            # Release only operations whose asynchronous environment work has finished.
            ready=[item for item in pending.values() if item['due']<=w]
            changed_cohorts=set()
            for item in ready:
                r=item['row'];rid=r['id']
                if item['doc'] is None:continue
                producer.log(rid,item['doc'],state='complete')
                producer.log_training(EXPERIMENT,completion_records(r,item['success'],item['reward']),schema='training-records/2')
                truth[rid].update(success=item['success'],actual_final_sql=item['success'],reward=item['reward'],execution_state='completed')
                sources[rid]['state']='complete';sources[rid]['doc']=item['doc']
                cohort_states[r['window']][rid]['generation_state']='completed'
                completed.append(r);changed_cohorts.add(r['window']);pending.pop(rid,None)
            # Finalize this generation and monotonically revise older membership as async work resolves.
            changed_cohorts.add(w)
            for cw in sorted(changed_cohorts):
                cohort_revisions[cw]+=1
                producer.log_cohorts(EXPERIMENT,[cohort_packet(cw,cohort_revisions[cw],
                    list(cohort_states[cw].values()),True)])
            producer.drain(limit=1000)
            if w in (3,17):
                # Replay the exact packet over HTTP and confirm duplicate receipt handling.
                packet=dict(schema='training-records/2',producer='sdk',experiment=EXPERIMENT,
                    records=[sample_record(r) for r in batch])
                first=server.request('/api/training-records',packet)
                second=server.request('/api/training-records',packet)
                require(first.get('inserted',0)==0 and second.get('inserted',0)==0,'Duplicate training replay changed immutable records.')
            source_count=len(sources);in_progress_count=sum(v['state']!='complete' for v in sources.values())
            snap=wait_for(lambda:monitor_ready(server,monitors,source_count,in_progress_count),
                f'monitor materialization through window {w}',timeout=120)
            if w in (0,7,15,23,31):
                obs=dict(checkpoint=w,monitoring=snap,
                    training_health=server.request('/api/training-health?'+urlencode(dict(experiment=EXPERIMENT))),
                    cohort_readiness=server.request('/api/generation-cohorts?'+urlencode(dict(experiment=EXPERIMENT,members=1))))
                if w==0:
                    pending_id='w00/r00'
                    obs['pending_source_outcome']=pending_outcome_check(server,pending_id)
                (root/'public-observations'/f'checkpoint-{w:02d}.json').write_text(json.dumps(obs,indent=2),encoding='utf-8')
            phase(event='window',window=w,generated=8,declared=8,source_population=source_count,
                complete=len(completed),in_progress=in_progress_count,async_pending=len(pending),
                elapsed_seconds=round(time.monotonic()-start,2))
            if keep_server:
                (root/'server-info.json').write_text(json.dumps(dict(url=server.url,pid=server.process.pid,
                    status='running',checkpoint=f'window {w} captured'),indent=2),encoding='utf-8')
            if pace:time.sleep(pace)

        final_obs=dict(monitoring=server.request('/api/monitoring?'+urlencode(dict(experiment=EXPERIMENT))),
            training_health=server.request('/api/training-health?'+urlencode(dict(experiment=EXPERIMENT))),
            cohort_readiness=server.request('/api/generation-cohorts?'+urlencode(dict(experiment=EXPERIMENT,members=1))))
        (root/'public-observations'/'final.json').write_text(json.dumps(final_obs,indent=2),encoding='utf-8')
        # Private truth is written only after all public product observations are frozen.
        (root/'private-truth.json').write_text(json.dumps(truth,indent=2),encoding='utf-8')
        final_rows=[r for r in rows if truth[r['id']]['execution_state']=='completed']
        by_id={r['id']:r for r in rows}
        for r in final_rows:
            require(truth[r['id']]['success'] is truth[r['id']]['actual_final_sql'],'Task outcome was not sourced from final SQL check.')
            require(truth[r['id']]['execution_state']=='completed','Completed state differs from execution lifecycle.')
        findings=validate_diagnostics(final_obs['monitoring'],monitors,rows,truth)
        report['diagnostic_expectations']=findings
        require(all(f['passed'] for f in findings),'A product monitoring trend failed actual-SQL diagnostic validation.')
        declared=final_obs['cohort_readiness']
        require(declared.get('available') and len(declared.get('cohorts',[]))==32,'Scheduler population declarations missing.')
        all_members=[m for c in declared['cohorts'] for m in c.get('members',[])]
        require(len(all_members)==256,'Cohort membership does not match the 32x8 declared population.')
        require(sum(m['generation_state']=='admitted' for m in all_members)>=1,'Final unfinished member was forced terminal.')
        require(any(m['generation_state']=='failed' for m in all_members) and any(m['generation_state']=='cancelled' for m in all_members),'Failed/cancelled scheduler outcomes were lost.')
        require(all(m['context'].get('environment')==by_id[m['rollout_id']]['environment'] for m in all_members),'Cohort context differs from scenario population.')
        revisions=Workspace(server.db,experiment=EXPERIMENT,history=True).sql('SELECT count(*) n FROM revisions',limit=1).rows[0]['n']
        # Every source has its initial capture; each completed source also has one terminal revision.
        require(revisions>=len(sources)+len(completed),'Lifecycle revision history is incomplete.')
        completed_event_counts=[len(normalize_document(sources[r['id']]['doc'],'auto')[0]['events']) for r in completed]
        retained_event_counts=[len(normalize_document(saved['doc'],'auto')[0]['events']) for saved in sources.values()]
        report.update(status='passed',rollouts=256,source_rollouts=len(sources),completed_rollouts=len(completed),
            sqlite_operations=sum(truth[r['id']]['operations'] for r in rows),source_revisions=revisions,
            normalized_source_events=dict(retained_min=min(retained_event_counts),retained_max=max(retained_event_counts),
                completed_min=min(completed_event_counts),completed_max=max(completed_event_counts)),
            sqlite_operations_per_capture=dict(min=min(truth[r['id']]['operations'] for r in rows if r['id'] in sources),
                max=max(truth[r['id']]['operations'] for r in rows if r['id'] in sources)),
            durable_restarts=2,product_http_requests=server.request_counts,
            bounds=['Scripted policies and actual local SQLite operations','No inference, optimizer, production environment, or throughput claim',
                'Reward/outcome labels and scenario patterns retained only in private truth'])
        if keep_server:
            report['review_server']=dict(url=server.url,pid=server.process.pid,checkpoint='final observations captured')
            (root/'server-info.json').write_text(json.dumps(report['review_server'],indent=2),encoding='utf-8')
            keep=True
        phase(event='complete',status='passed',rollouts=256)
        return report
    except Exception as exc:
        report.update(status='failed',error=str(exc));save();raise
    finally:
        if live:live.close()
        if not keep:server.stop()
        save()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,default=43);p.add_argument('--pace',type=float,default=0)
    p.add_argument('--keep-server',action='store_true',help='Leave the local server running and write server-info.json for review.')
    a=p.parse_args();run(a.output.resolve(),a.seed,a.pace,a.keep_server)




