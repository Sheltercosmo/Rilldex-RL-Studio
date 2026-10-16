"""Real loopback HTTP failure tests, not fresh model accuracy evidence."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from tracker import jev,semantic_watch as watch
from tracker.semantic_budget import ExecutionBudget,summary
from tracker.semantic_extraction import read
from tracker.schema import dumps
from tracker.store import Store
from tests import test_semantic_watch as watch_tests
from tests.test_semantic_extraction import response as selected_response


@contextmanager
def provider(actions):
    calls=[];completed=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            index=len(calls);calls.append(request);action=actions[index] if index<len(actions) else 'valid'
            if action=='drop':
                completed.append(index);self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if action=='late':time.sleep(.15)
            status=action if type(action) is int else 200
            if status!=200:payload=b'PRIVATE_PROVIDER_RESPONSE test-key'
            elif action=='invalid':payload=b'PRIVATE_INVALID_JSON'
            elif action=='large':payload=b'x'*1025
            else:payload=dumps(selected_response(request) if request.get('questions') else {'model':'test','answers':{}}).encode()
            self.send_response(status);self.send_header('Content-Length',str(len(payload)))
            if status==429:self.send_header('Retry-After','17')
            self.end_headers();completed.append(index)
            try:self.wfile.write(payload)
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with patch.object(jev,'ENDPOINT',f'http://127.0.0.1:{server.server_port}/v1/systemone'),patch.dict(os.environ,{'JEV_API_KEY':'test-key'}):
            yield calls,completed
    finally:server.shutdown();server.server_close();thread.join(timeout=3)


class JevTransportTests(unittest.TestCase):
    def test_overload_is_one_http_attempt_with_safe_retry_hint_and_no_body(self):
        with provider([429]) as (calls,_),TemporaryDirectory() as directory:
            budget=ExecutionBudget(directory,1,{'jev_requests':1})
            with self.assertRaises(jev.JevTransportError) as error:
                budget.invoke('jev',{'questions':{}},lambda:jev.JevClient().transport({'questions':{}}))
            self.assertEqual(len(calls),1);self.assertEqual(error.exception.details['retry_after_seconds'],17)
            self.assertTrue(error.exception.details['retryable']);self.assertEqual(budget.used['jev_requests'],1)
            saved=read(next((Path(directory)/'attempts').glob('*.json')))
            self.assertEqual(saved['provider_failure']['http_status'],429)
            self.assertNotIn('PRIVATE_PROVIDER_RESPONSE',dumps(saved));self.assertNotIn('test-key',dumps(saved))
            self.assertEqual(summary(directory)['providers']['jev']['attempts_without_reported_usage'],1)

    def test_dropped_or_late_response_may_follow_completed_provider_work(self):
        for action in ('drop','late'):
            with self.subTest(action=action),provider([action]) as (calls,completed):
                with self.assertRaises(jev.JevTransportError) as error:
                    jev.JevClient(timeout=.03).transport({'questions':{}})
                self.assertEqual(error.exception.details['outcome'],'unknown');self.assertEqual(len(calls),1)
                time.sleep(.18)
                self.assertEqual(completed,[0]);self.assertEqual(len(calls),1)

    def test_http_errors_do_not_retry_or_expose_response_text(self):
        for code in (401,403,408,451,500,503,529):
            with self.subTest(code=code),provider([code]) as (calls,_):
                with self.assertRaises(jev.JevTransportError) as error:jev.JevClient().transport({'questions':{}})
                self.assertEqual(len(calls),1);self.assertEqual(error.exception.details['http_status'],code)
                self.assertNotIn('test-key',str(error.exception));self.assertNotIn('PRIVATE',str(error.exception))

    def test_bad_and_oversize_responses_are_unusable_not_automatically_regenerated(self):
        for action,category in [('invalid','invalid_response'),('large','response_too_large')]:
            with self.subTest(action=action),provider([action]) as (calls,_),patch.object(jev,'MAX_RESPONSE_BYTES',1024):
                with self.assertRaises(jev.JevTransportError) as error:jev.JevClient().transport({'questions':{}})
                self.assertEqual(error.exception.details['category'],category);self.assertEqual(len(calls),1)

    def test_missing_credentials_are_distinguished_from_unknown_remote_outcome(self):
        with patch.dict(os.environ,{},clear=True),patch.object(jev.urllib.request,'urlopen') as network:
            with self.assertRaises(jev.JevTransportError) as error:jev.JevClient().transport({'questions':{}})
            self.assertEqual(error.exception.details['outcome'],'not_sent');network.assert_not_called()


class JevWorkerHttpTests(unittest.TestCase):
    setUp=watch_tests.SemanticWatchTests.setUp
    init=watch_tests.SemanticWatchTests.init
    source=watch_tests.SemanticWatchTests.source
    run_worker=watch_tests.SemanticWatchTests.run_worker
    def test_wire_failure_retry_has_its_own_durable_reservation(self):
        self.init(allowance={**self.cap,'jev_requests':3});rid=self.source()['id']
        with provider([429]) as (calls,_):
            client=jev.JevClient();failed=self.run_worker(client.transport)
            self.assertEqual(len(calls),1);self.assertEqual(failed['used']['jev_requests'],1)
            self.assertEqual(failed['job_counts'],{'failed':1})
            self.assertEqual(failed['jobs'][0]['details']['provider_failure']['http_status'],429)
            self.store=Store(self.store.path)
            self.run_worker(client.transport);self.assertEqual(len(calls),1)
            capped=self.run_worker(client.transport,retry_runs=[rid])
            self.assertEqual(capped['job_counts'],{'budget_reached':1});self.assertEqual(len(calls),3)
            watch.set_allowance(self.store,self.work,{**self.cap,'jev_requests':4})
            complete=self.run_worker(client.transport,retry_runs=[rid])
            self.assertEqual(complete['job_counts'],{'published':1});self.assertEqual(len(calls),4)
            self.run_worker(client.transport);self.assertEqual(len(calls),4)
            self.assertEqual(complete['attempt_statuses']['failed_or_interrupted'],1)
            self.assertEqual(complete['used']['jev_requests'],len(calls))


if __name__=='__main__':unittest.main()
