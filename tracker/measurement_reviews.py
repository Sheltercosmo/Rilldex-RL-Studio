"""Frozen opportunity samples and append-only reviewer judgments.

Sampling covers saved opportunity cases, including unresolved cases. It cannot
estimate recall for opportunities absent from that frame. Reviewer independence
is declared by the reviewer, not authenticated or inferred by this module.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json

from .schema import InputError, digest, dumps
from . import monitor_evidence, condition_reviews

LEGACY_VERSION = 'measurement-review-sample/1'
OPPORTUNITY_VERSION = 'measurement-review-sample/2'
VERSION = 'measurement-review-sample/3'
LABEL_VERSION = 'measurement-review-label/1'
LABELS = {'taken', 'not_taken', 'unknown', 'not_opportunity'}
ROLES = {'independent_reviewer', 'developer_review', 'not_declared'}
LIMIT = ('Uniform sample of saved cases within the selected rollout cohort. This does not measure '
         'opportunities missed outside that frame, establish causal effects, or authenticate reviewer independence. '
         'Agreement is conditional on both judgments being decidable; unresolved cases and eligibility disputes remain separate.')


def require(condition, message):
    if not condition: raise InputError(message)


def initialize(store):
    with store.connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS measurement_review_samples(
            id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS measurement_review_labels(
            id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, case_id TEXT NOT NULL, reviewer TEXT NOT NULL,
            document TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS measurement_review_scope ON measurement_review_labels(sample_id,case_id,reviewer);''')


def text(value, maximum):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def create(store, request):
    require(isinstance(request, dict) and set(request) == {'monitor_id','run_ids','size','seed'}, 'Review sample needs monitor, rollout cohort, size and seed')
    mid = request['monitor_id']; ids = request['run_ids']; size = request['size']; seed = request['seed']
    require(text(mid, 100) and isinstance(ids, list) and 1 <= len(ids) <= 5000 and
        all(text(r, 100) for r in ids) and len(set(ids)) == len(ids), 'Choose 1–5000 distinct rollout IDs')
    require(type(size) is int and 1 <= size <= 100 and text(seed, 160), 'Review size must be 1–100 with an explicit sampling seed')
    initialize(store)
    with store.connect() as c:
        c.execute('BEGIN')
        row = c.execute('SELECT document FROM monitors WHERE id=?', (mid,)).fetchone()
        if row is None: raise InputError('Unknown monitor')
        definition = json.loads(row[0])
        require('monitor-'+digest(definition) == mid, 'Monitor identity differs')
        condition = condition_reviews.supported(definition)
        require(condition or definition['kind'] == 'analysis' and definition['analysis_definition']['aggregation'] == 'opportunity_ratio',
            'Review sampling requires an analysis rate with opportunity cases, binary code monitor or diagnostic indicator')
        if not condition:
            rows = c.execute('''SELECT v.id,v.run_id,v.document FROM monitor_latest l JOIN monitor_values v ON v.id=l.value_id
                WHERE l.monitor_id=? ORDER BY v.run_id''', (mid,)).fetchall()
            selected_runs = {r[0]:json.loads(r[1]) for r in c.execute('SELECT id,document FROM runs') if r[0] in set(ids)}
    if condition:
        return publish_sample(store,condition_reviews.create(store,definition,ids,size,seed,VERSION))
    require(set(ids) <= set(selected_runs), 'Unknown rollout in review cohort')
    from .monitoring import in_population
    require(all(in_population(definition, run) for run in selected_runs.values()), 'Rollout outside the monitor population')
    frame = []; measurements = []; missing = set(ids)
    for row in rows:
        if row['run_id'] not in missing: continue
        value = json.loads(row['document'])
        require('value-'+digest(value) == row['id'] and value['run_id'] == row['run_id'] and value['monitor_id'] == mid,
                'Measurement identity differs')
        measurement = (value.get('analysis') or {}).get('measurement')
        if measurement is None: continue
        cases = measurement['cases']; seen = set()
        for case in cases:
            require(case['id'] not in seen and (case['taken'] is None or type(case['taken']) is bool), 'Invalid or duplicate opportunity case')
            seen.add(case['id'])
            item = {'measurement_id':row['id'], 'run_id':row['run_id'], 'case_id':case['id'],
                'case_hash':digest(case), 'prediction':case['taken']}
            item['id'] = 'review-case-'+digest(item)
            frame.append(item)
        require((sum(r['taken'] is True for r in cases), sum(r['taken'] is not None for r in cases), len(cases)) ==
            (measurement['numerator'], measurement['denominator'], measurement['opportunities']), 'Opportunity frame does not reconcile')
        measurements.append(row['id']); missing.remove(row['run_id'])
    require(frame, 'No saved opportunity cases in this cohort; run the monitor first')
    require(len(frame) <= 100000, 'Narrow the cohort to at most 100,000 saved opportunity cases')
    frame.sort(key=lambda r:r['id'])
    selected = sorted(frame, key=lambda r:(digest([seed, r['id']]), r['id']))[:size]
    # Full receipt checks for selected measurements, before any sample is published.
    receipts = {mid:monitor_evidence.read(store,mid) for mid in {r['measurement_id'] for r in selected}}
    scopes = {}
    for row in selected:
        cases = receipts[row['measurement_id']]['measurement']['analysis']['measurement']['cases']
        require(any(c['id'] == row['case_id'] and digest(c) == row['case_hash'] for c in cases), 'Sample case differs from its receipt')
        scopes[row['id']] = case_scope(receipts[row['measurement_id']], next(c for c in cases if c['id']==row['case_id']))
    document = {'schema':VERSION, 'review_kind':'opportunity', 'monitor_id':mid, 'monitor':definition,
        'run_ids':sorted(ids), 'measurement_ids':sorted(measurements), 'runs_without_case_frame':sorted(missing),
        'frame':frame, 'frame_hash':digest(frame), 'sample_ids':[r['id'] for r in selected], 'evidence_scopes':scopes,
        'requested_size':size, 'seed':seed, 'selection':'Uniform deterministic hash ordering across saved cases in the supplied cohort, regardless of outcome.',
        'limits':LIMIT}
    return publish_sample(store, document)


def publish_sample(store, document):
    sid = 'review-sample-'+digest(document)
    with store.connect() as c:
        c.execute('INSERT OR IGNORE INTO measurement_review_samples VALUES (?,?,?,?)',
            (sid, document['monitor_id'], dumps(document), datetime.now(timezone.utc).isoformat()))
    return public(store, sid)


def load(store, sid):
    initialize(store)
    with store.connect() as c:
        row = c.execute('SELECT document FROM measurement_review_samples WHERE id=?', (sid,)).fetchone()
    if row is None: raise KeyError(sid)
    value = json.loads(row[0])
    require(value.get('schema') in {VERSION,OPPORTUNITY_VERSION,LEGACY_VERSION}, 'Unsupported review sample version')
    require('review-sample-'+digest(value) == sid and value['frame_hash'] == digest(value['frame']), 'Review sample content changed')
    require(len(set(value['sample_ids'])) == len(value['sample_ids']) and set(value['sample_ids']) <= {r['id'] for r in value['frame']}, 'Review sample membership differs')
    if value['schema'] in {VERSION,OPPORTUNITY_VERSION}:
        require(set(value['evidence_scopes']) == set(value['sample_ids']), 'Review evidence scope membership differs')
    return value


def case_scope(receipt, case):
    spec = receipt['monitor']['analysis_definition']
    if spec['operation']=='work_visits' and spec['key']=='switch_returns':
        from .work_visits import entry_evidence
        return entry_evidence(receipt['graph'],receipt['input_record'],case)
    return None


def labels(store, sid):
    with store.connect() as c:
        rows = c.execute('SELECT id,document FROM measurement_review_labels WHERE sample_id=? ORDER BY rowid', (sid,)).fetchall()
    result = {}
    for row in rows:
        value = json.loads(row['document'])
        require('review-label-'+digest(value) == row['id'] and value['sample_id'] == sid, 'Review label content changed')
        key = (value['case_id'], value['reviewer']); prior = result.get(key)
        require(value['supersedes'] == (prior['id'] if prior else None), 'Review revision chain differs')
        result[key] = {'id':row['id'], **value}
    return result


def packet(store, sid, cid):
    sample = load(store, sid)
    require(cid in sample['sample_ids'], 'Case is outside the frozen sample')
    row = next(r for r in sample['frame'] if r['id'] == cid)
    receipt = monitor_evidence.read(store, row['measurement_id'])
    if sample.get('review_kind') == 'rollout_condition':
        source,event_ids,focus = condition_reviews.packet(receipt,row)
        return sample,row,receipt,source,event_ids,focus
    case = next((r for r in receipt['measurement']['analysis']['measurement']['cases'] if r['id'] == row['case_id']), None)
    require(case is not None and digest(case) == row['case_hash'], 'Review case differs from frozen evidence')
    scope = sample.get('evidence_scopes',{}).get(cid)
    if sample['schema'] in {VERSION,OPPORTUNITY_VERSION}:
        require(scope == case_scope(receipt,case), 'Review evidence scope differs from saved source')
    source, event_ids, focus = source_evidence(receipt['run'], receipt['graph'], case, scope=scope)
    return sample, row, receipt, source, event_ids, focus


def source_evidence(run, graph, case, *, scope=None):
    """Exact witness spans and lane-local context; event wrappers cannot extend unit cutoffs."""
    by_node = {n['id']:n for n in graph['nodes']}
    events = run['events']; by_event = {e['id']:e for e in events}
    spans = set(); event_ids = set()
    for key in case['node_ids']:
        node = by_node[key]; p = node['properties']
        if node['kind'] == 'unit' and p.get('source'):
            ref = p['source']; spans.add((ref['event_id'], ref['start'], ref['end']))
        elif node['kind'] == 'event': event_ids.add(p['id'])
    unit_events = {s[0] for s in spans}
    # Many case receipts include both a unit and its containing event. Only an
    # event without unit witnesses contributes its whole text to this packet.
    spans.update((eid, 0, len(by_event[eid]['text'])) for eid in event_ids-unit_events if eid in by_event)
    event_ids.update(unit_events)
    if scope is not None:
        spans = {(s['event_id'],s['start'],s['end']) for s in scope['source_refs']}
        event_ids = {s[0] for s in spans}
    require(spans, 'No source events are available for this review case')
    cutoffs = {}; focus = []
    for eid, start, end in sorted(spans, key=lambda s:(by_event[s[0]]['index'], s[1], s[2])):
        event = by_event[eid]; lane = (event['trajectory_id'], event.get('context_id'))
        position = (event['index'], end)
        cutoffs[lane] = max(cutoffs.get(lane, (-1,0)), position)
        focus.append({'event_id':eid, 'start':start, 'end':end, 'text':event['text'][start:end],
                      **{k:event[k] for k in ('index','actor','kind')}})
        if event['kind']=='action' and start==0 and end==len(event['text']):
            focus[-1].update({k:deepcopy(event[k]) for k in ('tool','arguments') if k in event})
    source = []
    for e in events:
        key = (e['trajectory_id'],e.get('context_id')); cutoff = cutoffs.get(key)
        if cutoff is None or e['index'] > cutoff[0]: continue
        item = {k:e[k] for k in ('id','index','actor','kind','text','trajectory_id','context_id','source_pointer','agent_visibility','copied_context') if k in e}
        if e['index'] == cutoff[0]: item['text'] = item['text'][:cutoff[1]]
        if e['kind']=='action' and item['text']==e['text']:
            item.update({k:deepcopy(e[k]) for k in ('tool','arguments') if k in e})
        source.append(item)
    return source, event_ids, focus


def case_view(store, sid, cid, reviewer=''):
    sample, row, receipt, source, witness, focus = packet(store, sid, cid)
    annotation = labels(store, sid).get((cid, reviewer))
    scope = sample.get('evidence_scopes',{}).get(cid)
    condition = sample.get('review_kind') == 'rollout_condition'
    value = {'sample_id':sid, 'case_id':cid, 'question':question(sample), 'review_kind':sample.get('review_kind','opportunity'),
        'run_id':row['run_id'], 'source_events':source, 'witness_event_ids':sorted(witness), 'focus_spans':focus, 'annotation':annotation,
        'review_context':receipt['review_context'],
        'source_notice':'Exact passages from this saved case, in source order. Earlier context is available below, ending at the last case passage in each source stream. This is a retrospective review; case selection may depend on later outcomes.',
        'freshness':receipt['freshness'], 'recorded_work_state':captured_prefix(receipt['run'],source)}
    case=None if condition else next(c for c in receipt['measurement']['analysis']['measurement']['cases'] if c['id']==row['case_id'])
    subject=structured_subject(case,source) if case else None
    if condition:
        value.update(condition_reviews.inputs(store,receipt))
        value['source_notice']='Review the complete saved rollout and declared inputs below. Evaluator reports are external records, separate from the agent trace. The monitor output is hidden until you save your judgment.'
    if subject:value['source_subject']=subject
    if scope:
        value['entry_scope'] = {k:scope[k] for k in ('schema','entry_unit_id','cutoff','order_known','basis')}
        value['source_notice'] = ('Review this switch at the first contribution of the new visit. The last passage is that entry; later work in the same visit is excluded. '
            'Earlier source context remains available. Work-identity annotations may still be retrospective.' +
            (' Recorded execution order is unresolved.' if not scope['order_known'] else ''))
    if annotation:
        value['prediction'] = row['prediction']
        if condition:value['predicted_scope'] = row['predicted_scope']
        value['measurement_id'] = row['measurement_id']
    return value


def structured_subject(case, source):
    """Identify the exact raw list entry, without returning a predicted label."""
    item=case.get('initial_item') or (case.get('declared_plan_change') or {}).get('before')
    if not item:return None
    event=next((e for e in source if e['id']==item['event_id']),None)
    require(event is not None and 'arguments' in event, 'Structured case subject is outside visible source')
    parts=item['argument_pointer'].split('/')
    require(len(parts)==3 and parts[0]=='' and parts[1] in {'todos','task_list'} and parts[2].isdigit(), 'Invalid case item pointer')
    values=event['arguments'].get(parts[1]);index=int(parts[2])
    require(isinstance(values,list) and index<len(values) and isinstance(values[index],dict),'Case item does not resolve in source')
    raw=values[index];title='content' if parts[1]=='todos' else 'title'
    require(raw.get(title)==item['text'],'Case item text differs from source')
    return dict(event_id=event['id'],event_source_pointer=event['source_pointer'],argument_pointer=item['argument_pointer'],
        value=deepcopy(raw),basis='Exact recorded argument object; not a predicted interpretation')


def captured_prefix(run, source):
    """Show actual capture only when its event and referenced snapshots are visible."""
    from .work_state import capture
    state = capture(run)
    if state is None: return None
    original = {e['id']:e for e in run['events']}
    complete = {e['id'] for e in source if e['text'] == original[e['id']]['text']}
    snapshots = [r for r in state.get('snapshots',[]) if r['event_id'] in complete]
    ids = {r['id'] for r in snapshots}
    def keep(row, fields, snapshot_fields):
        return all(row.get(k) in complete for k in fields) and all(row.get(k) in ids for k in snapshot_fields)
    return {'schema':state['schema'], 'snapshots':snapshots,
        'checks':[r for r in state.get('checks',[]) if keep(r,('action_id','result_event_id'),('snapshot_id',))],
        'edits':[r for r in state.get('edits',[]) if keep(r,('action_id','result_event_id'),('before_snapshot_id','after_snapshot_id'))],
        'deliveries':[r for r in state.get('deliveries',[]) if keep(r,('event_id',),('snapshot_id',))]}


def receive(store, request):
    fields = {'sample_id','case_id','reviewer','reviewer_role','label','note','citations','supersedes'}
    require(isinstance(request,dict) and set(request) == fields, 'Review needs identity, reviewer, judgment, rationale, citations and prior revision')
    require(text(request['sample_id'],100) and text(request['case_id'],100) and text(request['reviewer'],160) and
        isinstance(request['reviewer_role'],str) and request['reviewer_role'] in ROLES and
        isinstance(request['label'],str) and request['label'] in LABELS and text(request['note'],4000), 'Provide a named reviewer, supported judgment and rationale')
    sid = request['sample_id']; cid = request['case_id']
    sample, _, receipt, source, _, _ = packet(store, sid, cid); events = {e['id']:e for e in source}
    inputs = condition_reviews.inputs(store,receipt) if sample.get('review_kind') == 'rollout_condition' else None
    refs = request['citations']
    require(isinstance(refs,list) and 1 <= len(refs) <= 32, 'Cite 1–32 source passages or input records supporting this judgment')
    citations = []; seen = set()
    for ref in refs:
        require(isinstance(ref,dict), 'A citation must be an object')
        key=digest(ref); require(key not in seen, 'Duplicate review citation'); seen.add(key)
        if inputs is not None and set(ref) != {'event_id','start','end'}:
            citations.append(condition_reviews.citation(ref,inputs));continue
        require(isinstance(ref,dict) and set(ref) == {'event_id','start','end'}, 'A citation needs event ID and exact offsets')
        require(isinstance(ref['event_id'],str),'A citation needs a source event ID')
        event = events.get(ref['event_id']); start = ref['start']; end = ref['end']
        require(event and type(start) is int and type(end) is int and 0 <= start < end <= len(event['text']), 'Citation is outside this review source')
        citations.append({**ref, 'text':event['text'][start:end]})
    value = {'schema':LABEL_VERSION, **deepcopy(request), 'citations':citations}
    lid = 'review-label-'+digest(value)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        existing = c.execute('SELECT id FROM measurement_review_labels WHERE id=?', (lid,)).fetchone()
        if not existing:
            prior = c.execute('SELECT id FROM measurement_review_labels WHERE sample_id=? AND case_id=? AND reviewer=? ORDER BY rowid DESC LIMIT 1',
                (sid,cid,request['reviewer'])).fetchone()
            require(request['supersedes'] == (prior[0] if prior else None), 'Review changed; reload before revising it')
            c.execute('INSERT INTO measurement_review_labels VALUES (?,?,?,?,?,?)',
                (lid,sid,cid,request['reviewer'],dumps(value),datetime.now(timezone.utc).isoformat()))
    return {'annotation_id':lid, 'sample':public(store,sid), 'case':case_view(store,sid,cid,request['reviewer'])}


def public(store, sid):
    sample = load(store,sid); current = labels(store,sid); frame = {r['id']:r for r in sample['frame']}
    reports = []
    for reviewer in sorted({key[1] for key in current}):
        counts = Counter(); roles = set()
        for cid in sample['sample_ids']:
            label = current.get((cid,reviewer))
            if not label: continue
            counts['reviewed'] += 1; roles.add(label['reviewer_role'])
            reference = label['label']; predicted = frame[cid]['prediction']
            if reference == 'not_opportunity': counts['scope_agreements' if frame[cid].get('predicted_scope') == 'outside' else 'scope_unresolved' if frame[cid].get('predicted_scope') == 'unresolved' else 'eligibility_disputes'] += 1
            elif reference == 'unknown': counts['reference_unknown'] += 1
            elif predicted is None:
                counts['prediction_unknown_with_decidable_reference'] += 1
                if frame[cid].get('predicted_scope') == 'outside':counts['eligibility_disputes'] += 1
            else:
                actual = reference == 'taken'; counts['comparable'] += 1
                counts['agree' if predicted == actual else 'false_positive' if predicted else 'false_negative'] += 1
        reports.append({'reviewer':reviewer, 'declared_roles':sorted(roles), **dict(counts),
            'agreement':counts['agree']/counts['comparable'] if counts['comparable'] else None,
            'unreviewed':len(sample['sample_ids'])-counts['reviewed']})
    return {'id':sid, **{key:sample[key] for key in ('schema','monitor_id','run_ids','measurement_ids','seed','requested_size','selection','limits','frame_hash','runs_without_case_frame')},
        'monitor_name':sample['monitor']['name'], 'question':question(sample),'review_kind':sample.get('review_kind','opportunity'),
        'frame_cases':len(frame), 'sample_size':len(sample['sample_ids']),
        'cases':[{'id':cid,'run_id':frame[cid]['run_id'],'reviewed_by':sorted(name for key,name in current if key == cid)} for cid in sample['sample_ids']],
        'reviewers':reports, 'independence':'Reviewer roles are self-declared. Results from different reviewers are not pooled.'}


def question(sample):
    if sample.get('review_kind')=='rollout_condition':
        return sample.get('condition_question') or condition_reviews.question(sample['monitor'])
    return sample['monitor']['analysis_definition']['description']


def listing(store, monitor_id):
    initialize(store)
    with store.connect() as c:
        rows = c.execute('SELECT id FROM measurement_review_samples WHERE monitor_id=? ORDER BY created_at DESC LIMIT 50', (monitor_id,)).fetchall()
    return [public(store,row[0]) for row in rows]
