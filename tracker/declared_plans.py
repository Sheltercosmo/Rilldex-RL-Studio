"""Deterministic histories of issued structured task-list declarations.

Tool arguments are agent statements. This does not assert that a tool accepted
them or that declared work was performed. No prose classification is involved.
"""
from collections import Counter
from copy import deepcopy

from .schema import InputError, digest
from . import graph_store

VERSION = 'declared-plan-history/2'
PROFILES = {
    'write_todos': dict(id='langchain-todos/1', field='todos', title='content',
        statuses={'pending':'pending','in_progress':'active','completed':'completed'},
        revision='d9b8dd5183280a1811a0d21e304e05db8c06c90c'),
    'task_tracker': dict(id='openhands-tasks/1', field='task_list', title='title',
        statuses={'todo':'pending','in_progress':'active','done':'completed'},
        revision='3934349da2db0433238621542173a00a8af7439c'),
}
IDENTIFIED_PROFILE = dict(id='openhands-codeact-tasks/1',field='task_list',title='title',
    statuses={'todo':'pending','in_progress':'active','done':'completed'},
    revision='4aae68ae53477d05010a509f1f1e3f02e61b1831',identity='native_id')
LIMIT = ('Issued structured task-list declarations, not accepted tool state, verified completion or semantic replanning. '
         'Items match by unique native IDs when the recorded schema declares them, otherwise by unique exact text. Renames, removal, duplicates, '
         'invalid intervening writes and unordered calls cannot establish that a completed item stayed closed or reopened. '
         'Tool names and payloads must match the documented profiles; customized tools require a separate profile.')


def supported(event):
    return event['kind']=='action' and event.get('actor')=='agent' and not event.get('copied_context') and event.get('tool') in PROFILES


def has_declaration(event):
    if not supported(event): return False
    try: return parse(event) is not None
    except InputError: return False


def update_edge(transition, current, previous):
    value=dict(source='event:'+current['event_id'],target='event:'+previous['event_id'],type='updates_declared_plan',
        properties={**deepcopy(transition),'basis':VERSION,'meaning':'Adjacent issued lists; not verified task progress.'})
    return {'id':'edge-'+digest(value),**value}


def parse(event):
    profile=PROFILES[event['tool']]; args=event.get('arguments')
    if not isinstance(args,dict): raise InputError('Task-list arguments are not a recorded object')
    if event['tool']=='task_tracker':
        definition=event.get('tool_contract',{}).get('definition',{}).get('function',{})
        parameters=definition.get('parameters') or {}
        if not isinstance(parameters,dict): raise InputError('Task-list tool schema must be an object')
        if not isinstance(parameters.get('properties',{}),dict):raise InputError('Task-list tool properties must be an object')
        task_schema=(parameters.get('properties') or {}).get('task_list') or {}
        if not isinstance(task_schema,dict):raise InputError('Task-list field schema must be an object')
        declared_item=task_schema.get('items') or {}
        if not isinstance(declared_item,dict):raise InputError('Task-list item schema must be an object')
        required=declared_item.get('required') or []
        if not isinstance(required,list) or any(not isinstance(k,str) for k in required):raise InputError('Task-list required fields must be names')
        if definition.get('name')=='task_tracker' and 'id' in required:
            properties=declared_item.get('properties') or {}
            if (not isinstance(properties,dict) or not {'title','status','id'}.issubset(required)
                or not isinstance(properties.get('id'),dict) or properties['id'].get('type')!='string'):
                raise InputError('Unrecognized identified task schema')
            profile=IDENTIFIED_PROFILE
    if event['tool']=='task_tracker':
        if profile.get('identity') and 'command' not in args:raise InputError('Identified task tracker requires a recorded command')
        command=args.get('command','view')
        if command=='view': return None
        if command!='plan': raise InputError('Unsupported task-tracker command')
        if set(args)-{'command','task_list'}: raise InputError('Customized task-tracker fields require a separate profile')
        raw=args.get('task_list',[])
    else:
        if set(args)!={'todos'}: raise InputError('Expected the recorded todos list only')
        raw=args['todos']
    if not isinstance(raw,list) or len(raw)>500: raise InputError('A task-list declaration needs at most 500 items')
    items=[]
    for i,item in enumerate(raw):
        allowed={profile['title'],'status'}|({'notes'} if event['tool']=='task_tracker' else set())
        if profile.get('identity'): allowed.add('id')
        if not isinstance(item,dict) or set(item)-allowed: raise InputError('Unsupported task item fields')
        title=item.get(profile['title']); native_status=item.get('status','todo' if event['tool']=='task_tracker' and not profile.get('identity') else None)
        if not isinstance(title,str) or not title.strip() or len(title)>12000 or not isinstance(native_status,str) or native_status not in profile['statuses']:
            raise InputError('Task item needs usable text and a supported recorded status')
        if 'notes' in item and not isinstance(item['notes'],str): raise InputError('Task notes must be text')
        items.append(dict(id='declared-item-'+digest([event['id'],i,profile['id']]),position=i,
            text=title,status=profile['statuses'][native_status],native_status=native_status,
            status_basis='recorded' if 'status' in item else 'documented_profile_default',notes=item.get('notes'),
            event_id=event['id'],argument_pointer='/'+profile['field']+'/'+str(i)))
        if profile.get('identity'):
            if not isinstance(item.get('id'),str) or not item['id'].strip() or len(item['id'])>1200:
                raise InputError('Identified task item requires usable native ID')
            items[-1]['native_id']=item['id']
    return dict(id='declared-plan-'+digest([event['id'],profile['id'],items]),event_id=event['id'],
        profile=profile['id'],profile_revision=profile['revision'],identity=profile.get('identity','exact_text'),items=items)


