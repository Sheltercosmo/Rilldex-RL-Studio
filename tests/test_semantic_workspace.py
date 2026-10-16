import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tracker import semantic_catalog, semantic_workspace as workspace
from tracker.schema import InputError, digest
from tracker.semantic_extraction import read, write,WORK_ORGANIZATION_ACTIVITY_ROUTING,ACTIVITY_ROUTING,activity_choices,load_extraction
from tracker.store import Store
from tests.test_semantic_extraction import fixture, response


GENERATOR = '''import json,sys
r=json.load(sys.stdin)['request'];s=r['source'];e={'event_id':s['event_id'],'quote':s['text']}
if r.get('stage')=='content':
 fields={k:{'status':'not_expressed'} for k in r['field_contract']}
 fields['summary']={'status':'expressed','text':'Identifies the missing decorator and calls for adding it.','evidence':[e]}
 print(json.dumps({'citation_format':'source-quotes/1','candidates':[{'fields':fields}]}))
elif r.get('stage')=='activity_readings':
 print(json.dumps({'readings':[{'activity':'orient','text':'Identifies the immediate correction needed.','evidence':[e]}]}))
else:
 print(json.dumps({'partitions':[{'units':[{'quote':s['text']}],'contributions':['Identifies the immediate correction needed.'],'rationale':'The missing decorator and immediate correction form one contribution.'}]}))
'''


class SemanticWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.work=self.root/'observer';self.run=fixture()
        self.script=self.root/'generator.py';self.script.write_text(GENERATOR,encoding='utf-8')
        self.command=[sys.executable,str(self.script)]
        workspace.initialize(self.work,self.run,include_user=False)

    def complete(self,transport=response):
        return workspace.execute(self.work,transport,command=self.command,producer='test generator/1')

    def test_full_pipeline_queues_then_runs_resumes_audits_and_registers_without_code_edits(self):
        prepared=workspace.prepare(self.work)
        self.assertEqual(prepared['candidate_requests'],1)
        self.assertFalse(prepared['last_complete_result_present'])
        pending=workspace.execute(self.work,lambda _:self.fail('No candidate should reach Jev'))
        self.assertEqual(pending['status'],'needs_work')
        finished=self.complete()
        self.assertEqual(finished['status'],'complete_local_extraction')
        self.assertEqual(finished['last_execution']['provider_responses_this_execution'],3)
        source=read(self.work/'runs'/f'{self.run["id"]}.json')
        self.assertEqual(source,self.run)
        again=self.complete(lambda _:self.fail('Exact saved decisions must be reused'))
        self.assertEqual(again['last_execution']['provider_responses_this_execution'],0)
        self.assertEqual(again['last_execution']['candidate_calls_this_execution'],0)
        audit=workspace.audit(self.work)
        self.assertEqual(audit['validation']['last_complete']['selected_units'],1)
        store=Store(self.root/'tracker.sqlite');store.add([self.run])
        with patch.object(semantic_catalog,'PROFILES',{}):
            registered=semantic_catalog.register(store,self.work,self.run['id'],'Portable pass')
            repeat=semantic_catalog.register(store,self.work,self.run['id'],'Portable pass')
            self.assertEqual(registered,repeat)
            catalog=semantic_catalog.catalog(store)
            self.assertEqual(len(catalog['maps']),1)
            loaded=semantic_catalog.load(self.run,registered['observer'],store)
            exported=semantic_catalog.export_payload(loaded)
            self.assertEqual(exported['map']['source_hash'],digest(self.run))
            self.assertEqual(digest(exported),loaded['export_digest'])

    def test_completed_wire_response_survives_failed_validation_and_retry(self):
        with self.assertRaisesRegex(InputError,'model mismatch'):
            self.complete(lambda _:{'model':'wrong','answers':{}})
        wires=list((self.work/'wire').rglob('*.json'))
        self.assertEqual(len(wires),1)
        self.assertEqual(read(wires[0])['response']['model'],'wrong')
        self.assertEqual(workspace.status(self.work)['last_execution']['status'],'interrupted')
        self.assertFalse((self.work/'results'/f'{self.run["id"]}.json').exists())
        self.assertEqual(self.complete()['status'],'complete_local_extraction')
        self.assertEqual(len(list((self.work/'wire').rglob('*.json'))),4)

    def test_new_routing_is_bound_through_candidates_selection_map_and_resume(self):
        self.work=self.root/'organization'
        workspace.initialize(self.work,self.run,include_user=False,activity_routing=WORK_ORGANIZATION_ACTIVITY_ROUTING)
        self.assertEqual(self.complete()['activity_routing'],WORK_ORGANIZATION_ACTIVITY_ROUTING)
        request=next(read(p) for p in (self.work/'candidates/requests').glob('*.json') if read(p).get('stage')=='activity_readings')
        self.assertEqual(request['activity_definitions'],activity_choices(WORK_ORGANIZATION_ACTIVITY_ROUTING))
        self.assertEqual(request['activity_routing'],WORK_ORGANIZATION_ACTIVITY_ROUTING)
        self.assertEqual(self.complete(lambda _:self.fail('Resume must use the saved decisions'))['last_execution']['provider_responses_this_execution'],0)
        self.assertEqual(workspace.audit(self.work)['validation']['last_complete']['selected_units'],1)
        doc=load_extraction(self.run,self.work)['document']
        self.assertEqual(doc['provenance']['activity_routing'],WORK_ORGANIZATION_ACTIVITY_ROUTING)
        with self.assertRaisesRegex(InputError,'configuration changed'):
            workspace.initialize(self.work,self.run,include_user=False)
        result=read(self.work/'results'/f'{self.run["id"]}.json')
        wrong=copy.deepcopy(result);wrong.pop('activity_routing')
        with self.assertRaisesRegex(InputError,'workspace configuration'):
            workspace.check_configuration(wrong,workspace.load(self.work)[0])

    def test_work_phase_boundary_standard_is_pinned_and_audited(self):
        self.work=self.root/'phase-boundaries'
        config=workspace.initialize(self.work,self.run,include_user=False,partition_standard='contribution-boundaries/4')
        self.assertEqual(self.complete()['status'],'complete_local_extraction')
        workspace.audit(self.work)
        result=read(self.work/'results'/f'{self.run["id"]}.json')
        request=read(self.work/'decisions'/f'{result["windows"][0]["partition_request"]}.json')['request']
        self.assertEqual(request['state']['partition_standard'],'contribution-boundaries/4')
        with self.assertRaisesRegex(InputError,'partition decision'):
            workspace.check_configuration(result,{**config,'partition_standard':'contribution-boundaries/3'},self.work)
        with self.assertRaisesRegex(InputError,'configuration changed'):
            workspace.initialize(self.work,self.run,include_user=False)

    def test_new_route_does_not_reuse_legacy_reading_candidates(self):
        config,_=workspace.load(self.work)
        legacy=workspace.provider(self.work,config)
        from tracker.semantic_extraction import windows
        ref=windows(self.run)[0]
        old=legacy.readings(self.run,ref)
        write(self.work/'candidates/responses'/f'{old["request_hash"]}.json',{
            'request_hash':old['request_hash'],'producer':'legacy fixture',
            'readings':[{'activity':'orient','text':'Local correction','evidence':[ref]}]})
        changed=workspace.provider(self.work,{**config,'activity_routing':WORK_ORGANIZATION_ACTIVITY_ROUTING})
        new=changed.readings(self.run,ref)
        self.assertNotEqual(new['request_hash'],old['request_hash'])
        self.assertEqual(new['status'],'needs_activity_readings')
        self.assertEqual(legacy.readings(self.run,ref)['status'],'ready')

    def test_unknown_routing_is_rejected_before_workspace_write(self):
        fresh=self.root/'unknown'
        with self.assertRaisesRegex(InputError,'Unknown semantic activity routing'):
            workspace.initialize(fresh,self.run,activity_routing='unknown')
        self.assertFalse(fresh.exists())

    def test_new_route_rejects_rehashed_criteria_changes_even_when_argmax_replays(self):
        from tracker.semantic_extraction import audit_result
        self.work=self.root/'criteria'
        workspace.initialize(self.work,self.run,include_user=False,activity_routing=WORK_ORGANIZATION_ACTIVITY_ROUTING)
        self.complete()
        result=read(self.work/'results'/f'{self.run["id"]}.json')
        unit=result['units'][0];saved=read(self.work/'decisions'/f'{unit["activity_request"]}.json')
        saved['request']['questions']['choice']['criteria']['orient']+=' Unversioned criterion change.'
        key=digest(saved['request']);write(self.work/'decisions'/f'{key}.json',saved)
        unit['activity_request']=key
        with self.assertRaisesRegex(InputError,'criteria differ from declared routing'):
            audit_result(self.run,result,self.work)

    def test_source_and_configuration_are_frozen_and_lock_is_process_owned(self):
        self.assertEqual(workspace.initialize(self.work,self.run,include_user=False),workspace.load(self.work)[0])
        with self.assertRaisesRegex(InputError,'configuration changed'):
            workspace.initialize(self.work,self.run,include_user=True)
        with workspace.exclusive(self.work):
            with self.assertRaisesRegex(InputError,'Another process'):
                with workspace.exclusive(self.work):pass
        workspace.prepare(self.work) # Leftover lock file is harmless.
        changed=copy.deepcopy(self.run);changed['events'][1]['text']='different source'
        write(self.work/'runs'/f'{self.run["id"]}.json',changed)
        with self.assertRaisesRegex(InputError,'source changed'):workspace.status(self.work)

    def test_registration_rejects_partial_and_detects_changed_derived_map(self):
        store=Store(self.root/'tracker.sqlite');store.add([self.run])
        workspace.execute(self.work,lambda _:self.fail('No candidates'))
        with self.assertRaisesRegex(InputError,'complete extraction'):
            semantic_catalog.register(store,self.work,self.run['id'],'Incomplete')
        self.complete()
        with patch.object(semantic_catalog,'PROFILES',{}):
            registered=semantic_catalog.register(store,self.work,self.run['id'],'Frozen')
            result=read(self.work/'results'/f'{self.run["id"]}.json')
            unit=result['units'][0]
            note={'schema':'semantic-source-review/1','source_hash':digest(self.run),
                  'extraction_hash':digest(result),'annotator':'test reviewer',
                  'notes':[{'text':'New review after registration','evidence':[unit['source']],'unit_ids':[unit['id']]}]}
            write(self.work/'reviews'/self.run['id']/f'{digest(result)}.json',note)
            with self.assertRaisesRegex(InputError,'observation changed'):
                semantic_catalog.load(self.run,registered['observer'],store)
            listing=semantic_catalog.catalog(store)
            self.assertEqual(listing['maps'],[])
            self.assertEqual(listing['unavailable'][0]['observer'],registered['observer'])
            newer=semantic_catalog.register(store,self.work,self.run['id'],'Frozen')
            self.assertNotEqual(newer['observer'],registered['observer'])
            self.assertEqual(len(semantic_catalog.catalog(store)['maps']),1)

    def test_cli_prepare_run_status_and_audit_are_source_independent(self):
        store=Store(self.root/'tracker.sqlite');store.add([self.run])
        base=[sys.executable,'-X','utf8','-m','rilldex','--db',str(store.path),'semantic']
        fresh=self.root/'cli-observer'
        def invoke(*arguments):
            result=subprocess.run([*base,*map(str,arguments)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            return result.stdout
        prepared=json.loads(invoke('prepare',fresh,'--run-id',self.run['id'],'--agent-only',
                                   '--activity-routing',WORK_ORGANIZATION_ACTIVITY_ROUTING))
        self.assertEqual(prepared['eligible_windows'],1)
        self.assertEqual(prepared['activity_routing'],WORK_ORGANIZATION_ACTIVITY_ROUTING)
        output=invoke('run',fresh)
        self.assertIn('needs_partition_candidates',output)
        self.assertEqual(json.loads(invoke('status',fresh))['status'],'needs_work')
        self.assertEqual(json.loads(invoke('audit',fresh))['saved_decisions'],0)

    def test_new_store_without_bundled_development_runs_has_an_empty_catalog(self):
        store=Store(self.root/'empty.sqlite')
        self.assertEqual(semantic_catalog.catalog(store)['maps'],[])


if __name__=='__main__':unittest.main()
