import copy
import tempfile
from pathlib import Path
import unittest

from tracker.adapters import normalize
from tracker.jev import DEFAULT_MODEL
from tracker.schema import InputError,digest
from tracker.semantic_extraction import (FileCandidates,Pipeline,generation_request,partition,
    prefix,read,validate_proposals,windows,write,audit_result,load_extraction,episode_scope,source_expression_links)
from tracker.semantic_map import evidence


def fixture():
    return normalize({'schema_version':'ATIF-v1.7','session_id':'semantic-stages','agent':{'name':'test','version':'1'},'steps':[
      {'step_id':1,'source':'user','message':'Restore service.'},
      {'step_id':2,'source':'agent','message':'The reproduction code lacks the decorator. We need to add it to the class to replicate the issue.'},
      {'step_id':3,'source':'user','message':'FUTURE result: success.'}]})[0]


def response(req):
    q=req['questions']['choice'];stage=req['state']['stage'];value='p0' if stage=='partition' else 'orient' if stage=='activity' else 'c0'
    options=list(q['criteria']);other=[x for x in options if x!=value]
    return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','choice':other[0], 'confidence':0,
        'probabilities':{k:0.6 if k==value else 0.4/len(other) for k in options}}},'usage':{'input_tokens':10,'output_tokens':2}}


def proposals(req):
    fs={k:{'status':'not_expressed'} for k in req['field_contract']}
    fs['summary']={'status':'expressed','text':'Recognizes the missing decorator and calls for adding it.','evidence':[req['source']]}
    fs['work_target']={'status':'expressed','text':'Make the reproduction exercise the decorator.','evidence':[req['source']]}
    return {'request_hash':digest(req),'producer':'test candidate provider','candidates':[{'fields':fs}]}


