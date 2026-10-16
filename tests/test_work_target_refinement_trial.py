"""The second request must not replace authentication with a decision hash."""
from io import BytesIO
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from research import work_target_refinement_trial as trial
from tracker.schema import digest
from tracker.semantic_extraction import write


class TrialAuthenticationTests(unittest.TestCase):
    def test_multiple_selected_requests_keep_credential_separate_from_request_hash(self):
        captured=[]
        class Opener:
            handlers=[urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'})]
            def open(self,outgoing,timeout):
                captured.append(outgoing.get_header('Authorization'))
                req=json.loads(outgoing.data)
                return BytesIO(json.dumps({'model':req['model'],'answers':{'choice':{
                    'type':'choice','probabilities':{'c0':1,'unresolved':0}}}}).encode())
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp);rows=[]
            for i in range(2):
                req={'model':'jev-1.13.0','state':{'cutoff_event_id':str(i),'missingness':{}},
                     'questions':{'choice':{'type':'choice','criteria':{'c0':'one','unresolved':'unknown'}}}}
                rows.append({'id':str(i),'population':'retained_reasoning_unit','request':req,'request_hash':digest(req)})
            write(dest/'manifest.json',{'requests':rows,'maximum_http_attempts':2,'maximum_input_bytes':10000})
            with patch.object(trial,'DEST',dest),patch.object(trial,'OBSERVER',dest/'observer'),\
                 patch.object(trial.urllib.request,'build_opener',return_value=Opener()),\
                 patch.object(trial.getpass,'getpass',return_value='test-only-placeholder'),\
                 patch.object(trial.refinement,'execute',return_value={'status':'complete','changes':[]}),\
                 patch.object(trial,'audit',return_value={'rows':[]}),patch('builtins.print'):
                trial.run()
            self.assertEqual(captured,['Bearer test-only-placeholder']*2)


if __name__=='__main__':unittest.main()