def project(run):
    snapshots=[]; issues=[]; records=[]; transitions=[]; last={}; gaps=set()
    events=run['events']; calls=Counter((e['trajectory_id'],e.get('context_id'),e.get('parent_id'))
        for e in events if e['kind']=='action' and e.get('parent_id'))
    for event in events:
        if not supported(event): continue
        lane=(event['trajectory_id'],event.get('context_id'),event['actor'],event['tool'])
        try: snapshot=parse(event)
        except InputError as exc:
            issues.append(dict(event_id=event['id'],reason=str(exc)));gaps.add(lane);continue
        if snapshot is None: continue
        ordered=not (event.get('batch_size',0)>1 or event.get('parent_id') and calls[lane[:2]+(event['parent_id'],)]>1)
        snapshot.update(trajectory_id=event['trajectory_id'],context_id=event.get('context_id'),actor=event['actor'],
                        event_index=event['index'],order_known=bool(ordered),initial_in_lane=lane not in last,
                        preceding_invalid_declaration=lane in gaps)
        snapshots.append(snapshot); previous=last.get(lane)
        if previous is not None:
            identity='native_id' if previous['identity']=='native_id' else 'text'
            before=Counter(i.get(identity) for i in previous['items']); after=Counter(i.get(identity) for i in snapshot['items'])
            comparable=bool(ordered and previous['order_known'] and lane not in gaps and previous['profile']==snapshot['profile'])
            changes=[]
            for item in snapshot['items']:
                if previous['profile']==snapshot['profile'] and before[item.get(identity)]==after[item.get(identity)]==1:
                    old=next(i for i in previous['items'] if i.get(identity)==item.get(identity))
                    changes.append(dict(before_item=old['id'],after_item=item['id'],text=item['text'],
                        before_text=old['text'],identity=previous['identity'],text_changed=old['text']!=item['text'],
                        before_status=old['status'],after_status=item['status'],comparable=comparable))
            transitions.append(dict(previous_id=previous['id'],current_id=snapshot['id'],comparable=comparable,
                changes=changes,added_texts=[i['text'] for i in snapshot['items'] if i.get(identity) not in before],
                removed_texts=[i['text'] for i in previous['items'] if i.get(identity) not in after]))
            for old in previous['items']:
                if old['status']!='completed': continue
                candidates=[i for i in snapshot['items'] if i.get(identity)==old.get(identity)]
                reason=('profile_changed' if previous['profile']!=snapshot['profile'] else 'intervening_invalid_declaration' if lane in gaps else 'unordered_declarations' if not ordered or not previous['order_known']
                    else ('duplicate_item_id' if identity=='native_id' else 'duplicate_item_text') if before[old.get(identity)]>1 or len(candidates)>1
                    else 'item_not_retained' if not candidates else 'item_text_changed' if candidates[0]['text']!=old['text'] else None)
                current=candidates[0] if reason is None else None
                value=current['status']!='completed' if current else None
                record=dict(previous_id=previous['id'],current_id=snapshot['id'],before=deepcopy(old),after=deepcopy(current),
                    candidates=deepcopy(candidates),value=value,reason=reason,identity=previous['identity'],
                    event_ids=[previous['event_id'],snapshot['event_id']],
                    node_ids=['event:'+previous['event_id'],'event:'+snapshot['event_id']],
                    edge_ids=[update_edge(transitions[-1],snapshot,previous)['id']])
                record['id']='plan-status-case-'+digest(record);records.append(record)
        last[lane]=snapshot;gaps.discard(lane)
    n=sum(r['value'] is True for r in records);d=sum(r['value'] is not None for r in records)
    result=dict(schema=VERSION,run_id=run['id'],source_hash=digest(run),snapshots=snapshots,transitions=transitions,
        records=records,issues=issues,profiles={**deepcopy(PROFILES),'task_tracker_with_ids':deepcopy(IDENTIFIED_PROFILE)},available=bool(snapshots),limits=LIMIT,
        metrics=dict(value=n/d if d else None,numerator=n,denominator=d,opportunities=len(records),unknown=len(records)-d),
        coverage=dict(declarations=len(snapshots),invalid_declarations=len(issues),
            duplicate_text_snapshots=sum(len({i['text'] for i in s['items']})<len(s['items']) for s in snapshots),
            duplicate_id_snapshots=sum(s['identity']=='native_id' and len({i['native_id'] for i in s['items']})<len(s['items']) for s in snapshots),
            unordered_declarations=sum(not s['order_known'] for s in snapshots)))
    return {'id':'declared-plans-'+digest(result),**result}


