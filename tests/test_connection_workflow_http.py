"""Real loopback source-check → managed delivery → source-map → restart workflow."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen

from tracker.portable import chat_document
from tracker.store import Store
from test_input_http import SERVER


def request(endpoint, path, body=None):
    req=Request(endpoint+path, data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=15) as response: return json.load(response)


@contextmanager
def server(root):
    log=root/'server.log';env=dict(os.environ,PYTHONUTF8='1');env.pop('JEV_API_KEY',None)
    with log.open('w',encoding='utf-8') as stream:
        process=subprocess.Popen([sys.executable,'-c',SERVER,str(root/'workspace.sqlite')],
            stdin=subprocess.PIPE,stdout=stream,stderr=stream,text=True,env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            deadline=time.monotonic()+15;endpoint=None
            while time.monotonic()<deadline and process.poll() is None:
                match=re.search(r'Rilldex: (http://127\.0\.0\.1:\d+)',log.read_text(encoding='utf-8'))
                if match: endpoint=match[1];break
                time.sleep(.05)
            if endpoint is None: raise AssertionError(log.read_text(encoding='utf-8'))
            yield endpoint
        finally:
            try:process.communicate(input='',timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


class ConnectionWorkflowHTTPTests(unittest.TestCase):
    def wait(self, predicate):
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            value=predicate()
            if value:return value
            time.sleep(.1)
        self.fail('Managed source did not reach the expected state')

    def test_long_rollout_preview_partial_writes_revisions_map_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);outputs=root/'job output';outputs.mkdir()
            config=dict(root=str(outputs),mode='exports',producer='long/worker',interval=.2,
                        metadata={'experiment':'long workflow'})
            messages=[{'role':'user','content':'Find and repair the parser error. Verify the final change.'}]
            for index in range(40):
                messages += [{'role':'assistant','content':f'Attempt {index+1}: inspect the current result.',
                              'tool_calls':[{'id':str(index),'type':'function','function':{'name':'check','arguments':{'attempt':index}}}]},
                             {'role':'tool','tool_call_id':str(index),'content':'Check failed: expected two items.' if index<39 else 'Check passed.'}]
            envelope=dict(producer='long/worker',rollout_id='parser',revision=0,state='in_progress',
                          document=chat_document(messages),metadata={'training_step':7,'training_step_basis':'generation_iteration'})
            path=outputs/'worker.jsonl'
            with server(root) as endpoint:
                self.assertEqual(request(endpoint,'/api/connections/preview',config)['files'],0)
                cid=request(endpoint,'/api/connections',config)['id']
                row=lambda: next(r for r in request(endpoint,'/api/connections')['connections'] if r['id']==cid)
                raw=json.dumps(envelope)
                path.write_text(raw[:len(raw)//2],encoding='utf-8')
                self.wait(lambda:row()['status'].get('waiting'))
                self.assertEqual(row()['recent_rollouts'],[])
                with path.open('a',encoding='utf-8') as out:out.write(raw[len(raw)//2:]+'\n')
                first=self.wait(lambda:row()['recent_rollouts']) [0]
                self.assertEqual(first['experiment'],'long workflow')
                self.assertEqual(first['training_step'],7)
                check=request(endpoint,'/api/connections/preview',config)
                sample=check['coverage']['runs'][0]['source_preview']
                self.assertGreater(sample['total_events'],120)
                self.assertEqual(len(sample['events']),12)
                self.assertGreater(sample['omitted_relations'],30)
                source=request(endpoint,'/api/runs/'+first['run_id']+'?raw=1')['run']
                self.assertEqual(len(source['events']),sample['total_events'])
                with urlopen(endpoint+'/semantic-map?run='+first['run_id']+'&observer=source') as response:
                    self.assertIn('rollout-map.js',response.read().decode())
                envelope['document']['messages'].append({'role':'assistant','content':'The last check passed; the change is ready.'})
                envelope.update(revision=1,state='complete')
                with path.open('a',encoding='utf-8') as out:out.write(json.dumps(envelope)+'\n')
                current=self.wait(lambda:row()['recent_rollouts'][0] if row()['received']['received_revisions']==2 else None)
                self.assertNotEqual(first['run_id'],current['run_id'])
                self.assertEqual(current['revision'],1)
                preview=request(endpoint,'/api/connections/preview',config)['coverage']['runs'][0]['source_preview']
                self.assertEqual(preview['delivery'],{'revision':1,'state':'complete'})
                # Complete-file checking shares the source preview but stays read-only.
                batch=json.dumps(chat_document(messages)).encode()
                before=len(Store(root/'workspace.sqlite').list())
                checked=request(endpoint,'/api/import-file/check',{'file':{'name':'replay.json','base64':base64.b64encode(batch).decode()}})
                self.assertEqual(checked['runs'][0]['source_preview']['events'][0]['text'],messages[0]['content'])
                self.assertEqual(len(Store(root/'workspace.sqlite').list()),before)
            with server(root) as endpoint:
                row=lambda: next(r for r in request(endpoint,'/api/connections')['connections'] if r['id']==cid)
                self.wait(lambda:row()['status'].get('checked_at'))
                self.assertEqual(row()['received']['received_revisions'],2)
                self.assertEqual(row()['recent_rollouts'][0]['run_id'],current['run_id'])
                self.assertEqual(request(endpoint,'/api/runs/'+first['run_id']+'?raw=1')['run']['id'],first['run_id'])


if __name__=='__main__':unittest.main()
