"""Repair protocol integrity; these checks do not score semantic accuracy."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,FileCandidates,read,write,load_extraction
from tracker.semantic_map import evidence
from tracker.stated_checks import (ROUTED_VERSION,POLICY,derive_candidates,build,audit,execute,
    candidate_repair_request,content_request,candidates_path,path_for)
from tracker.check_candidate_repairs import (RESPONSE_VERSION,revise_candidates,prepare_revision,audit_revisions)
from tests.test_stated_checks import fixture


def choose(req,winner):
    keys=req['questions']['choice']['criteria']
    return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':next(k for k in keys if k!=winner),
        'probabilities':{k:.8 if k==winner else .2/(len(keys)-1) for k in keys}}}}


def setup_case(directory):
    run,local,owner,action,check,proposals=fixture()
    # A second row lets us verify that a repair only invalidates one packet.
    other=next(u for u in local['units'] if u['kind']=='semantic' and u['id']!=owner['id'])
    proposals['units'].append({'unit_id':other['id'],'candidates':[]})
    engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),
        lambda req:choose(req,'checking_work' if req['state']['stage']=='checking_applicability' else 'no_suitable_candidate'))
    previous=build(run,local,proposals,engine.decide,ROUTED_VERSION)
    req=candidate_repair_request(run,local,previous['observations'][0])
    response={'schema':RESPONSE_VERSION,'request_hash':digest(req),'producer':'test author',
        'citation_format':'source-quotes/1','candidates':[{'text':'Inspect the report contents.',
            'evidence':[{'event_id':owner['source']['event_id'],'quote':'Check its existence and contents.'}],
            'facets':[{'id':'contents','text':'Inspect the report contents.',
                'evidence':[{'event_id':owner['source']['event_id'],'quote':'Check its existence and contents.'}]}]}]}
    return run,local,proposals,previous,req,response


class CheckCandidateRepairsTests(unittest.TestCase):
    def test_quote_repair_preserves_source_and_unrelated_packets_and_requires_fresh_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,proposals,previous,req,response=setup_case(directory)
            untouched=deepcopy([run,local,proposals,previous,req,response])
            revised,revision=revise_candidates(run,local,proposals,previous,req,response)
            self.assertEqual([run,local,proposals,previous,req,response],untouched)
            self.assertEqual(revised['producer'],proposals['producer'])
            self.assertEqual(revised['units'][1],proposals['units'][1])
            for i,row in enumerate(proposals['units']):
                owner=next(u for u in local['units'] if u['id']==row['unit_id'])
                before=content_request(run,local,owner,row,proposals,ROUTED_VERSION)
                after=content_request(run,local,owner,revised['units'][i],revised,ROUTED_VERSION)
                self.assertEqual(before==after,i==1)
            self.assertEqual(revised['units'][0]['candidates'][0]['evidence'][0]['text'],'Check its existence and contents.')
            stages=[]
            def reject(req):stages.append(req['state']['stage']);return choose(req,'unresolved')
            engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),reject)
            result=build(run,local,revised,engine.decide,ROUTED_VERSION)
            self.assertEqual(stages,['stated_check_contents'])
            self.assertEqual(result['observations'][0]['selection'],'unresolved')
            self.assertNotIn('check',result['observations'][0])
            self.assertTrue(audit(run,local,revised,result,directory)['argmax_replayed'])

    def test_rejects_stale_request_modified_prefix_wrong_owner_and_forced_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,p,previous,req,response=setup_case(directory)
            for kind in ['request_hash','prefix','owner','forced','producer']:
                with self.subTest(kind=kind):
                    q=deepcopy(req);r=deepcopy(response)
                    if kind=='request_hash':r['request_hash']='stale'
                    if kind=='prefix':q['prefix'][-1]['text']+=' invented'
                    if kind=='owner':q['unit_id']=p['units'][1]['unit_id']
                    if kind=='forced':r['selected']='c0'
                    if kind=='producer':r['producer']=' '
                    with self.assertRaises(InputError):revise_candidates(run,local,p,previous,q,r)

    def test_rejects_future_omitted_or_non_owner_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,p,previous,req,response=setup_case(directory)
            for kind in ['future','outside_owner','invented_quote','malformed']:
                with self.subTest(kind=kind):
                    r=deepcopy(response)
                    if kind=='future':ref={'event_id':run['events'][-1]['id'],'quote':run['events'][-1]['text']}
                    elif kind=='outside_owner':ref={'event_id':run['events'][0]['id'],'quote':run['events'][0]['text']}
                    elif kind=='invented_quote':ref={'event_id':req['source']['event_id'],'quote':'Not in source'}
                    else:ref='not a citation'
                    r['candidates'][0]['evidence']=[ref]
                    with self.assertRaises(InputError):revise_candidates(run,local,p,previous,req,r)
            # A real earlier source span can still be absent from the supplied
            # generation view. Offset citations must not bypass that boundary.
            run['events'][0]['kind']='message'
            run['events'][0]['text']='x'*(POLICY['max_event_chars']*2)
            local['source_hash']=digest(run);p['source_hash']=digest(run);p['extraction_hash']=digest(local)
            engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),
                lambda req:choose(req,'checking_work' if req['state']['stage']=='checking_applicability' else 'no_suitable_candidate'))
            previous=build(run,local,p,engine.decide,ROUTED_VERSION);req=candidate_repair_request(run,local,previous['observations'][0])
            r=deepcopy(response);r.update(request_hash=digest(req),citation_format='source-offsets/1')
            mid=POLICY['max_event_chars'];omitted=evidence(run,run['events'][0]['id'],start=mid,end=mid+1)
            for value in [r['candidates'][0],*r['candidates'][0]['facets']]:value['evidence']=[req['source'],omitted]
            with self.assertRaisesRegex(InputError,'outside the supplied'):revise_candidates(run,local,p,previous,req,r)

    def test_empty_proposals_remain_a_gap_and_malformed_bundles_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,p,previous,req,response=setup_case(directory)
            empty=deepcopy(response);empty['candidates']=[]
            revised,_=revise_candidates(run,local,p,previous,req,empty)
            self.assertEqual(revised['units'][0]['candidates'],[])
            for value in [None,[None],[{}],response['candidates']*4]:
                r=deepcopy(response);r['candidates']=value
                with self.assertRaises(InputError):revise_candidates(run,local,p,previous,req,r)

    def test_full_directory_revision_replays_without_mutating_baseline_and_detects_tampering(self):
        from tests.test_semantic_extraction import fixture as source_fixture,response as base_response,proposals as base_proposals
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source';out=Path(root)/'repaired';run=source_fixture()
            engine=Pipeline(source,FileCandidates(source/'candidates'),base_response)
            pending=engine.run(run)
            for u in pending['units']:
                req=read(source/'candidates/requests'/f"{u['candidate_request']}.json")
                write(source/'candidates/responses'/f'{digest(req)}.json',base_proposals(req))
            local=engine.run(run);write(source/'runs'/f"{run['id']}.json",run)
            p=derive_candidates(run,local);write(candidates_path(source,local),p)
            engine.transport=lambda req:choose(req,'checking_work' if req['state']['stage']=='checking_applicability' else 'no_suitable_candidate')
            previous,_=execute(run,local,p,engine,ROUTED_VERSION)
            req=candidate_repair_request(run,local,previous['observations'][0])
            ref=req['source'];meaning='Test candidate; protocol fixture, not a semantic reference.'
            response={'schema':RESPONSE_VERSION,'request_hash':digest(req),'producer':'test author','citation_format':'source-offsets/1',
                      'candidates':[{'text':meaning,'evidence':[ref],'facets':[{'id':'test','text':meaning,'evidence':[ref]}]}]}
            before={str(f.relative_to(source)):f.read_bytes() for f in source.rglob('*') if f.is_file()}
            receipt=prepare_revision(source,run['id'],req,response,out)
            self.assertFalse(path_for(out,local).exists())
            self.assertEqual(before,{str(f.relative_to(source)):f.read_bytes() for f in source.rglob('*') if f.is_file()})
            self.assertEqual(read(out/'results'/f"{run['id']}.json"),local)
            with self.assertRaisesRegex(InputError,'already exists'):prepare_revision(source,run['id'],req,response,out)
            with self.assertRaisesRegex(InputError,'separate'):prepare_revision(source,run['id'],req,response,source/'nested')
            revised=read(candidates_path(out,local));self.assertEqual(len(audit_revisions(run,local,revised,out)),1)
            replay=Pipeline(out,FileCandidates(out/'candidates'),lambda req:choose(req,'c0' if req['state']['stage']=='stated_check_contents' else 'observation_only'))
            result,_=execute(run,local,revised,replay,ROUTED_VERSION)
            self.assertEqual(replay.calls,2)
            view=load_extraction(run,out)['document']
            self.assertEqual(len(view['check_candidate_revisions']),1)
            self.assertEqual(view['check_candidate_revisions'][0]['previous_selection'],'no_suitable_candidate')
            self.assertEqual(result['observations'][0]['applicability'],previous['observations'][0]['applicability'])
            execute(run,local,revised,replay,ROUTED_VERSION);self.assertEqual(replay.calls,2)
            history=out/'check_candidate_revisions'/receipt['revision_id']/'response.json'
            tampered=read(history);tampered['producer']='changed';write(history,tampered)
            with self.assertRaisesRegex(InputError,'history differs'):audit_revisions(run,local,revised,out)


if __name__=='__main__':unittest.main()