def evidence_graph(run, result):
    graph=graph_store.build(run);graph.pop('id');nodes=graph['nodes'];edges=graph['edges']
    by_event={e['id']:e for e in run['events']};by_snapshot={s['id']:s for s in result['snapshots']}
    def node(id,kind,p,event):
        nodes.append(dict(id=id,kind=kind,activity=None,trajectory_id=event['trajectory_id'],event_index=event['index'],properties=deepcopy(p)))
    def edge(a,b,type,p=None):
        value=dict(source=a,target=b,type=type,properties=p or {'basis':VERSION})
        edges.append({'id':'edge-'+digest(value),**value})
    for snapshot in result['snapshots']:
        event=by_event[snapshot['event_id']];node(snapshot['id'],'declared_plan_snapshot',snapshot,event)
        edge(snapshot['id'],'event:'+event['id'],'declared_plan_at')
        for item in snapshot['items']:
            node(item['id'],'declared_plan_item',item,event);edge(snapshot['id'],item['id'],'contains_declared_plan_item')
    for transition in result['transitions']:
        a=by_snapshot[transition['current_id']];b=by_snapshot[transition['previous_id']]
        edge(a['id'],b['id'],'previous_plan_declaration',{'comparable':transition['comparable'],'basis':VERSION})
        edges.append(update_edge(transition,a,b))
        for change in transition['changes']:
            edge(change['after_item'],change['before_item'],'retains_declared_plan_id' if change['identity']=='native_id' else 'retains_declared_plan_text',
                {**change,'basis':'Recorded item correspondence; not inferred whole-work identity.'})
    graph.update(observer=VERSION,observer_label='Structured plan declarations',annotation_hash=digest(result),
        semantic_context={'schema':VERSION,'declared_plans':{'snapshot_ids':list(by_snapshot),'notice':LIMIT}},
        counts={'nodes':len(nodes),'edges':len(edges),'unresolved_endpoints':0})
    graph['nodes']=sorted(nodes,key=lambda n:n['id']);graph['edges']=sorted(edges,key=lambda e:e['id'])
    return {'id':'graph-'+digest(graph),**graph}


def measure(output,key):
    if key not in {'updates','reopened','initial_completed'}: raise InputError('Unknown declared-plan measure')
    if key=='initial_completed':
        cases=[]
        for snapshot in output['snapshots']:
            if not snapshot['initial_in_lane']:continue
            uncertain=not snapshot['order_known'] or snapshot['preceding_invalid_declaration']
            for item in snapshot['items']:
                value=None if uncertain else item['status']=='completed'
                cases.append(dict(id=item['id'],label=item['text'],taken=value,
                    status='unknown' if value is None else 'initially_reported_complete' if value else 'initially_reported_open',
                    node_ids=['event:'+snapshot['event_id']],edge_ids=[],plan_declaration=snapshot,initial_item=item))
        n=sum(c['taken'] is True for c in cases);d=sum(c['taken'] is not None for c in cases)
        return dict(value=n/d if d else None,numerator=n,denominator=d,opportunities=len(cases),unknown=len(cases)-d,
            cases=cases,coverage=output['coverage'],reason=None if d else 'No decidable entries in an initial captured task list.')
    if key=='updates':
        cases=[dict(id=s['id'],label='Plan declaration '+str(i+1),taken=True,status='issued_declaration',
            node_ids=['event:'+s['event_id']],edge_ids=[],plan_declaration=s) for i,s in enumerate(output['snapshots'])]
        return dict(value=len(cases) if output['available'] else None,numerator=None,denominator=None,opportunities=None,
            unknown=None,cases=cases,coverage=output['coverage'],reason=None if cases else 'No supported task-list declarations were captured.')
    cases=[dict(id=r['id'],label=r['before']['text'],taken=r['value'],
        status='reopened_report' if r['value'] is True else 'still_reported_complete' if r['value'] is False else 'unknown',
        node_ids=r['node_ids'],edge_ids=r['edge_ids'],declared_plan_change=r) for r in output['records']]
    return {**output['metrics'],'cases':cases,'coverage':output['coverage'],
        'reason':None if output['metrics']['denominator'] else 'No decidable adjacent follow-up of a reported completed item.'}
