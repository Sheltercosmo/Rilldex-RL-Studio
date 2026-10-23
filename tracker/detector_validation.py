"""Reusable frozen review labels and versioned detector comparisons.

No detector code runs on a read or a browser request. Saved monitor results and
explicit Python evaluations share the same case-level results and coverage.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json

from .schema import InputError, digest, dumps
from . import measurement_reviews as reviews, condition_reviews, monitor_evidence, monitoring

SET_VERSION='detector-validation-set/1'
RESULT_VERSION='detector-validation-result/1'
SPLITS={'development','held_out','all'}
STATUSES={'decided','unresolved','missing','error','not_applicable','changed_inputs'}


def require(value,message):
    if not value:raise InputError(message)


def initialize(store):
    reviews.initialize(store)
    with store.connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS detector_validation_sets(
            id TEXT PRIMARY KEY,name TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS detector_validation_results(
            id TEXT PRIMARY KEY,set_id TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS detector_validation_scope ON detector_validation_results(set_id,created_at);''')


def save(store,table,prefix,doc):
    identifier=prefix+digest(doc);now=datetime.now(timezone.utc).isoformat()
    with store.connect() as c:
        c.execute('INSERT OR IGNORE INTO '+table+' VALUES (?,?,?,?)',
                  (identifier,doc['name'] if table.endswith('_sets') else doc['set_id'],dumps(doc),now))
    return {'id':identifier,**doc}


def load(store,identifier,result=False):
    initialize(store)
    table='detector_validation_results' if result else 'detector_validation_sets'
    prefix='validation-result-' if result else 'validation-set-'
    with store.connect() as c:row=c.execute('SELECT document FROM '+table+' WHERE id=?',(identifier,)).fetchone()
    if row is None:raise KeyError(identifier)
    doc=json.loads(row[0]);require(prefix+digest(doc)==identifier,'Saved validation content changed')
    return {'id':identifier,**doc}


def signature(monitor):
    if condition_reviews.supported(monitor):return ('rollout_condition',condition_reviews.question(monitor))
    if monitor['kind']=='analysis' and monitor['analysis_definition']['aggregation']=='opportunity_ratio':
        return ('opportunity',monitor['analysis_definition']['description'])
    return None


def external_inputs(store,receipt):
    if not condition_reviews.supported(receipt['monitor']):return None
    data=condition_reviews.inputs(store,receipt)
    return {k:data[k] for k in ('declared_inputs','evaluator_inputs','evaluator_reports')}


def create(store,body):
    require(isinstance(body,dict) and set(body)=={'name','sample_ids','reviewer','seed','held_out_percent'},
            'Supply name, sample_ids, reviewer, seed and held_out_percent')
    require(reviews.text(body['name'],160) and reviews.text(body['reviewer'],160) and reviews.text(body['seed'],160),
            'Name the validation set, reviewer and split seed')
    ids=body['sample_ids'];percent=body['held_out_percent']
    require(isinstance(ids,list) and 1<=len(ids)<=20 and all(reviews.text(s,100) for s in ids) and len(set(ids))==len(ids),
            'Select 1–20 distinct review samples')
    require(type(percent) is int and 0<=percent<=100,'Held-out percentage must be 0–100')
    initialize(store);cases={};target=None;unreviewed=0;excluded=set()
    for sid in sorted(ids):
        sample=reviews.load(store,sid);current=reviews.labels(store,sid)
        sig=(sample.get('review_kind','opportunity'),reviews.question(sample))
        require(target is None or sig==target,'Samples must review the same question and case type')
        target=sig;excluded.update(sample['runs_without_case_frame'])
        for cid in sample['sample_ids']:
            label=current.get((cid,body['reviewer']))
            if label is None:unreviewed+=1;continue
            _,row,receipt,_,_,_=reviews.packet(store,sid,cid)
            run=receipt['run'];key=digest([run['id'],row['case_id']])
            if key in cases:
                require(cases[key]['label']['label']==label['label'],'Duplicate cases have conflicting labels; select a single reference sample')
                continue
            metadata=run.get('metadata',{});task=metadata.get('task_id')
            if task:group=['task',metadata.get('environment'),task]
            else:
                with store.connect() as c:identity=c.execute('SELECT producer,rollout_id FROM rollout_revisions WHERE run_id=? ORDER BY producer,rollout_id LIMIT 1',(run['id'],)).fetchone()
                group=['rollout',*identity] if identity else ['source',run['id']]
            split='held_out' if int(digest([body['seed'],group])[:12],16)%100<percent else 'development'
            cases[key]=dict(id='validation-case-'+key,sample_id=sid,review_case_id=cid,run_id=run['id'],
                native_case_id=row['case_id'],source_hash=digest(run),measurement_id=row['measurement_id'],
                split=split,split_group=group,title=str(task or 'Rollout case'),label=deepcopy(label),
                external_inputs=external_inputs(store,receipt))
    require(cases,'No saved judgments from this reviewer in the selected samples')
    document=dict(schema=SET_VERSION,name=body['name'].strip(),reviewer=body['reviewer'],review_kind=target[0],question=target[1],
        sample_ids=sorted(ids),split_policy=dict(seed=body['seed'],held_out_percent=percent,grouping='task when recorded; otherwise logical rollout/source'),
        cases=sorted(cases.values(),key=lambda x:x['id']),unreviewed_cases=unreviewed,runs_without_case_frame=sorted(excluded),
        boundary='Frozen reviewed cases, not a population accuracy estimate. Held-out is an assigned split, not proof that cases were unseen during development.')
    return save(store,'detector_validation_sets','validation-set-',document)


def selected(document,split):
    require(isinstance(split,str) and split in SPLITS,'Choose development, held_out or all')
    return [c for c in document['cases'] if split=='all' or c['split']==split]


def case_input(store,document,case):
    _,_,receipt,source,witness,focus=reviews.packet(store,case['sample_id'],case['review_case_id'])
    require(digest(receipt['run'])==case['source_hash'],'Validation source changed')
    # Reference labels and earlier predictions are intentionally not callback inputs.
    return dict(id=case['id'],run_id=case['run_id'],source_hash=case['source_hash'],question=document['question'],
                review_kind=document['review_kind'],source_events=source,witness_event_ids=sorted(witness),focus_spans=focus,
                **({'run':deepcopy(receipt['run'])} if document['review_kind']=='rollout_condition' else {'metadata':deepcopy(receipt['run'].get('metadata',{}))}),
                external_inputs=deepcopy(case['external_inputs']))


def case_view(store,set_id,case_id):
    doc=load(store,set_id);case=next((c for c in doc['cases'] if c['id']==case_id),None)
    require(case is not None,'Case is outside this validation set')
    return {**case_input(store,doc,case),'reference':case['label'],'split':case['split'],
            'review_url':'/measurement-review?sample='+case['sample_id']+'&case='+case['review_case_id']}


def normalize_prediction(row):
    require(isinstance(row,dict) and not set(row)-{'case_id','value','status','reason','measurement_id'},'Invalid prediction fields')
    status=row.get('status','decided' if type(row.get('value')) is bool else 'unresolved')
    require(isinstance(status,str) and status in STATUSES,'Invalid prediction status')
    require(type(row.get('value')) is bool if status=='decided' else row.get('value') is None,'A decided prediction needs true/false; other statuses use null')
    require(isinstance(row.get('reason',''),str) and len(row.get('reason',''))<=4000,'Reason must contain at most 4000 characters')
    return {**row,'status':status,'value':row.get('value'),'reason':row.get('reason','')}


def report(cases,predictions):
    counts=Counter();rows=[]
    for case in cases:
        p=predictions[case['id']];ref=case['label']['label'];counts['cases']+=1;counts[p['status']]+=1
        if ref=='unknown':outcome='reference_unknown'
        elif ref=='not_opportunity':outcome='scope_agreement' if p['status']=='not_applicable' else 'scope_unresolved' if p['value'] is None else 'scope_disagreement'
        else:
            positive=ref=='taken';counts['reference_positive' if positive else 'reference_negative']+=1
            if p['value'] is None:outcome='prediction_unavailable'
            else:outcome=('true_positive' if positive else 'false_positive') if p['value'] else ('false_negative' if positive else 'true_negative')
        counts[outcome]+=1
        rows.append(dict(case_id=case['id'],run_id=case['run_id'],title=case['title'],split=case['split'],reference=ref,
                         label_id=case['label']['id'],outcome=outcome,**{k:v for k,v in p.items() if k!='case_id'}))
    ratio=lambda a,b:a/b if b else None
    tp,tn,fp,fn=(counts[k] for k in ('true_positive','true_negative','false_positive','false_negative'))
    jointly=tp+tn+fp+fn;reference=counts['reference_positive']+counts['reference_negative']
    return dict(counts=dict(counts),coverage=ratio(jointly,reference),agreement=ratio(tp+tn,jointly),
                precision=ratio(tp,tp+fp),recall_on_decided=ratio(tp,tp+fn),positive_detection_coverage=ratio(tp,counts['reference_positive']),rows=rows)


def publish(store,body):
    require(isinstance(body,dict) and set(body)=={'set_id','split','detector','predictions'},'Supply set_id, split, detector and predictions')
    document=load(store,body['set_id']);cases=selected(document,body['split'])
    require(cases,'This split has no labeled cases')
    detector=body['detector']
    require(isinstance(detector,dict) and reviews.text(detector.get('name'),160) and reviews.text(detector.get('version'),240),
            'Give the detector a name and explicit version')
    # Keep arbitrary version/config metadata serializable, bounded, and separate from labels.
    require(len(dumps(detector))<=100000,'Detector definition is too large')
    values=body['predictions'];require(isinstance(values,list) and len(values)<=len(cases),'Too many predictions')
    known={c['id'] for c in cases};predictions={}
    for raw in values:
        require(isinstance(raw,dict) and isinstance(raw.get('case_id'),str) and raw['case_id'] in known and raw['case_id'] not in predictions,
                'Predictions need distinct case IDs from this split')
        row=normalize_prediction(raw)
        if row.get('measurement_id'):
            receipt=monitor_evidence.read(store,row['measurement_id']);case=next(c for c in cases if c['id']==row['case_id'])
            require(receipt['run']['id']==case['run_id'] and digest(receipt['run'])==case['source_hash'],'Prediction evidence belongs to another source')
        predictions[row['case_id']]=row
    for case in cases:
        predictions.setdefault(case['id'],dict(case_id=case['id'],value=None,status='missing',reason='No prediction supplied for this frozen case'))
    result=dict(schema=RESULT_VERSION,set_id=document['id'],split=body['split'],detector=deepcopy(detector),
                report=report(cases,predictions),boundary='Agreement and recall_on_decided use jointly decidable cases. Coverage and positive_detection_coverage include unavailable predictions. References are frozen reviewer judgments.')
    return save(store,'detector_validation_results','validation-result-',result)


def capture(store,body):
    require(isinstance(body,dict) and set(body)=={'set_id','split','monitor_id'},'Select a validation set, split and saved monitor version')
    doc=load(store,body['set_id']);cases=selected(doc,body['split'])
    monitor=next((m for m in monitoring.definitions(store) if m['id']==body['monitor_id']),None)
    require(monitor and signature(monitor)==(doc['review_kind'],doc['question']),'Monitor must measure the validation set’s question and case type')
    predictions=[]
    for case in cases:
        with store.connect() as c:latest=c.execute('SELECT value_id FROM monitor_latest WHERE monitor_id=? AND run_id=?',(monitor['id'],case['run_id'])).fetchone()
        if latest is None:continue
        receipt=monitor_evidence.read(store,latest[0]);value=receipt['measurement']
        require(digest(receipt['run'])==case['source_hash'],'Saved result belongs to a different source')
        result=dict(case_id=case['id'],value=None,status='unresolved',measurement_id=latest[0],reason=value.get('reason') or '')
        if doc['review_kind']=='rollout_condition':
            if external_inputs(store,receipt)!=case['external_inputs']:
                result.update(status='changed_inputs',reason='Declared inputs or evaluator records differ from the labeled case')
            else:
                row=condition_reviews.frame_row(receipt,latest[0]);result['value']=row['prediction']
                result['status']='not_applicable' if row['predicted_scope']=='outside' else 'decided' if row['prediction'] is not None else 'error' if value['status']=='error' else 'unresolved'
        else:
            found=next((r for r in (value.get('analysis') or {}).get('measurement',{}).get('cases',[]) if r['id']==case['native_case_id']),None)
            result.update(value=found['taken'] if found else None,status='decided' if found and found['taken'] is not None else 'unresolved' if found else 'missing',
                          reason='' if found else 'The saved detector result did not produce this frozen opportunity case')
        predictions.append(result)
    return publish(store,dict(set_id=doc['id'],split=body['split'],detector=dict(name=monitor['name'],version=monitor.get('custom',{}).get('version',monitor['observer']),monitor=monitor),predictions=predictions))


def compare(store,left_id,right_id):
    left=load(store,left_id,True);right=load(store,right_id,True)
    require(left['set_id']==right['set_id'] and left['split']==right['split'],'Compare evaluations of the same frozen set and split')
    rows=[];counts=Counter();prior={r['case_id']:r for r in left['report']['rows']};correct={'true_positive','true_negative','scope_agreement'}
    wrong={'false_positive','false_negative','scope_disagreement'}
    for r in right['report']['rows']:
        l=prior[r['case_id']];a=l['outcome'];b=r['outcome']
        change='unchanged' if a==b and l['status']==r['status'] else 'improved' if a in wrong and b in correct else 'regressed' if a in correct and b in wrong else 'newly_decided' if a not in correct|wrong and b in correct|wrong else 'lost_coverage' if a in correct|wrong and b not in correct|wrong else 'changed'
        rows.append(dict(case_id=r['case_id'],change=change,before=l,after=r));counts[change]+=1
    return dict(set_id=left['set_id'],split=left['split'],left=left['id'],right=right['id'],counts=dict(counts),rows=rows)


def listing(store):
    initialize(store)
    with store.connect() as c:
        sets=[dict(id=r[0],**json.loads(r[1])) for r in c.execute('SELECT id,document FROM detector_validation_sets ORDER BY created_at DESC')]
        results=[dict(id=r[0],**json.loads(r[1])) for r in c.execute('SELECT id,document FROM detector_validation_results ORDER BY created_at DESC')]
        samples=[]
        for row in c.execute('SELECT id,document FROM measurement_review_samples ORDER BY created_at DESC LIMIT 200'):
            s=json.loads(row[1]);reviewers=[r[0] for r in c.execute('SELECT DISTINCT reviewer FROM measurement_review_labels WHERE sample_id=? ORDER BY reviewer',(row[0],))]
            samples.append(dict(id=row[0],monitor_id=s['monitor_id'],monitor_name=s['monitor']['name'],question=reviews.question(s),review_kind=s.get('review_kind','opportunity'),
                                size=len(s['sample_ids']),reviewers=reviewers))
    monitors=[dict(id=m['id'],name=m['name'],version=m.get('custom',{}).get('version',m['observer']),review_kind=signature(m)[0],question=signature(m)[1])
              for m in monitoring.definitions(store) if signature(m)]
    return dict(database=str(store.path.resolve()),sets=[{k:v for k,v in d.items() if k!='cases'}|{'counts':dict(Counter(c['split'] for c in d['cases']))} for d in sets],
                results=[{k:v for k,v in d.items() if k!='report'}|{'report':{k:v for k,v in d['report'].items() if k!='rows'}} for d in results],samples=samples,monitors=monitors)


class ValidationSet:
    """Execute explicit local callbacks over frozen source; reference labels stay separate."""
    def __init__(self,database,set_id):
        from .store import Store
        self.store=Store(database);self.document=load(self.store,set_id);self.id=set_id

    def evaluate(self,function,*,name,version,split='development'):
        require(callable(function),'Provide a local Python callback')
        require(reviews.text(name,160) and reviews.text(version,240),'Give the detector a name and explicit version before running it')
        predictions=[]
        for case in selected(self.document,split):
            try:
                raw=function(case_input(self.store,self.document,case))
                row=normalize_prediction({'value':raw} if raw is None or type(raw) is bool else raw)
            except Exception as error:row=dict(value=None,status='error',reason=str(error)[:4000])
            predictions.append({**row,'case_id':case['id']})
        return publish(self.store,dict(set_id=self.id,split=split,detector=dict(name=name,version=version,mode='local_callback'),predictions=predictions))
