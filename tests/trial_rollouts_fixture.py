from pathlib import Path
import json
import os
import sys
import threading
import types

test_dir=Path(__file__).parent;sys.path.insert(0,str(test_dir))
package=types.ModuleType('tests');package.__path__=[str(test_dir)];sys.modules['tests']=package
import tracker
assert 'site-packages' in tracker.__file__,tracker.__file__
from tracker import server
from tracker.store import Store
from test_investigation_trials import setup,design,plan
from test_trial_rollouts import monitors

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
database=root/('returned-'+str(os.getpid())+'.sqlite');store=Store(database)
doc,run=setup(store);raw=design(run);raw['seeds']=[0,1];doc=plan(store,doc,raw);ids=monitors(store)
(root/'fixture.json').write_text(json.dumps(dict(investigation=doc['id'],database=str(database),monitors=ids)),encoding='utf-8')
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    threading.Thread(target=lambda:(sys.stdin.read(),instance.shutdown()),daemon=True).start()
    return instance
server.LocalServer=managed
server.serve(store,port=0)
