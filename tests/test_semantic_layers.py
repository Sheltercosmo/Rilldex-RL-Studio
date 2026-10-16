"""Authored lifecycle controls; selections are not semantic accuracy labels."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError,digest
from tracker.store import Store
from tracker import feedback_opportunities,graph_store,semantic_catalog,semantic_watch as watch,semantic_workspace as workspace
from tracker.semantic_extraction import load_extraction,read
from tracker.semantic_layers import FEEDBACK_PROFILE

GENERATOR='''import json,sys
r=json.load(sys.stdin)['request'];s=r['source'];e={'event_id':s['event_id'],'quote':s['text']}
if r.get('stage')=='content':
 fields={k:{'status':'not_expressed'} for k in r['field_contract']}
 fields['summary']={'status':'expressed','text':s['text'],'evidence':[e]}
 print(json.dumps({'citation_format':'source-quotes/1','candidates':[{'fields':fields}]}))
elif r.get('stage')=='activity_readings':
 event=next(e for e in r['prefix'] if e['id']==s['event_id'])
 print(json.dumps({'readings':[{'activity':'inspect' if event['kind']=='action' else 'report','text':s['text'],'evidence':[e]}]}))
else:
 print(json.dumps({'partitions':[{'units':[{'quote':s['text']}],'contributions':[s['text']],'rationale':'One authored contribution in this control.'}]}))
'''


def source(name='a',texts=('The status is ready.','Proceed with the task.','Here is the result.')):
    return normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Complete task '+name,'agent':{'thought':None,'action':'Inspect status'},'environment':'Status: ready.'},
        *[{'step':i+1,'user_message':None,'agent':{'thought':text,'action':None},'environment':None} for i,text in enumerate(texts)]
    ]},'auto',{'experiment':'layer-test'})[0]


def response(req,feedback='f0'):
    stage=req['state']['stage']
    if stage=='activity':choice='inspect' if req['state']['expression_form']=='recorded action dispatch' else 'report'
    else:choice={'partition':'p0','content':'c0','feedback_assessment':feedback}[stage]
    return {'model':req['model'],'answers':{'choice':{'type':'choice',
        'probabilities':{key:int(key==choice) for key in req['questions']['choice']['criteria']}}},
        'usage':{'input_tokens':10,'output_tokens':2}}


class SemanticLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.work=self.root/'worker';self.store=Store(self.root/'study.sqlite')
        script=self.root/'proposer.py';script.write_text(GENERATOR,encoding='utf-8');self.command=[sys.executable,str(script)]
        self.cap={'jev_requests':50,'candidate_requests':50,'input_bytes':2_000_000}

    def init(self,**changes):
        return watch.initialize(self.store,self.work,experiment='layer-test',label='Activities and feedback',
            command=self.command,producer='authored-lifecycle-control/1',allowance=changes.get('allowance',self.cap),
            workspace_options={'include_user':False,'feedback_profile':FEEDBACK_PROFILE})

    def run_worker(self,transport=response,**options):
        return watch.run_once(self.store,self.work,transport,command=self.command,**options)

    def test_cross_activity_feedback_is_published_with_graph_and_coverage_aware_measure(self):
        observer=self.init()['observer'];run=source();self.store.add([run])
        completed=self.run_worker()
        self.assertEqual(completed['job_counts'],{'published':1})
        self.assertEqual(completed['used']['jev_requests'],14)
        self.assertEqual(completed['provider_usage']['providers']['jev']['stages']['feedback_assessment'],3)
        view=semantic_catalog.load(run,observer,self.store)
        units=view['raw_extraction']['units']
        self.assertEqual([u['activity'] for u in units],['inspect','report','report','report'])
        links=[r for r in view['document']['relations'] if r['type']=='assesses']
        self.assertEqual(len(links),3)
        graph=graph_store.read(self.store,completed['jobs'][0]['details']['graph_id'])
        measure=feedback_opportunities.project(graph)
        self.assertEqual(measure['metrics']['value'],1)
        self.assertEqual(measure['metrics']['unknown'],0)
        audit=workspace.audit(self.work/'runs'/run['id'])
        self.assertTrue(audit['feedback_layer']['argmax_replayed'])
        repeated=self.run_worker(lambda _:self.fail('Published layers cannot rerun inference'))
        self.assertEqual(repeated['used'],completed['used'])

    def test_budget_pause_after_base_preserves_layer_cache_and_blocks_partial_publication(self):
        self.init(allowance={**self.cap,'jev_requests':12});run=source();self.store.add([run])
        first=self.run_worker();directory=self.work/'runs'/run['id']
        self.assertEqual(first['job_counts'],{'budget_reached':1})
        self.assertEqual(first['current_published'],0)
        saved=read(directory/'results'/f'{run["id"]}.json');before=digest(saved)
        self.assertEqual(saved['status'],'complete_local_extraction')
        self.assertEqual(workspace.status(directory)['layers']['feedback']['status'],'pending')
        with self.assertRaisesRegex(InputError,'Feedback layer is incomplete'):load_extraction(run,directory)
        from tracker.observer_archive import rows as archived
        self.assertEqual(archived(self.store),[])
        self.store=Store(self.store.path)
        self.assertEqual(self.run_worker(lambda _:self.fail('No automatic retry'))['used'],first['used'])
        watch.set_allowance(self.store,self.work,{**self.cap,'jev_requests':14})
        calls=[]
        def only_pending(req):
            self.assertEqual(req['state']['stage'],'feedback_assessment');calls.append(digest(req));return response(req)
        done=self.run_worker(only_pending,retry_runs=[run['id']])
        self.assertEqual(done['current_published'],1);self.assertEqual(len(calls),2)
        self.assertEqual(done['used']['jev_requests'],14)
        self.assertEqual(digest(read(directory/'results'/f'{run["id"]}.json')),before)

    def test_failed_relationship_attempt_is_counted_and_requires_explicit_retry(self):
        self.init();run=source(texts=('The status is ready.',));self.store.add([run]);calls=[]
        def failing(req):
            calls.append(req['state']['stage'])
            if calls[-1]=='feedback_assessment':raise RuntimeError('private provider fault')
            return response(req)
        failed=self.run_worker(failing)
        self.assertEqual(failed['job_counts'],{'failed':1});self.assertEqual(failed['used']['jev_requests'],6)
        self.assertNotIn('private provider fault',json.dumps(failed))
        self.store=Store(self.store.path)
        self.run_worker(lambda _:self.fail('Restart cannot retry the failed call'))
        done=self.run_worker(retry_runs=[run['id']]);self.assertEqual(done['used']['jev_requests'],7)
        self.assertEqual(done['current_published'],1)

    def test_negative_selection_needs_complete_opportunity_window(self):
        self.init();long=source();short=source('b',('Nothing to add.',));self.store.add([long,short])
        done=self.run_worker(lambda req:response(req,'none_of_these'))
        rows={}
        for job in done['jobs']:
            rows[job['run_id']]=feedback_opportunities.project(graph_store.read(self.store,job['details']['graph_id']))
        self.assertEqual(rows[long['id']]['metrics']['value'],0)
        self.assertIsNone(rows[short['id']]['metrics']['value'])
        self.assertIn('window_not_fully_observed',rows[short['id']]['coverage']['unknown_reasons'])

    def test_source_revision_during_feedback_cannot_publish_stale_layers(self):
        self.init();run=source(texts=('The status is ready.',))
        payload={'producer':'test','rollout_id':'one','revision':0,'state':'complete',
            'document':run['raw'],'metadata':{'experiment':'layer-test'}}
        first=self.store.ingest(payload);changed=[]
        def supersede(req):
            if req['state']['stage']=='feedback_assessment' and not changed:
                new=copy.deepcopy(payload);new['revision']=1;new['state']='in_progress'
                changed.append(self.store.ingest(new))
            return response(req)
        done=self.run_worker(supersede)
        self.assertTrue(changed);self.assertEqual(done['current_published'],0)
        self.assertEqual(done['job_counts'],{'superseded':1})

    def test_invalid_profiles_fail_before_creating_a_workspace(self):
        for invalid in ['other',{},[]]:
            with self.assertRaises(InputError):workspace.initialize(self.root/'invalid',source(),feedback_profile=invalid)
        self.assertFalse((self.root/'invalid').exists())

    def test_cli_profile_is_explicit_and_keeps_zero_default_allowance(self):
        proc=subprocess.run([sys.executable,'-m','rilldex','--db',str(self.store.path),'semantic','watch-init',
            str(self.work),'--experiment','layer-test','--label','Activities and feedback','--feedback-references'],
            capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['allowance'],watch.ZERO)
        self.assertEqual(read(self.work/'watch.json')['workspace_options']['feedback_profile'],FEEDBACK_PROFILE)


if __name__=='__main__':unittest.main()
