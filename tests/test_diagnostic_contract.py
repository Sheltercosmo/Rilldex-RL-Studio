from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tracker import diagnostic_contract as contract, diagnostic_direct as direct, diagnostic_search as search
from tracker.diagnostic_worker import CallBudgetReached
from tracker.schema import dumps


def source(actor='agent',kind='action'):
    return dict(schema='diagnostic-input/1',id='contract-test',task='Exercise the real application.',
        trace=dumps([dict(id='edit',actor=actor,kind=kind,arguments={'command':"apply_patch <<'PATCH'\n*** Add File: check.py\n+print('pass')\n*** End Patch\nPATCH"})]),
        complete_recorded_text=True,action_coverage='recorded')


def transport(choices=None):
    choices=choices or dict(contract='target_required',result_origin='substitute',use='delivered')
    def send(req):
        answers={}
        for name,q in req['questions'].items():
            selected=next((value for suffix,value in choices.items() if name.startswith('contract-') and name.endswith('_'+suffix)),'none')
            answers[name]=dict(type='choice',probabilities={k:int(k==selected) for k in q['criteria']})
        return dict(model=req['model'],answers=answers)
    return send


class ContractTests(unittest.TestCase):
    def test_literal_source_and_one_request_replay(self):
        s=source();calls=[];send=transport()
        def counted(req):calls.append(req);return send(req)
        with TemporaryDirectory() as temp:
            result=search.execute(s,Path(temp),counted,version=search.CONTRACT_VERSION)
            self.assertEqual(len(calls),1)
            finding=next(f for f in result['findings'] if f['evidence_kind']=='artifact_contract_flag')
            view=finding['artifact_contract']['view'];ref=view['source_payload']
            self.assertIn('apply_patch',s['trace'][ref['start']:ref['end']])
            self.assertEqual(result['metrics']['evaluator_bypass']['value'],1)
            self.assertTrue(search.audit(s,result,temp)['exact_replay'])
            self.assertEqual(search.execute(s,Path(temp),counted),result)
            self.assertEqual(len(calls),1)

    def test_non_flag_controls_and_missing_followup(self):
        for change in [dict(contract='substitute_allowed'),dict(result_origin='target_behavior'),dict(use='quoted'),dict(use='intermediate')]:
            facts=dict(contract='target_required',result_origin='substitute',use='delivered');facts.update(change)
            with TemporaryDirectory() as temp:
                result=search.execute(source(),Path(temp),transport(facts))
                self.assertEqual(result['metrics']['evaluator_bypass']['value'],0)
        for suffix in contract.SUFFIXES:
            facts=dict(contract='target_required',result_origin='substitute',use='delivered');facts[suffix]='unresolved'
            with TemporaryDirectory() as temp:
                result=search.execute(source(),Path(temp),transport(facts))
                self.assertIsNone(result['metrics']['evaluator_bypass']['value'])

    def test_tool_quotes_and_ordinary_pages_keep_wire_cache(self):
        for actor in ['tool','environment','user','system']:
            s=source(actor)
            self.assertEqual(list(direct.requests(s,search.FLOW_VERSION)),list(direct.requests(s,search.CONTRACT_VERSION)))
        s=source();s['trace']=dumps([dict(actor='agent',kind='action',arguments={'command':'ls'})])
        self.assertEqual(list(direct.requests(s,search.FLOW_VERSION)),list(direct.requests(s,search.CONTRACT_VERSION)))

    def test_existing_code_flow_pages_keep_exact_requests(self):
        from test_diagnostic_code_flow import source as flow_source
        s=flow_source()
        self.assertEqual(list(direct.requests(s,search.FLOW_VERSION)),list(direct.requests(s,search.CONTRACT_VERSION)))

    def test_native_arguments_do_not_repeat_large_display_text(self):
        s=source();import json
        rows=json.loads(s['trace']);rows[0]['text']='display copy '*1100;s['trace']=dumps(rows)
        views=[v for r in direct.requests(s,search.CONTRACT_VERSION) for v in r['state'].get('artifact_contract_views',{}).values()]
        # A complete native dispatch uses structured arguments, rather than
        # spending the view budget again on its redundant display string.
        self.assertTrue(views)
        for view in views:self.assertNotIn('display copy',dumps(view['payload']))

    def test_opening_stays_same_native_record_not_neighboring_agent(self):
        from tracker.diagnostic_relations import records
        s=source();s['trace']=dumps([
            dict(actor='agent',text='UNRELATED REQUIREMENT '+('z'*18000),trajectory_id='other'),
            dict(actor='agent',text='RELEVANT OPENING '+('x'*19000)+'\n[action] {"command":"apply_patch *** Add File: check.py"}',trajectory_id='current')])
        fragments=search.index(s,search.CONTRACT_VERSION)
        requests=list(direct.requests(s,search.CONTRACT_VERSION))
        views=[v for r in requests for v in r['state'].get('artifact_contract_views',{}).values()]
        self.assertEqual(len(views),1)
        opening=''.join(f['text'] for f in views[0]['opening_context'])
        self.assertIn('RELEVANT OPENING',opening);self.assertNotIn('UNRELATED REQUIREMENT',opening)
        for f in views[0]['opening_context']:
            self.assertEqual(f['text'],s['trace'][f['start']:f['end']]);self.assertEqual(f['actor'],'agent')

    def test_budget_omits_whole_optional_packet_and_incomplete_stays_unknown(self):
        s=source();base=list(direct.requests(s,search.FLOW_VERSION))[0]
        with patch.object(search,'REQUEST_CHARS',len(dumps(base))+100):
            self.assertEqual(list(direct.requests(s,search.CONTRACT_VERSION)),list(direct.requests(s,search.FLOW_VERSION)))
        def stop(req):raise CallBudgetReached()
        with TemporaryDirectory() as temp:
            result=search.execute(s,Path(temp),stop)
            self.assertIsNone(result['metrics']['evaluator_bypass']['value'])
