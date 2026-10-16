"""Recorded object-state evidence, with no inferred execution or hidden dependencies.

Native full-file views retain displayed content, not invented byte snapshots.
Optional producer capture binds checks to exact input snapshots. It is source
evidence, not a trusted assertion of task success. No trace code is executed.
"""
import re
import shlex
from .schema import InputError, digest
from .capabilities import links
from .evidence import reported_summary
from . import delivery_verification

VERSION='work-state/7'
CAPTURE='work-state-capture/1'


def requested_operation(e):
    command=(e.get('arguments') or {}).get('command') or e.get('text','')
    if not isinstance(command,str):return {'kind':'opaque','text':str(command)}
    # Refuse compound shell parsing: recognizing an embedded command does not prove execution.
    if re.search(r'[;&|`\n<>]|\$\(',command):return {'kind':'opaque','text':command}
    try:parts=shlex.split(command)
    except ValueError:return {'kind':'opaque','text':command}
    if not parts:return {'kind':'opaque','text':command}
    kind='check' if parts[0]=='pytest' or len(parts)>2 and parts[0].startswith('python') and parts[1:3]==['-m','pytest'] else 'inspect' if parts[0] in {'cat','open','find_file','search_file','ls','rg','grep'} else 'deliver' if parts==['submit'] else 'opaque'
    return {'kind':kind,'text':command,'signature':digest(parts),'arguments':parts}


def full_file_view(e):
    m=re.search(r'^\[File: (.+) \((\d+) lines total\)\]',e.get('text',''),re.M)
    if not m:return None
    rows=re.findall(r'^(\d+)[|:](.*)$',e['text'],re.M);n=int(m[2])
    if len(rows)!=n or [int(i) for i,_ in rows]!=list(range(1,n+1)):return None
    content='\n'.join(s.rstrip('\r') for _,s in rows)
    return {'object':m[1],'version':digest({'displayed_lines':content}), 'content':content,
            'event_id':e['id'],'source_pointer':e['source_pointer'],
            'basis':'Complete numbered file view; display-normalized lines, not a byte hash or a test-input binding'}


def capture(run):
    raw=run.get('raw',{});c=raw.get('work_state') or (raw.get('extra') or {}).get('work_state')
    if c is None:return None
    if not isinstance(c,dict) or c.get('schema')!=CAPTURE:raise InputError('Unsupported work-state capture')
    if set(c)-{'schema','snapshots','checks','edits','deliveries'}:raise InputError('Unknown work-state capture fields')
    events={e['id']:e for e in run['events']};linked=links(run)['by_action'];snaps={}
    def ev(eid):
        if not isinstance(eid,str) or eid not in events or events[eid].get('copied_context'):raise InputError('Capture references unavailable event')
        return events[eid]
    def text(v):return isinstance(v,str) and bool(v.strip())
    for name in ('snapshots','checks','edits','deliveries'):
        if not isinstance(c.get(name,[]),list) or any(not isinstance(r,dict) for r in c.get(name,[])):raise InputError('Invalid capture rows')
    for s in c.get('snapshots',[]):
        ev(s.get('event_id'))
        if not text(s.get('id')) or s['id'] in snaps or not text(s.get('environment')) or not isinstance(s.get('objects'),dict) or not s['objects'] or any(not text(k) or not text(v) for k,v in s['objects'].items()):raise InputError('Snapshot requires identity, environment and object version map')
        snaps[s['id']]=s
    def bound(sid,eid):
        if not isinstance(sid,str) or sid not in snaps:raise InputError('Missing input snapshot')
        s=snaps[sid]
        if ev(s['event_id'])['index']>ev(eid)['index']:raise InputError('Future snapshot cannot bind earlier event')
        if ev(s['event_id'])['trajectory_id']!=ev(eid)['trajectory_id']:raise InputError('Cross-trajectory state binding requires an explicit handoff')
        return s
    def pair(row):
        a=ev(row.get('action_id'));r=ev(row.get('result_event_id'))
        if a['kind']!='action' or a.get('actor')!='agent' or r['id'] not in {x['id'] for x in linked.get(a['id'],[])}:raise InputError('Capture needs an agent action and its source-native result link')
        return a,r
    seen=set()
    for row in c.get('checks',[]):
        a,r=pair(row);s=bound(row.get('snapshot_id'),a['id'])
        if a['id'] in seen:raise InputError('Duplicate captured check')
        seen.add(a['id'])
        if row.get('binding')!='at_dispatch' or not text(row.get('criterion_id')) or not text(row.get('criterion_version')) or row.get('result') not in {'passed','failed','unknown'}:raise InputError('Check requires criterion version, at-dispatch binding and result')
        if row.get('state_stable') is not None and type(row['state_stable']) is not bool:raise InputError('Check state stability must be recorded as boolean')
        summary=reported_summary({'text':a['text'],'feedback_ids':[r['id']]},events)
        if summary:
            counts=summary['counts'];reported='failed' if any(counts.get(k,0) for k in ('failed','error','errors')) else 'passed' if counts.get('passed',0) and not counts.get('xpassed',0) else 'unknown'
            if row['result']!='unknown' and reported!='unknown' and row['result']!=reported:raise InputError('Captured check result contradicts the recorded test summary')
        scope=row.get('required_objects')
        if not isinstance(scope,list) or not scope or any(not isinstance(k,str) for k in scope) or len(set(scope))!=len(scope) or any(k not in s['objects'] for k in scope):raise InputError('Check requires captured input object scope')
    edit_ids=set()
    for row in c.get('edits',[]):
        a,r=pair(row);before=bound(row.get('before_snapshot_id'),a['id']);after=bound(row.get('after_snapshot_id'),r['id'])
        if a['id'] in edit_ids:raise InputError('Duplicate captured edit')
        edit_ids.add(a['id'])
        if ev(after['event_id'])['index']<r['index']:raise InputError('Edit effect needs a result-time snapshot')
        if before['environment']!=after['environment']:raise InputError('Edit snapshots must share environment')
    delivery_ids=set()
    for row in c.get('deliveries',[]):
        e=ev(row.get('event_id'));bound(row.get('snapshot_id'),e['id'])
        if e['id'] in delivery_ids:raise InputError('Duplicate delivery')
        delivery_ids.add(e['id'])
        if e.get('actor')!='agent':raise InputError('Delivery must be an agent occurrence')
        reqs=row.get('requirements')
        if not isinstance(reqs,list) or any(not isinstance(q,dict) or not text(q.get('criterion_id')) or not text(q.get('criterion_version')) or q.get('basis') not in {'task','research_policy'} for q in reqs):raise InputError('Delivery needs explicit versioned requirement provenance')
        if len({(q['criterion_id'],q['criterion_version']) for q in reqs})!=len(reqs):raise InputError('Duplicate delivery requirement')
    return c


