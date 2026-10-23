import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from rilldex import Run
from tracker import run_records
from tracker.server import serve
from tracker.store import Store
from tracker.schema import InputError
from tracker.workspace_directory import Directory, identity, validate_database, view_path


class WorkspaceDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.directory=Directory(self.root/'directory.sqlite')
        self.servers=[]
        self.store=Store(self.root/'first.sqlite')

    def tearDown(self):
        for stop,thread,_ in reversed(self.servers):
            stop.set();thread.join(20)
            self.assertFalse(thread.is_alive(),'Server did not close')
        self.temp.cleanup()

    def start(self,store=None,*,directory=True):
        ready=threading.Event();stop=threading.Event();values={}
        def callback(url):values['url']=url;ready.set()
        def run():
            try:serve(store or self.store,port=0,workspace_directory=self.directory if directory else None,stop_event=stop,on_ready=callback)
            except Exception as e:values['error']=repr(e);ready.set()
        thread=threading.Thread(target=run,daemon=True);thread.start()
        self.servers.append((stop,thread,values))
        self.assertTrue(ready.wait(15));self.assertNotIn('error',values)
        return values['url']

    def request(self,url,path,value=None):
        request=Request(url+path,data=json.dumps(value).encode() if value is not None else None,
                        headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=35) as response:return json.load(response)

    def packet(self,text):
        return dict(schema='run-records/1',producer='same-worker',experiment='same-run',records=[dict(
            id=text,session='same-session',kind='console',observed_at='2026-10-22T10:00:00Z',payload=dict(stream='stdout',text=text))])

    def test_switching_keeps_ingestion_projects_and_saved_comparisons_isolated(self):
        a=self.start()
        with Run('baseline',project='study-a',workspace=self.store.path,hardware=False,capture_console=False):pass
        run_records.save_selection(self.store,name='Review pair',experiments=['study-a/baseline'])
        target=self.root/'second.sqlite'
        result=self.request(a,'/api/workspaces/open',dict(path=str(target),create=True,name='Second study',current_view='/?view=health&experiment=study-a%2Fbaseline'))
        b=result['url'];self.assertNotEqual(a,b.rstrip('/'))
        self.request(a,'/api/run-records',self.packet('first-after-switch'))
        self.request(b.rstrip('/'),'/api/run-records',self.packet('second-only'))
        self.assertEqual(run_records.records(self.store,experiment='same-run')['total'],1)
        second=Store(target)
        self.assertEqual(run_records.records(second,experiment='same-run')['total'],1)
        self.assertEqual(run_records.records(self.store,experiment='same-run')['rows'][0]['record']['payload']['text'],'first-after-switch')
        with second.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM experiment_selections').fetchone()[0],0)
        self.request(b.rstrip('/'),'/api/workspaces/view',dict(view='/connections#data-access-section'))
        back=self.request(b.rstrip('/'),'/api/workspaces/open',dict(id=identity(self.store.path),current_view='/connections#data-access-section'))
        self.assertEqual(back['url'],a+'/?view=health&experiment=study-a%2Fbaseline');self.assertTrue(back['reused'])
        again=self.request(a,'/api/workspaces/open',dict(id=identity(target)))
        self.assertEqual(again['url'],b.rstrip('/')+'/connections#data-access-section')
        catalog=self.request(a,'/api/workspaces')
        self.assertEqual({r['state'] for r in catalog['rows']},{'current','open'})
        self.assertEqual(next(r['name'] for r in catalog['rows'] if r['id']==identity(target)),'Second study')
        self.servers[0][0].set();self.servers[0][1].join(20);self.assertFalse(self.servers[0][1].is_alive())
        with self.assertRaises(OSError):urlopen(b.rstrip('/')+'/api/health',timeout=1)
        reopened=self.start()
        resumed=self.request(reopened,'/api/workspaces/open',dict(id=identity(target)))
        self.assertEqual(resumed['url'],b.rstrip('/')+'/connections#data-access-section')
        self.assertEqual(run_records.records(Store(target),experiment='same-run')['total'],1)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM experiment_selections').fetchone()[0],1)

    def test_simultaneous_open_reuses_one_server_and_external_server_is_not_owned(self):
        a=self.start();other=Store(self.root/'other.sqlite');self.directory.remember(other.path)
        def open_one(_):return self.request(a,'/api/workspaces/open',dict(id=identity(other.path)))
        with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(open_one,range(3)))
        self.assertEqual(len({r['url'] for r in results}),1)
        self.assertEqual(sum(not r['reused'] for r in results),1)
        external=Store(self.root/'external.sqlite');endpoint=self.start(external)
        result=self.request(a,'/api/workspaces/open',dict(id=identity(external.path)))
        self.assertEqual(result['url'],endpoint+'/');self.assertTrue(result['reused'])
        self.servers[0][0].set();self.servers[0][1].join(20)
        self.assertTrue(self.request(endpoint,'/api/health')['ready'])

    def test_wrong_workspace_or_instance_on_reused_port_is_not_reused(self):
        a=self.start();other=Store(self.root/'other.sqlite');row=self.directory.remember(other.path)
        with self.directory.connect() as c:
            c.execute('UPDATE workspaces SET endpoint=?,instance=? WHERE id=?',(a,'stale-process',row['id']))
        with self.assertRaises(HTTPError) as error:
            self.request(a,'/api/workspaces/open',dict(id=row['id']))
        self.assertEqual(error.exception.code,400)
        self.assertIn('saved capture port',json.load(error.exception)['error'])
        same=self.directory.get(identity(self.store.path));same['instance']='stale-process'
        from tracker.workspace_directory import alive
        self.assertFalse(alive(same))

    def test_invalid_files_create_collisions_and_invalid_names_do_not_change_data(self):
        endpoint=self.start();bad=self.root/'unrelated.sqlite'
        connection=sqlite3.connect(bad)
        connection.execute('CREATE TABLE unrelated(value)');connection.commit();connection.close()
        raw=bad.read_bytes()
        cases=[dict(path=str(bad)),dict(path=str(bad),create=True),dict(path='missing.sqlite'),
               dict(path='new.sqlite',create=True,name=' '),dict(path='new.sqlite',create='yes'),
               dict(path=str(self.directory.path)),dict(path='new.sqlite',create=True,current_view='https://example.org')]
        for body in cases:
            with self.subTest(body=body),self.assertRaises(HTTPError) as error:
                self.request(endpoint,'/api/workspaces/open',body)
            self.assertEqual(error.exception.code,400)
        self.assertEqual(bad.read_bytes(),raw);self.assertFalse((self.root/'new.sqlite').exists())

    def test_missing_recents_can_be_removed_without_deleting_database(self):
        endpoint=self.start();other=Store(self.root/'other.sqlite');row=self.directory.remember(other.path)
        self.request(endpoint,'/api/workspaces/forget',dict(id=row['id']))
        self.assertTrue(other.path.is_file());validate_database(other.path)
        with self.assertRaises(HTTPError):self.request(endpoint,'/api/workspaces/forget',dict(id=identity(self.store.path)))
        row=self.directory.remember(other.path);other.path.unlink()
        listing=self.request(endpoint,'/api/workspaces')
        self.assertEqual(next(r['state'] for r in listing['rows'] if r['id']==row['id']),'missing')
        self.request(endpoint,'/api/workspaces/forget',dict(id=row['id']))

    def test_view_validation_and_create_uses_current_database_parent(self):
        endpoint=self.start()
        result=self.request(endpoint,'/api/workspaces/open',dict(path='space λ.sqlite',create=True,name='Study λ'))
        self.assertTrue((self.root/'space λ.sqlite').is_file())
        self.assertEqual(len(self.request(endpoint,'/api/workspaces')['rows']),2)
        for value in ('//external.example/', '/api/workspace/snapshot', '/\\evil', '', None):
            with self.subTest(value=value),self.assertRaises(InputError):view_path(value)

    def test_unavailable_recent_directory_does_not_stop_capture(self):
        blocked=self.root/'not-a-directory';blocked.write_text('existing file')
        with patch.dict(os.environ,RILLDEX_WORKSPACE_REGISTRY=str(blocked/'registry.sqlite')):
            endpoint=self.start(directory=False)
        self.assertTrue(self.request(endpoint,'/api/health')['ready'])
        self.request(endpoint,'/api/run-records',self.packet('capture-still-works'))
        self.assertEqual(run_records.records(self.store,experiment='same-run')['total'],1)
        self.assertEqual(self.request(endpoint,'/api/workspace-identity')['name'],'first.sqlite')
        with self.assertRaises(HTTPError) as error:self.request(endpoint,'/api/workspaces')
        self.assertEqual(error.exception.code,503)

    def test_cli_registration_listing_and_invalid_file(self):
        import subprocess,sys
        env=dict(os.environ,RILLDEX_WORKSPACE_REGISTRY=str(self.root/'cli-registry.sqlite'))
        def cli(*args):return subprocess.run([sys.executable,'-m','rilldex','workspace',*args],env=env,
                                            text=True,encoding='utf-8',capture_output=True,timeout=15)
        added=cli('add',str(self.store.path),'--name','Study λ')
        self.assertEqual(added.returncode,0,added.stderr);self.assertEqual(json.loads(added.stdout)['name'],'Study λ')
        listed=cli('list');self.assertEqual(listed.returncode,0,listed.stderr)
        self.assertEqual(json.loads(listed.stdout)['workspaces'][0]['state'],'closed')
        missing=self.root/'missing.sqlite';failed=cli('add',str(missing))
        self.assertNotEqual(failed.returncode,0);self.assertFalse(missing.exists())


if __name__=='__main__':unittest.main()
