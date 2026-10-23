from pathlib import Path
import json
import os
import sys
import threading

from rilldex import Run
from tracker.store import Store
from tracker.server import serve
from tracker.workspace_directory import Directory
from tracker import run_records

root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
directory=Directory(root/'registry.sqlite')
first=Store(root/'baseline.sqlite');second=Store(root/'candidate.sqlite')
for store,project in ((first,'Baseline project'),(second,'Candidate project')):
    for name in ('trial-1','trial-2'):
        with Run(name,project=project,workspace=store.path,hardware=False,capture_console=False) as run:
            run.log({'loss':.5,'reward':.3},step=1)
    run_records.save_selection(store,name=project+' comparison',experiments=[project+'/trial-1',project+'/trial-2'])
directory.remember(first.path,'Baseline study');directory.remember(second.path,'Candidate study')
(root/'fixture.json').write_text(json.dumps({'first':str(first.path),'second':str(second.path)}),encoding='utf-8')
stop=threading.Event()
threading.Thread(target=lambda:(sys.stdin.read(),stop.set()),daemon=True).start()
serve(first,port=0,workspace_directory=directory,stop_event=stop)
