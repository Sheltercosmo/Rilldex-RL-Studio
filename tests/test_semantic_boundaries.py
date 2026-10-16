import copy
import unittest
import tempfile
from pathlib import Path

from tracker.adapters import normalize
from tracker.schema import InputError, digest
from tracker.semantic_extraction import windows, partition
from tracker.semantic_boundaries import proposals, selection_request, materialize
from tracker.semantic_boundaries import GlobalSourceCandidates
from tracker.semantic_extraction import Pipeline, audit_result, read, write
from tracker.jev import DEFAULT_MODEL


def source(text):
    run = normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Inspect and fix the project.', 'agent':{'thought':text,'action':None},'environment':None},
        {'step':1,'user_message':'FUTURE SECRET RESULT', 'agent':{'thought':'Next.', 'action':None},'environment':None}]})[0]
    return run, windows(run)[0]


class GlobalBoundaryTests(unittest.TestCase):
    def test_all_adjacent_groupings_preserve_source_without_choosing_units(self):
        run,w=source('First.\n\nSecond.\n\nThird.')
        value=proposals(run,w)
        self.assertEqual(len(value['partitions']),4)
        self.assertEqual([p['groups'] for p in value['partitions']],[[[0,1,2]],[[0],[1,2]],[[0,1],[2]],[[0],[1],[2]]])
        for p in value['partitions']:self.assertEqual(partition(run,w,p['units']),p['units'])
        self.assertNotIn('activity',str(value))

    def test_code_with_blank_lines_is_not_fragmented(self):
        run,w=source('Draft:\n\n```python\na = 1\n\nb = 2\n```\n\nInsert this code.')
        value=proposals(run,w)
        self.assertEqual(len(value['blocks']),3)
        self.assertIn('a = 1\n\nb = 2',value['blocks'][1]['text'])
        self.assertEqual(value['total_possible_partitions'],4)

    def test_unclosed_tilde_fence_remains_payload(self):
        run,w=source('Draft:\n\n~~~~\na\n\nb\n~~~\n\nc')
        value=proposals(run,w)
        self.assertEqual(len(value['blocks']),2)
        self.assertTrue(value['blocks'][1]['text'].endswith('c'))

    def test_budget_is_unavailable_not_a_truncated_prediction(self):
        run,w=source('\n\n'.join('Block '+str(i) for i in range(9)))
        value=proposals(run,w)
        self.assertEqual(value['coverage'],'partition_budget_exceeded')
        self.assertEqual(value['total_possible_partitions'],256)
        self.assertEqual(value['partitions'],[])
        with self.assertRaises(InputError):selection_request(run,value,None)

    def test_prose_has_no_implied_semantic_partition_and_no_future_context(self):
        run,w=source('One statement, then a separate request?')
        value=proposals(run,w);req=selection_request(run,value,None)
        self.assertIn('no_suitable_candidate',req['questions']['choice']['criteria'])
        self.assertNotIn('FUTURE',str(req))
        self.assertEqual(materialize(value,'unresolved')['units'],[])
        with self.assertRaises(InputError):materialize(value,'p20')

    def test_original_unicode_offsets_and_window_subrange(self):
        run,w=source('Prelude.\n\nÜnicode 👩🏽‍💻.\r\n\r\nFin.')
        event=next(e for e in run['events'] if e['id']==w['event_id'])
        w=copy.deepcopy(w);w['start']=event['text'].index('Ünicode');w['text']=event['text'][w['start']:w['end']]
        value=proposals(run,w)
        self.assertEqual(len(value['blocks']),2)
        for block in value['blocks']:self.assertEqual(event['text'][block['start']:block['end']],block['text'])

    def test_pipeline_runs_boundary_before_activity_and_waits_for_content(self):
        run,w=source('The decorator is missing.\n\nWe need to add it to reproduce the problem.')
        run['events']=run['events'][:2]
        calls=[]
        def transport(req):
            stage=req['state']['stage'];calls.append(stage)
            value='p0' if stage=='global-source-partitions' else 'orient'
            keys=list(req['questions']['choice']['criteria'])
            return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','choice':keys[-1],
                'confidence':0,'probabilities':{k:.7 if k==value else .3/(len(keys)-1) for k in keys}}}}
        with tempfile.TemporaryDirectory() as d:
            engine=Pipeline(d,GlobalSourceCandidates(Path(d)/'c'),transport);result=engine.run(run)
            self.assertEqual(calls,['global-source-partitions','activity'])
            self.assertEqual(result['units'][0]['activity'],'orient')
            self.assertEqual(result['units'][0]['status'],'needs_candidates')
            self.assertEqual(result['status'],'needs_work')
            self.assertTrue(audit_result(run,result,d)['argmax_replayed'])
            replay=engine.run(run);self.assertEqual(replay,result);self.assertEqual(len(calls),2)
            corrupt=copy.deepcopy(result);corrupt['windows'][0]['unit_count']=2
            with self.assertRaises(InputError):audit_result(run,corrupt,d)

    def test_pipeline_budget_cannot_publish_activity_or_complete(self):
        run,w=source('\n\n'.join('Part '+str(i) for i in range(9)));run['events']=run['events'][:2]
        def forbidden(req):raise AssertionError('No request should run without complete boundaries')
        with tempfile.TemporaryDirectory() as d:
            result=Pipeline(d,GlobalSourceCandidates(Path(d)/'c'),forbidden).run(run)
            self.assertEqual(result['units'],[])
            self.assertEqual(result['windows'][0]['reason'],'partition_budget_exceeded')
            self.assertTrue(audit_result(run,result,d)['argmax_replayed'])

    def test_rejected_global_partition_does_not_leak_into_activity_or_content(self):
        run,w=source('A single paragraph may contain independent contributions.');run['events']=run['events'][:2]
        def reject(req):
            self.assertEqual(req['state']['stage'],'global-source-partitions')
            keys=list(req['questions']['choice']['criteria'])
            return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice',
                'probabilities':{k:.8 if k=='no_suitable_candidate' else .2/(len(keys)-1) for k in keys}}}}
        with tempfile.TemporaryDirectory() as d:
            result=Pipeline(d,GlobalSourceCandidates(Path(d)/'c'),reject).run(run)
            self.assertEqual(result['units'],[])
            self.assertEqual(result['windows'][0]['reason'],'no_suitable_candidate')
            self.assertTrue(audit_result(run,result,d)['argmax_replayed'])
            corrupt=copy.deepcopy(result);corrupt['status']='complete_local_extraction'
            with self.assertRaises(InputError):audit_result(run,corrupt,d)

    def test_large_region_fallback_is_source_bound_selected_and_replayed(self):
        run,w=source('\n\n'.join('Detail '+str(i) for i in range(9)));run['events']=run['events'][:2]
        def transport(req):
            keys=list(req['questions']['choice']['criteria']);winner='p0' if req['state']['stage']=='partition' else 'orient'
            return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice',
                'probabilities':{k:.8 if k==winner else .2/(len(keys)-1) for k in keys}}}}
        with tempfile.TemporaryDirectory() as d:
            provider=GlobalSourceCandidates(Path(d)/'candidates');engine=Pipeline(d,provider,transport)
            pending=engine.run(run);key=pending['windows'][0]['repair_request']
            req=read(Path(d)/'candidates/requests'/f'{key}.json')
            response={'request_hash':key,'producer':'test source proposer',
                      'partitions':[{'spans':[{'start':w['start'],'end':w['end']}]}]}
            path=Path(d)/'candidates/responses'/f'{key}.json';write(path,response)
            selected=engine.run(run)
            self.assertEqual(selected['windows'][0]['fallback_candidate_request'],key)
            audit=audit_result(run,selected,d)
            self.assertEqual(audit['pending_boundary_windows'],[])
            self.assertEqual(audit['annotation_status'],'incomplete')
            self.assertEqual(len(audit['pending_content_units']),1)
            response['partitions'][0]['spans'][0]['start']+=1;write(path,response)
            with self.assertRaises(InputError):audit_result(run,selected,d)

    def test_invalid_content_is_retained_and_later_units_still_run(self):
        from tracker.semantic_extraction import generation_request
        run,w=source('The decorator is missing. Add it.')
        def transport(req):
            keys=list(req['questions']['choice']['criteria']);winner='p0' if req['state']['stage']=='global-source-partitions' else 'orient'
            return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice',
                'probabilities':{k:.8 if k==winner else .2/(len(keys)-1) for k in keys}}}}
        with tempfile.TemporaryDirectory() as d:
            ref=partition(run,w,[w])[0];req=generation_request(run,ref,'orient');key=digest(req)
            write(Path(d)/'candidates/responses'/f'{key}.json',{'request_hash':key,'producer':'bad test proposer','candidates':[]})
            result=Pipeline(d,GlobalSourceCandidates(Path(d)/'candidates'),transport).run(run)
            self.assertEqual([u['status'] for u in result['units']],['needs_candidate_repair','needs_candidates'])
            audit=audit_result(run,result,d)
            self.assertEqual(len(audit['pending_content_units']),2)
            rejection=result['units'][0]['candidate_rejection']
            self.assertTrue((Path(d)/'candidates/rejections'/f'{rejection}.json').exists())
            corrupt=copy.deepcopy(result);corrupt['units'][0]['candidate_request']='wrong'
            with self.assertRaises(InputError):audit_result(run,corrupt,d)

    def test_selective_activity_reading_waits_without_blocking_other_units(self):
        run,w=source('Submit the work.');ref=partition(run,w,[w])[0]
        calls=[]
        def transport(req):
            calls.append(req['state']['stage']);keys=list(req['questions']['choice']['criteria'])
            winner='p0' if req['state']['stage']=='global-source-partitions' else 'orient'
            return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice',
                'probabilities':{k:.8 if k==winner else .2/(len(keys)-1) for k in keys}}}}
        with tempfile.TemporaryDirectory() as d:
            provider=GlobalSourceCandidates(Path(d)/'candidates',activity_reading_sources=[ref])
            result=Pipeline(d,provider,transport).run(run)
            self.assertEqual([u['status'] for u in result['units']],['needs_activity_readings','needs_candidates'])
            self.assertEqual(calls.count('activity'),1)
            self.assertTrue(audit_result(run,result,d)['argmax_replayed'])
