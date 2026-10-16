"""Authored integration controls, not labels for semantic model accuracy."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError,digest
from tracker.store import Store
from tracker import graph_store,semantic_workspace as workspace,semantic_watch as watch
from tracker.semantic_extraction import load_extraction,read,write
from tracker.semantic_layers import REQUESTED_PROFILE
from tracker import requested_work as work
from tests.test_semantic_layers import GENERATOR as BASE_GENERATOR,response as base_response


GENERATOR=BASE_GENERATOR.replace("if r.get('stage')=='content':",'''if r.get('stage')=='requested_work_candidates':
 previous=r['previous_records'];old=next((x for x in previous if x['id']=='delivery'),None)
 clauses=[{'id':'pdf','kind':'requirement','text':'Save a PDF.','evidence':[e]},
          {'id':'compare','kind':'requested_check','text':s['text'],'evidence':[e]}]
 if old:clauses[0]=old['clauses'][0]
 edit={'op':'revise' if old else 'introduce','record_id':'delivery','text':s['text'],
       'evidence':[e],'clauses':clauses,'retired_clauses':[]}
 if not old:edit['kind']='condition'
 print(json.dumps({'citation_format':'source-quotes/1','candidates':[{'edits':[edit]}]}))
elif r.get('stage')=='content':''')
# Preserve previously selected offset citations when retaining unchanged clauses.
GENERATOR=GENERATOR.replace("'citation_format':'source-quotes/1','candidates':[{'edits'", "'citation_format':'source-references/1','candidates':[{'edits'")


def source(revised=False):
    entries=[{'step':0,'user_message':'Save a PDF. Compare the two models.',
        'agent':{'thought':'I will deliver the report.','action':None},'environment':None}]
    if revised:
        entries.append({'step':1,'user_message':'Keep the PDF; instead compare three models.',
            'agent':{'thought':'The comparison is finished.','action':None},'environment':None})
    return normalize({'trajectory_format':'devai/1','trajectory':entries},'auto',{'experiment':'terms-control'})[0]


def response(req):
    if req['state']['stage']!='requested_work':return base_response(req)
    return {'model':req['model'],'answers':{'choice':{'type':'choice',
        'probabilities':{key:int(key=='c0') for key in req['questions']['choice']['criteria']}}},
        'usage':{'input_tokens':10,'output_tokens':2}}


class RequestedLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.directory=self.root/'worker';self.store=Store(self.root/'study.sqlite')
        script=self.root/'proposer.py';script.write_text(GENERATOR,encoding='utf-8');self.command=[sys.executable,str(script)]
        self.cap={'jev_requests':80,'candidate_requests':80,'input_bytes':4_000_000}

    def init(self,command=True,cap=None):
        return watch.initialize(self.store,self.directory,experiment='terms-control',label='Requested terms',
            workspace_options={'requested_profile':REQUESTED_PROFILE},allowance=cap or self.cap,
            command=self.command if command else None,producer='authored-terms/1' if command else None)

    def run_worker(self,transport=response,command=True,**options):
        return watch.run_once(self.store,self.directory,transport,command=self.command if command else None,**options)

    def seed_base(self,run,target):
        seed=self.root/'base';workspace.initialize(seed,run)
        workspace.execute(seed,response,command=self.command,producer='authored-terms/1',budget_limits=self.cap)
        workspace.initialize(target,run,requested_profile=REQUESTED_PROFILE)
        for name in ('candidates','decisions'):shutil.copytree(seed/name,target/name)
        return seed

    def test_requested_checks_and_revisions_survive_publication_and_restart(self):
        self.init();run=source(True);self.store.add([run]);done=self.run_worker()
        self.assertEqual(done['job_counts'],{'published':1})
        root=self.directory/'runs'/run['id'];bundle=load_extraction(run,root)
        records=read(work.path_for(root,bundle['raw_extraction']))['records']
        self.assertEqual(len(records),1);record=records[0]
        self.assertEqual(record['status'],'requested') # Agent completion prose cannot satisfy a condition.
        self.assertEqual([c['kind'] for c in record['clauses']],['requirement','requested_check'])
        history=read(work.path_for(root,bundle['raw_extraction']))
        self.assertEqual(history['changes'][0]['after']['clauses'][0],history['changes'][1]['after']['clauses'][0])
        self.assertNotEqual(history['changes'][0]['after']['clauses'][1]['version_id'],record['clauses'][1]['version_id'])
        self.assertTrue(workspace.audit(root)['requested_layer']['argmax_replayed'])
        graph=graph_store.read(self.store,done['jobs'][0]['details']['graph_id'])
        self.assertIn('requested_clause_version',{n.get('kind') for n in graph['nodes']})
        self.store=Store(self.store.path)
        again=self.run_worker(lambda _:self.fail('Published requirements must not spend again'))
        self.assertEqual(again['used'],done['used'])
        self.assertEqual(done['used']['candidate_requests'],sum(read(p)['candidate_calls_this_execution'] for p in (root/'executions').glob('*.json')))

    def test_file_arrival_resumes_requested_layer_without_reclassifying_base(self):
        self.init(command=False);run=source();self.store.add([run]);root=self.directory/'runs'/run['id']
        self.seed_base(run,root)
        waiting=self.run_worker(lambda _:self.fail('Base cache should suffice'),command=False)
        self.assertEqual(waiting['job_counts'],{'needs_candidates':1})
        self.assertEqual(waiting['jobs'][0]['details']['waiting_candidates']['stages'],{'requested_work_candidates':1})
        with self.assertRaisesRegex(InputError,'Requested conditions layer is incomplete'):load_extraction(run,root)
        reqpath=next((root/'work_candidates'/'requests').glob('*.json'));req=read(reqpath)
        out=root/'work_candidates'/'responses'/reqpath.name;out.parent.mkdir(parents=True)
        out.write_text('{',encoding='utf-8')
        self.assertEqual(self.run_worker(lambda _:self.fail('Partial JSON cannot wake'),command=False)['job_counts'],{'needs_candidates':1})
        process=subprocess.run(self.command,input=json.dumps({'request':req}),text=True,capture_output=True,check=True)
        write(out,{**json.loads(process.stdout),'request_hash':digest(req),'producer':'authored-terms/1'})
        stages=[]
        def choose(req):stages.append(req['state']['stage']);return response(req)
        done=self.run_worker(choose,command=False)
        self.assertEqual(stages,['requested_work']);self.assertEqual(done['current_published'],1)

    def test_candidate_budget_is_shared_and_survives_restart(self):
        self.init(cap={**self.cap,'candidate_requests':0});run=source();self.store.add([run]);root=self.directory/'runs'/run['id']
        self.seed_base(run,root)
        stopped=self.run_worker(lambda _:self.fail('No requested candidate yet'))
        self.assertEqual(stopped['job_counts'],{'budget_reached':1});self.assertEqual(stopped['current_published'],0)
        self.store=Store(self.store.path)
        self.assertEqual(self.run_worker(lambda _:self.fail('Restart cannot replenish allowance'))['used'],stopped['used'])
        watch.set_allowance(self.store,self.directory,{**self.cap,'candidate_requests':1})
        stages=[]
        def choose(req):stages.append(req['state']['stage']);return response(req)
        done=self.run_worker(choose,retry_runs=[run['id']])
        self.assertEqual(stages,['requested_work']);self.assertEqual(done['used']['candidate_requests'],1)
        self.assertEqual(done['current_published'],1)

    def test_exact_requested_cache_works_with_zero_new_allowance(self):
        run=source();first=self.root/'first';second=self.root/'second'
        for path in (first,second):workspace.initialize(path,run,requested_profile=REQUESTED_PROFILE)
        workspace.execute(first,response,command=self.command,producer='authored-terms/1',budget_limits=self.cap)
        done=workspace.execute(second,lambda _:self.fail('Exact cache must not call Jev'),
            command=self.command,producer='authored-terms/1',budget_limits=watch.ZERO,cache_directories=[first])
        self.assertEqual(done['status'],'complete_local_extraction')
        self.assertEqual(done['last_execution']['candidate_calls_this_execution'],0)
        self.assertTrue(workspace.audit(second)['requested_layer']['argmax_replayed'])

    def test_rejected_candidate_is_not_published_or_retried_until_edited(self):
        self.init(command=False);run=source();self.store.add([run]);root=self.directory/'runs'/run['id']
        self.seed_base(run,root);self.run_worker(command=False)
        path=next((root/'work_candidates'/'requests').glob('*.json'));req=read(path)
        out=root/'work_candidates'/'responses'/path.name
        write(out,{'request_hash':digest(req),'producer':'authored-terms/1','candidates':[]})
        def reject(req):
            value=response(req)
            value['answers']['choice']['probabilities']={k:int(k=='no_suitable_candidate') for k in req['questions']['choice']['criteria']}
            return value
        stopped=self.run_worker(reject,command=False)
        self.assertEqual(stopped['current_published'],0)
        self.assertEqual(self.run_worker(lambda _:self.fail('Unchanged rejection cannot respend'),command=False)['used'],stopped['used'])
        process=subprocess.run(self.command,input=json.dumps({'request':req}),text=True,capture_output=True,check=True)
        write(out,{**json.loads(process.stdout),'request_hash':digest(req),'producer':'authored-terms/1'})
        self.assertEqual(self.run_worker(command=False)['current_published'],1)

    def test_profile_cannot_load_a_saved_layer_from_another_context_policy(self):
        root=self.root/'pass';run=source();workspace.initialize(root,run,requested_profile=REQUESTED_PROFILE)
        workspace.execute(root,response,command=self.command,producer='authored-terms/1',budget_limits=self.cap)
        extraction=read(root/'results'/f'{run["id"]}.json');path=work.path_for(root,extraction)
        saved=read(path);saved['context_policy']=None;write(path,saved)
        with self.assertRaisesRegex(InputError,'pinned profile'):load_extraction(run,root)

    def test_feedback_and_requested_layers_publish_together(self):
        from tracker.semantic_layers import FEEDBACK_PROFILE
        from tests.test_semantic_layers import source as feedback_source
        run=feedback_source(texts=('The status is ready.',));run['metadata']['experiment']='terms-control'
        watch.initialize(self.store,self.directory,experiment='terms-control',label='Terms and feedback',
            workspace_options={'requested_profile':REQUESTED_PROFILE,'feedback_profile':FEEDBACK_PROFILE},
            command=self.command,producer='authored-terms/1',allowance=self.cap)
        self.store.add([run]);done=self.run_worker()
        self.assertEqual(done['current_published'],1)
        layers=done['jobs'][0]['details']['layers']
        self.assertTrue(layers['feedback']['argmax_replayed']);self.assertTrue(layers['requested_conditions']['argmax_replayed'])

    def test_invalid_profile_or_agent_only_is_rejected_before_creation(self):
        for changes in ({'requested_profile':'typo'},{'requested_profile':REQUESTED_PROFILE,'include_user':False}):
            path=self.root/'invalid'
            with self.assertRaises(InputError):workspace.initialize(path,source(),**changes)
            self.assertFalse(path.exists())
            with self.assertRaises(InputError):watch.initialize(self.store,path,experiment='terms-control',label='Invalid',workspace_options=changes)
            self.assertFalse(path.exists())

    def test_cli_pins_layer_without_authorizing_spend(self):
        process=subprocess.run([sys.executable,'-m','rilldex','--db',str(self.store.path),'semantic','watch-init',
            str(self.directory),'--experiment','terms-control','--label','Terms','--requested-conditions'],text=True,capture_output=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout)['allowance'],watch.ZERO)
        self.assertEqual(read(self.directory/'watch.json')['workspace_options']['requested_profile'],REQUESTED_PROFILE)


if __name__=='__main__':unittest.main()
