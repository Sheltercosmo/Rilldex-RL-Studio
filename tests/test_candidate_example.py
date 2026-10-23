"""The optional local/API example uses the same one-request JSON contract."""
import io
import json
import unittest
from unittest.mock import patch

from rilldex.candidate import propose


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


if __name__=='__main__':unittest.main()