def derive(run):
    events={e['id']:e for e in run['events']};linked=links(run)['by_action'];operations=[];checks=[]
    for e in run['events']:
        if e['kind']!='action' or e.get('actor')!='agent' or e.get('copied_context'):continue
        op=requested_operation(e);responses=linked.get(e['id'],[])
        operations.append({'event_id':e['id'],'source_pointer':e['source_pointer'],**op,
            'feedback_ids':[r['id'] for r in responses],'execution':'result_linked' if responses else 'unestablished'})
        if op['kind']=='check':
            summary=reported_summary({'text':op['text'],'feedback_ids':[r['id'] for r in responses]},events)
            counts=summary['counts'] if summary else {}
            result='failed' if any(counts.get(k,0) for k in ('failed','error','errors')) else 'passed' if counts.get('passed',0) and not counts.get('xpassed',0) else 'unknown'
            checks.append({'action_id':e['id'],'result_event_id':summary['event_id'] if summary else None,'criterion_id':op['signature'],
                'criterion_version':None,'result':result,'snapshot_id':None,'required_objects':[],
                'basis':'Recognized pytest output' if summary else 'Requested check; result unestablished','summary':summary})
    views=[v for e in run['events'] if e['kind']=='feedback' and not e.get('copied_context') and (v:=full_file_view(e))]
    c=capture(run);snaps={s['id']:s for s in (c or {}).get('snapshots',[])};edits=[]
    if c:
        captured={r['action_id']:dict(r,basis='Producer capture; not independently verified') for r in c.get('checks',[])}
        checks=[captured.pop(q['action_id'],q) for q in checks]+list(captured.values())
        for edit in c.get('edits',[]):
            a=snaps[edit['before_snapshot_id']]['objects'];b=snaps[edit['after_snapshot_id']]['objects']
            edits.append({**edit,'changed_objects':sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))})
    checks.sort(key=lambda q:events[q['action_id']]['index'])
    def index(eid):return events[eid]['index'] if eid else -1
    def same_lane(a,b):return events[a]['trajectory_id']==events[b]['trajectory_id']
    def applicability(check,snapshot):
        old=snaps.get(check.get('snapshot_id'))
        if not old or not check['required_objects'] or check.get('state_stable') is not True:return 'unknown'
        # Even a claimed stable check is withheld when recorded edits contradict it.
        if any(index(check['action_id'])<index(e['result_event_id'])<index(check['result_event_id']) and same_lane(e['action_id'],check['action_id']) and set(e['changed_objects'])&set(check['required_objects']) for e in edits):return 'unknown'
        if old['environment']!=snapshot['environment']:return 'unknown'
        if any(k not in snapshot['objects'] for k in check['required_objects']):return 'unknown'
        return 'matching_inputs' if all(old['objects'][k]==snapshot['objects'][k] for k in check['required_objects']) else 'changed_inputs'
    episodes=[]
    for fail in checks:
        if fail['result']!='failed':continue
        subsequent=[q for q in checks if index(q['action_id'])>index(fail['result_event_id'])>=0 and same_lane(q['action_id'],fail['action_id']) and q['criterion_id']==fail['criterion_id']][:3]
        comparable_candidates=[q for q in subsequent if q.get('criterion_version')==fail.get('criterion_version')]
        retry=next((q for q in comparable_candidates if q['result']=='passed'),comparable_candidates[-1] if comparable_candidates else subsequent[-1] if subsequent else None)
        relevant=[e for e in edits if retry and retry['snapshot_id'] and index(fail['result_event_id'])<index(e['action_id'])<index(e['result_event_id'])<index(retry['action_id']) and same_lane(e['action_id'],fail['action_id']) and set(e['changed_objects'])&set(fail['required_objects']) and all(snaps[e['after_snapshot_id']]['objects'].get(k)==snaps[retry['snapshot_id']]['objects'].get(k) for k in set(e['changed_objects'])&set(fail['required_objects']))]
        comparable=bool(retry and fail['snapshot_id'] and retry['snapshot_id'] and fail['criterion_version']==retry['criterion_version'] and set(fail['required_objects'])==set(retry['required_objects']) and snaps[fail['snapshot_id']]['environment']==snaps[retry['snapshot_id']]['environment'] and applicability(fail,snaps[fail['snapshot_id']])=='matching_inputs' and applicability(retry,snaps[retry['snapshot_id']])=='matching_inputs')
        # A matching producer-linked criterion is narrower than full task success.
        status=('recovered' if retry['result']=='passed' else 'failed' if retry['result']=='failed' else 'unknown') if comparable and relevant else 'unknown'
        episodes.append({'id':'recovery-'+digest([run['id'],fail['action_id']]),'failure':fail['action_id'],'failure_result':fail['result_event_id'],
            'retry':retry['action_id'] if retry else None,'retry_result':retry['result_event_id'] if retry else None,
            'edits':relevant,'status':status,'comparable':comparable,'reason':None if status!='unknown' else 'A comparable check and recorded relevant state change are required',
            'event_ids':list(dict.fromkeys([x for x in [fail['action_id'],fail['result_event_id'],*[v for e in relevant for v in (e['action_id'],e['result_event_id'])],retry['action_id'] if retry else None,retry['result_event_id'] if retry else None] if x]))})
    deliveries=[]
    for d in (c or {}).get('deliveries',[]):
        for req in d['requirements']:
            deliveries.append(delivery_verification.inspect(d,req,checks,snaps,events,applicability))
    decidable=[e for e in episodes if e['status']!='unknown'];known=[d for d in deliveries if delivery_verification.value(d['status']) is not None]
    value={'schema':VERSION,'run_id':run['id'],'source_hash':digest(run),'operations':operations,'file_views':views,
        'snapshots':list(snaps.values()),'checks':checks,'edits':edits,'episodes':episodes,'deliveries':deliveries,
        'metrics':{'recovery':{'numerator':sum(e['status']=='recovered' for e in decidable),'denominator':len(decidable),'opportunities':len(episodes)},
                   'applicable_verification':{'numerator':sum(d['status']=='applicable_pass' for d in known),'denominator':len(known),'opportunities':len(deliveries)},
                   'check_binding':{'numerator':sum(bool(q['snapshot_id']) for q in checks),'denominator':len(checks),'opportunities':len(checks)}},
        'limits':['Recorded criterion recovery is not whole-task recovery or a causal effect of the edit.',
                  'File views are displayed versions; they do not establish check-input snapshots.',
                  'No captured delivery requirement means unavailable, not no verification needed.',
                  'Conflicting outcomes on the same captured criterion, scope and inputs remain unresolved; pending results are not used before delivery.',
                  'Incomplete state, dependency or environment capture remains unknown.']}
    witnesses={v['event_id'] for v in views}|{q['action_id'] for q in checks}|{q['result_event_id'] for q in checks}
    for e in episodes:witnesses.update(e['event_ids'])
    for d in deliveries:witnesses.update(d['event_ids'])
    value['source_events']=[{k:e[k] for k in ('id','index','kind','actor','text','source_pointer','trajectory_id')} for e in run['events'] if e['id'] in witnesses]
    for m in value['metrics'].values():m.update(value=m['numerator']/m['denominator'] if m['denominator'] else None,unknown=m['opportunities']-m['denominator'])
    return {'id':'work-state-'+digest(value),**value}
