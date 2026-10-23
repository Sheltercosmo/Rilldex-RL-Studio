from pathlib import Path
import json
import os
import sys
import threading

sys.path.insert(0, str(Path(__file__).parent))
import tracker
assert 'site-packages' in tracker.__file__, tracker.__file__
from tracker import server
from tracker.store import Store
from test_investigation_trials import setup

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
store=Store(root/('trials-'+str(os.getpid())+'.sqlite'))
doc,run=setup(store)
(root/'fixture.json').write_text(json.dumps(dict(investigation=doc['id'],run=run['id'],event=run['events'][20]['id'])),encoding='utf-8')
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    threading.Thread(target=lambda:(sys.stdin.read(),instance.shutdown()),daemon=True).start()
    return instance
server.LocalServer=managed
server.serve(store,port=0)
