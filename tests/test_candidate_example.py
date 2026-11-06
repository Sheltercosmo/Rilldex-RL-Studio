"""The optional local/API example uses the same one-request JSON contract."""
import io
import json
import unittest
from unittest.mock import patch

from rilldex.candidate import propose,settings,identity


class CandidateExampleTests(unittest.TestCase):
    def test_local_and_hosted_requests_preserve_packet_and_json_contract(self):
        packet={'stage':'units','response_contract':{'units':[]},'source':'quoted trace'}
        response=json.dumps({'choices':[{'message':{'content':'{"units":[]}'}}]}).encode()
        for endpoint in ('http://127.0.0.1:8000/v1/chat/completions','https://example.invalid/v1/chat/completions'):
            with patch('rilldex.candidate.urlopen',return_value=io.BytesIO(response)) as call:
                self.assertEqual(propose(packet,endpoint=endpoint,model='pinned-model'),{'units':[]})
                call.assert_called_once()
                request=call.call_args.args[0]
                body=json.loads(request.data)
                self.assertEqual(json.loads(body['messages'][1]['content']),packet)
                self.assertEqual(body['response_format'],{'type':'json_object'})
                self.assertNotIn('Authorization',request.headers)

    def test_invalid_endpoints_never_make_a_request(self):
        for endpoint in ('http://remote.invalid/v1/chat/completions','https://user:secret@example.invalid/chat','https://example.invalid/chat?key=secret'):
            with patch('rilldex.candidate.urlopen') as call:
                with self.assertRaises(ValueError):propose({},endpoint=endpoint,model='model')
                call.assert_not_called()

    def test_nonobject_candidate_is_rejected(self):
        response=json.dumps({'choices':[{'message':{'content':'[]'}}]}).encode()
        with patch('rilldex.candidate.urlopen',return_value=io.BytesIO(response)):
            with self.assertRaises(ValueError):propose({},endpoint='http://localhost:8000/chat',model='model')

    def test_prompt_only_endpoint_uses_same_validated_payload_without_json_mode(self):
        packet={'request':{'source':'exact source','response_contract':{'candidates':[]}}}
        response=json.dumps({'choices':[{'message':{'content':'{"candidates":[]}'}}]}).encode()
        with patch('rilldex.candidate.urlopen',return_value=io.BytesIO(response)) as call:
            result=propose(packet,endpoint='http://localhost:8000/chat',model='local-model',json_mode='prompt')
            self.assertEqual(result,{'candidates':[]})
            body=json.loads(call.call_args.args[0].data)
            self.assertNotIn('response_format',body)
            self.assertEqual(json.loads(body['messages'][1]['content']),packet)
            call.assert_called_once()

    def test_generation_mode_is_pinned_without_changing_legacy_identity(self):
        env=dict(RILLDEX_LLM_PRESET='local',RILLDEX_LLM_MODEL='pinned',RILLDEX_LLM_API_KEY='test-only')
        legacy=identity(settings(env));self.assertEqual(set(legacy),{'adapter','endpoint','model'})
        changed=identity(settings({**env,'RILLDEX_LLM_JSON_MODE':'prompt'}))
        self.assertEqual(changed,{**legacy,'json_mode':'prompt'})
        self.assertNotIn('test-only',json.dumps(changed))
        with self.assertRaises(ValueError):settings({**env,'RILLDEX_LLM_JSON_MODE':'guess'})


if __name__=='__main__':unittest.main()
