"""Authored contract checks; model semantics are evaluated separately."""
from copy import deepcopy
import unittest
from tracker import work_mentions as mentions, work_mention_checks as checks
from tracker.schema import InputError, digest
from test_work_scope_frames import fixture, rekey
from test_work_mentions import proposal, answer


def control(count=1,selected=None):
    run,g=fixture(count);p=mentions.packet(g,['unit-'+str(i) for i in range(count)])
    r=proposal(p);b=mentions.bind(p,r,'authored control')
    decision=answer(mentions.selection_request(p,b),selected)
    req=checks.request(p,b,decision)
    choices={q:('complete' if q.endswith('_coverage') else 'supported' if '_l' in q else 'faithful_single') for q in req['questions']}
    return g,p,r,b,decision,req,choices


class ComponentChecks(unittest.TestCase):
    def test_argmax_keeps_source_unit_and_component_receipts(self):
        g,p,r,b,selection,req,choices=control()
        response=answer(req,choices) # contradictory choice field and zero confidence
        out=mentions.fork(g,p,r,'authored control',selection,component_response=response)
        projected=mentions.project(out);row=projected['rows'][0]
        self.assertEqual(row['component_checks']['status'],'complete')
        self.assertEqual(len(row['reading']['mentions']),2)
        self.assertEqual(out['semantic_context']['work_mentions']['response'],selection)
        self.assertEqual([n for n in out['nodes'] if n['kind']=='unit'],[n for n in g['nodes'] if n['kind']=='unit'])
        self.assertEqual(out['coverage']['work_mentions']['component_complete_units'],1)
        self.assertNotIn('review',req['state']);self.assertNotIn('confidence',str(req))

    def test_wrong_endpoint_removes_only_link_and_never_reverses_it(self):
        g,p,r,b,selection,req,choices=control();choices['u0_l0']='wrong_endpoint'
        out=mentions.fork(g,p,r,'authored control',selection,component_response=answer(req,choices))
        row=mentions.project(out)['rows'][0]
        self.assertEqual(len(row['reading']['mentions']),2);self.assertEqual(row['reading']['links'],[])
        self.assertEqual(row['component_checks']['links'][0]['choice'],'wrong_endpoint')
        self.assertEqual(row['component_checks']['status'],'partial')
        self.assertFalse(any(e['type']=='local_work_purpose' for e in out['edges']))

    def test_supported_link_cannot_bypass_rejected_endpoint(self):
        g,p,r,b,selection,req,choices=control();choices['u0_m1']='unsupported_meaning'
        out=mentions.fork(g,p,r,'authored control',selection,component_response=answer(req,choices))
        row=mentions.audit(out)['rows'][0];link=row['component_checks']['links'][0]
        self.assertEqual([m['id'] for m in row['reading']['mentions']],['create'])
        self.assertEqual(link['choice'],'supported');self.assertFalse(link['retained']);self.assertFalse(link['endpoints_retained'])

    def test_completeness_is_separate_from_retained_components(self):
        g,p,r,b,selection,req,choices=control();choices['u0_coverage']='missing_or_bundled'
        out=mentions.fork(g,p,r,'authored control',selection,component_response=answer(req,choices))
        row=mentions.project(out)['rows'][0]
        self.assertEqual(row['component_checks']['status'],'partial')
        self.assertEqual(len(row['reading']['links']),1)
        self.assertEqual(out['coverage']['work_mentions']['component_complete_units'],0)

    def test_whole_candidate_rejection_is_not_rejudged_or_promoted(self):
        g,p,r,b,selection,req,choices=control(2,{'u0':'no_suitable_candidate'})
        self.assertTrue(all(k.startswith('u1_') for k in req['questions']))
        rows=checks.apply(p,b,selection,answer(req,choices))
        self.assertIsNone(rows[0]['reading']);self.assertNotIn('component_checks',rows[0])
        self.assertEqual(rows[0]['choice'],'no_suitable_candidate')

    def test_all_withheld_is_not_empty_complete_reading(self):
        g,p,r,b,selection,req,choices=control()
        choices.update(u0_m0='compound',u0_m1='wrong_attribution_or_mode')
        row=checks.apply(p,b,selection,answer(req,choices))[0]
        self.assertEqual(row['reading']['mentions'],[])
        self.assertEqual(row['component_checks']['status'],'partial')
        self.assertEqual(len(row['component_checks']['mentions']),2)

    def test_missing_or_wrong_model_response_fails_closed(self):
        _,p,_,b,selection,req,choices=control()
        for change in ('model','missing'):
            response=answer(req,choices)
            if change=='model':response['model']='different'
            else:response['answers'].pop('u0_l0')
            with self.subTest(change=change),self.assertRaises(InputError):checks.apply(p,b,selection,response)

    def test_tampered_component_receipt_or_nodes_are_rejected(self):
        g,p,r,b,selection,req,choices=control()
        out=mentions.fork(g,p,r,'authored control',selection,component_response=answer(req,choices))
        for change in ('request','response','node'):
            x=deepcopy(out)
            if change=='request':x['semantic_context']['work_mentions']['component_checks']['request_hash']='wrong'
            elif change=='response':x['semantic_context']['work_mentions']['component_checks']['response']=answer(req,{**choices,'u0_l0':'not_expressed'})
            else:next(n for n in x['nodes'] if n['kind']=='work_mention')['properties']['label']='Different'
            rekey(x)
            with self.subTest(change=change),self.assertRaises(InputError):mentions.audit(x)

    def test_named_withholding_still_takes_precedence(self):
        g,p,r,b,selection,req,choices=control()
        review=dict(author='Development reviewer',basis='Authored mechanics test',units=[dict(unit_id='unit-0',decision='withhold',reason='Further review required')])
        out=mentions.fork(g,p,r,'authored control',selection,review,answer(req,choices))
        row=mentions.project(out)['rows'][0]
        self.assertEqual(row['status'],'withheld');self.assertIsNone(row['reading'])
        self.assertEqual(row['component_checks']['status'],'complete')

    def test_legacy_graph_identity_is_unchanged_without_optional_checks(self):
        g,p,r,b,selection,_,_=control()
        a=mentions.fork(g,p,r,'authored control',selection)
        b=mentions.fork(g,p,r,'authored control',selection,component_response=None)
        self.assertEqual(a,b);self.assertNotIn('component_checks',mentions.project(a)['rows'][0])


if __name__=='__main__':unittest.main()