class ExtractionTests(unittest.TestCase):
    def test_optional_work_phase_routing_has_distinct_cache_and_preserves_legacy_replay(self):
        from tracker.semantic_extraction import WORK_PHASE_ACTIVITY_ROUTING, WORK_ORGANIZATION_ACTIVITY_ROUTING,ACTIVITY_ROUTING
        run=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            old=Pipeline(root,FileCandidates(root/'c'),response).run(run)
            new=Pipeline(root,FileCandidates(root/'c',activity_routing=WORK_PHASE_ACTIVITY_ROUTING),response).run(run)
            old_key=old['units'][0]['activity_request'];new_key=new['units'][0]['activity_request']
            self.assertNotEqual(old_key,new_key)
            self.assertEqual(read(root/'decisions'/f'{old_key}.json')['request']['state']['activity_routing'],ACTIVITY_ROUTING)
            self.assertEqual(read(root/'decisions'/f'{new_key}.json')['request']['state']['activity_routing'],WORK_PHASE_ACTIVITY_ROUTING)
            self.assertTrue(audit_result(run,old,root)['argmax_replayed'])
            self.assertTrue(audit_result(run,new,root)['argmax_replayed'])
            repeated=Pipeline(root,FileCandidates(root/'c'),lambda _:self.fail('Saved legacy request must replay')).run(run)
            self.assertEqual(repeated,old)
            organization=Pipeline(root,FileCandidates(root/'c',activity_routing=WORK_ORGANIZATION_ACTIVITY_ROUTING),response).run(run)
            self.assertNotIn(organization['units'][0]['activity_request'],{old_key,new_key})
            self.assertTrue(audit_result(run,organization,root)['argmax_replayed'])
            wrong=copy.deepcopy(organization);wrong['activity_routing']=ACTIVITY_ROUTING
            with self.assertRaisesRegex(InputError,'declared routing'):audit_result(run,wrong,root)
            del wrong['activity_routing']
            with self.assertRaisesRegex(InputError,'declared routing'):audit_result(run,wrong,root)
            with self.assertRaisesRegex(InputError,'Unknown semantic activity routing'):
                FileCandidates(root/'c',activity_routing='invalid')

    def test_semantic_boundary_mode_waits_before_classification_and_resumes(self):
        from tracker.semantic_extraction import SEMANTIC_PARTITIONS
        run=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);provider=FileCandidates(root/'c',partition_policy=SEMANTIC_PARTITIONS)
            engine=Pipeline(root,provider,response);pending=engine.run(run)
            self.assertEqual(engine.calls,0)
            self.assertEqual(pending['units'],[])
            self.assertEqual(pending['windows'][0]['status'],'needs_partition_candidates')
            self.assertEqual(audit_result(run,pending,root)['selected_units'],0)
            key=pending['windows'][0]['repair_request'];req=read(root/'c/requests'/f'{key}.json')
            self.assertNotIn('FUTURE',str(req))
            ref=req['source']
            write(root/'c/responses'/f'{key}.json',{'request_hash':key,'producer':'test semantic proposer',
                'partitions':[{'spans':[{'start':ref['start'],'end':ref['end']}]}]})
            classified=engine.run(run)
            self.assertEqual(len(classified['units']),1)
            self.assertEqual(engine.calls,2)
            selected=read(root/'decisions'/f"{classified['windows'][0]['partition_request']}.json")
            self.assertEqual(len(selected['request']['state']['partitions']),1)
            self.assertEqual(selected['request']['state']['partition_policy'],SEMANTIC_PARTITIONS)
            self.assertTrue(audit_result(run,classified,root)['argmax_replayed'])
            altered=copy.deepcopy(pending);altered['windows'][0]['status']='partitioned'
            with self.assertRaisesRegex(InputError,'Pending semantic boundary'):audit_result(run,altered,root)

    def test_semantic_boundary_candidates_exclude_automatic_paragraph_fragments(self):
        from tracker.semantic_extraction import partition_options
        run=fixture();agent=next(e for e in run['events'] if e['actor']=='agent')
        agent['text']='Let me clarify the setup:\n\nThe decorator is missing.\n\nWe need to add it.'
        w=windows(run)[0]
        extra=[{'spans':[{'start':w['start'],'end':w['end']}],'origin':'authored semantic candidate'}]
        self.assertGreater(len(partition_options(run,w,extra)),1)
        self.assertEqual(len(partition_options(run,w,extra,semantic_only=True)),1)
        with self.assertRaisesRegex(InputError,'required before classification'):
            partition_options(run,w,semantic_only=True)

    def test_atif_message_and_reasoning_share_the_recorded_dispatch_parent(self):
        run=normalize({'schema_version':'ATIF-v1.7','session_id':'source-pairing','agent':{'name':'test','version':'1'},'steps':[
            {'step_id':1,'source':'user','message':'Find available fares.'},
            {'step_id':2,'source':'agent','message':'I will search available fares.',
             'reasoning_content':'Refundability is required for this trip.',
             'tool_calls':[{'tool_call_id':'x','function_name':'find_fares','arguments':{'refundable':True}}]}]})[0]
        units=[{'id':e['id'],'source':evidence(run,e['id']),'actor':e['actor'],
            'trajectory_id':e['trajectory_id'],'kind':'action' if e['kind']=='action' else 'semantic'}
            for e in run['events'] if e['actor']=='agent']
        links=source_expression_links(run,units)
        self.assertEqual({r['from'] for r in links},{units[0]['id'],units[1]['id']})
        self.assertEqual({r['to'] for r in links},{units[2]['id']})
        self.assertEqual({r['source_parent_event_id'] for r in links},{units[0]['id']})

    def test_expression_pairing_requires_recorded_parent_and_same_actor(self):
        run=normalize({'trajectory_format':'devai/1','trajectory':[
            {'step':0,'user_message':'Inspect file.','agent':{'thought':'Read the file.','action':'read file'},'environment':'File text'},
            {'step':1,'user_message':None,'agent':{'thought':'Now report the result.','action':None},'environment':None}]})[0]
        units=[{'id':e['id'],'source':evidence(run,e['id']),'actor':e['actor'],
            'trajectory_id':e['trajectory_id'],'kind':'action' if e['kind']=='action' else 'semantic'}
            for e in run['events'] if e['kind'] in {'reasoning','action'}]
        links=source_expression_links(run,units)
        self.assertEqual(len(links),1)
        self.assertEqual((links[0]['from'],links[0]['to']),(units[0]['id'],units[1]['id']))
        self.assertEqual(links[0]['type'],'recorded_with')
        different=copy.deepcopy(units);different[0]['actor']='other'
        self.assertEqual(source_expression_links(run,different),[])
        unpaired=copy.deepcopy(run)
        next(e for e in unpaired['events'] if e['kind']=='action').pop('parent_id')
        self.assertEqual(source_expression_links(unpaired,units),[])

    def test_recorded_dispatch_is_one_unit_without_semantic_partition_call(self):
        run=normalize({'trajectory_format':'devai/1','trajectory':[
            {'step':0,'user_message':'Read the file.','agent':{
                'thought':None,'action':"Running Python code interactively: open_file('src/model.py')"},
             'environment':'Empty file'}]})[0]
        calls=[]
        def transport(req):calls.append(req['state']['stage']);return response(req)
        with tempfile.TemporaryDirectory() as d:
            engine=Pipeline(d,FileCandidates(Path(d)/'c'),transport);result=engine.run(run)
            self.assertEqual(calls,['activity'])
            self.assertEqual(len(result['units']),1)
            self.assertEqual(result['windows'][0]['partition_choice'],'source_dispatch')
            self.assertTrue(audit_result(run,result,d)['argmax_replayed'])
            for area in ['windows','units']:
                altered=copy.deepcopy(result)
                if area=='units':altered[area][0].pop('boundary_origin')
                else:altered[area][0]['unit_count']=2
                with self.assertRaisesRegex(InputError,'dispatch boundary differs'):
                    audit_result(run,altered,d)

    def test_episode_scope_requires_every_eligible_window_between_explicit_boundaries(self):
        run=fixture();ref=windows(run)[0]
        scope=episode_scope(run,ref['event_id'],ref['event_id'])
        with tempfile.TemporaryDirectory() as d:
            provider=FileCandidates(Path(d)/'c');engine=Pipeline(d,provider,response)
            first=engine.run(run,scope=scope)
            req=read(Path(d)/'c/requests'/f"{first['units'][0]['candidate_request']}.json")
            write(Path(d)/'c/responses'/f'{digest(req)}.json',proposals(req))
            result=engine.run(run,scope=scope)
            self.assertEqual(audit_result(run,result,d)['coverage'],'complete selected episode')
            changed=copy.deepcopy(result);changed['windows']=[];changed['units']=[]
            with self.assertRaisesRegex(InputError,'Episode source coverage'):audit_result(run,changed,d)
            with self.assertRaisesRegex(InputError,'selection differs'):engine.run(run,window_ids=[],scope=scope)
            with self.assertRaisesRegex(InputError,'ordered'):episode_scope(run,run['events'][-1]['id'],run['events'][0]['id'])

    def test_source_sentence_proposals_are_actually_repaired_and_resume_binds_requests(self):
        run=fixture();w=windows(run);self.assertEqual(len(w),1)
        with tempfile.TemporaryDirectory() as d:
            provider=FileCandidates(Path(d)/'candidates');calls=[]
            def transport(req):calls.append(req);return response(req)
            engine=Pipeline(d,provider,transport);r=engine.run(run)
            self.assertEqual(len(r['units']),1)
            self.assertEqual(r['units'][0]['source']['text'],w[0]['text'])
            self.assertEqual(r['units'][0]['status'],'needs_candidates')
            self.assertEqual([x['state']['stage'] for x in calls],['partition','activity'])
            request_file=next((Path(d)/'candidates/requests').glob('*.json'));req=read(request_file)
            self.assertNotIn('FUTURE',str(req))
            write(Path(d)/'candidates/responses'/request_file.name,proposals(req))
            r=engine.run(run);self.assertEqual(r['status'],'complete_local_extraction')
            self.assertEqual([x['state']['stage'] for x in calls],['partition','activity','content'])
            self.assertIn('exercise the decorator',r['units'][0]['content']['work_target']['text'])
            self.assertTrue(audit_result(run,r,d)['argmax_replayed'])
            self.assertEqual(load_extraction(run,d)['document']['provenance']['origin'],'jev_selected_model_candidates')
            altered=copy.deepcopy(r);altered['units'][0]['content']['work_target']['text']='Invented completion'
            with self.assertRaisesRegex(InputError,'Selected content differs'):audit_result(run,altered,d)
            engine.run(run);self.assertEqual(len(calls),3)
            p=next((Path(d)/'decisions').glob('*.json'));saved=read(p);saved['answers']['choice']['value']='unresolved';write(p,saved)
            with self.assertRaisesRegex(InputError,'raw argmax differs'):engine.run(run)

    def test_partitions_cannot_drop_or_duplicate_content(self):
        run=fixture();w=windows(run)[0]
        for spans in [[{'start':w['start']+4,'end':w['end']}],
                      [{'start':w['start'],'end':30},{'start':20,'end':w['end']}],
                      [{'start':w['start'],'end':w['end']-8}]]:
            with self.assertRaises(InputError):partition(run,w,spans)

    def test_repair_state_does_not_trigger_classification(self):
        run=fixture()
        def reject(req):
            q=req['questions']['choice'];return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','probabilities':{k:1 if k=='no_suitable_candidate' else 0 for k in q['criteria']}}}}
        with tempfile.TemporaryDirectory() as d:
            engine=Pipeline(d,FileCandidates(Path(d)/'c'),reject);r=engine.run(run)
            self.assertEqual(engine.calls,1);self.assertEqual(r['units'],[]);self.assertEqual(r['windows'][0]['status'],'needs_partition_candidates')
            repair=read(Path(d)/'c/requests'/f"{r['windows'][0]['repair_request']}.json")
            self.assertEqual(repair['schema'],'semantic-partition-proposal-request/1')
            r['windows'][0]['status']='partitioned';r['status']='complete_local_extraction'
            with self.assertRaisesRegex(InputError,'Unresolved partition'):audit_result(run,r,d)

    def test_candidate_cannot_smuggle_future_or_another_actors_private_result(self):
        run=fixture();ref=windows(run)[0];req=generation_request(run,ref,'orient');p=proposals(req)
        p['candidates'][0]['fields']['summary']['evidence']=[evidence(run,run['events'][-1]['id'])]
        with self.assertRaisesRegex(InputError,'Future evidence'):validate_proposals(run,req,p)
        private=copy.deepcopy(run['events'][0]);private.update(id='private',kind='external_feedback',agent_visibility='not_established',text='PRIVATE SIM failure')
        run['events'].insert(1,private);ps,excluded=prefix(run,ref)
        self.assertIn('private',excluded);self.assertNotIn('PRIVATE SIM failure',str(ps))
        req=generation_request(run,ref,'orient');p=proposals(req);p['candidates'][0]['fields']['summary']['evidence']=[evidence(run,'private')]
        with self.assertRaisesRegex(InputError,'not established as agent-visible'):validate_proposals(run,req,p)

    def test_candidate_must_match_current_unit_category_and_field_contract(self):
        run=fixture();req=generation_request(run,windows(run)[0],'orient');p=proposals(req)
        p['request_hash']='wrong'
        with self.assertRaisesRegex(InputError,'current generation request'):validate_proposals(run,req,p)
        p=proposals(req);p['candidates'][0]['fields'].pop('situation')
        with self.assertRaisesRegex(InputError,'fields differ'):validate_proposals(run,req,p)

    def test_empty_expressed_field_names_the_repair_without_inventing_content(self):
        run=fixture();req=generation_request(run,windows(run)[0],'orient');p=proposals(req)
        p['candidates'][0]['fields']['focus']={'status':'expressed','text':'','evidence':[req['source']]}
        with self.assertRaisesRegex(InputError,'Content field "focus" needs readable meaning'):
            validate_proposals(run,req,p)
        p['candidates'][0]['fields']['focus']={'status':'not_expressed'}
        self.assertEqual(validate_proposals(run,req,p)[0]['fields']['focus'],{'status':'not_expressed'})

    def test_rejected_partition_is_repaired_with_real_new_spans(self):
        run=fixture();e=next(e for e in run['events'] if e['actor']=='agent')
        e['text']+=' The answer is 42.';cut=e['text'].index('The answer is 42.')
        def transport(req):
            if req['state']['stage']=='partition':
                choices=req['questions']['choice']['criteria'];value='p2' if 'p2' in choices else 'no_suitable_candidate'
                return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','probabilities':{k:1 if k==value else 0 for k in choices}}}}
            return response(req)
        with tempfile.TemporaryDirectory() as d:
            engine=Pipeline(d,FileCandidates(Path(d)/'c'),transport);first=engine.run(run)
            self.assertEqual(first['units'],[])
            key=first['windows'][0]['repair_request'];req=read(Path(d)/'c/requests'/f'{key}.json')
            write(Path(d)/'c/responses'/f'{key}.json',{'request_hash':digest(req),'producer':'test boundary proposal',
                'partitions':[{'spans':[{'start':0,'end':cut},{'start':cut,'end':len(e['text'])}]}]})
            second=engine.run(run)
            self.assertEqual(len(second['units']),2)
            self.assertEqual(second['units'][0]['source']['end'],cut)
            self.assertEqual(second['units'][1]['source']['text'],'The answer is 42.')
            self.assertTrue(audit_result(run,second,d)['argmax_replayed'])


if __name__=='__main__':unittest.main()
