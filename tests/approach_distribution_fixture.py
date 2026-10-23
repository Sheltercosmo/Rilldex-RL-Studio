"""Isolated authored controls + optional retained public observer replay."""
from pathlib import Path
import json
import os
import sqlite3
import sys
import threading
import types

tests=Path(__file__).parent
sys.path.insert(0,str(tests))
package=types.ModuleType('tests');package.__path__=[str(tests)];sys.modules['tests']=package
from test_approach_distribution import save_run
import tracker
assert 'site-packages' in tracker.__file__,tracker.__file__
from tracker import server,behavior_distributions as bd
from tracker.store import Store

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
database=root/('approaches-'+str(os.getpid())+'.sqlite')
public=os.environ.get('RILLDEX_PUBLIC_APPROACH_REPLAY')
if public:
    with sqlite3.connect(Path(public,'review.sqlite').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(database) as target:source.backup(target)
store=Store(database)
for step,reports,procedures in [
    (0,['reported']*17,['same_procedure']*16),
    (1,['reported','reported','unresolved'],['reconfigured_procedure']*2),
    (2,['reported','reported'],['alternative_procedure']),
    (3,['reported','not_reported'],['same_procedure']),
    (4,['reported','not_reported','reported','unresolved'],['reconfigured_procedure']*3),
    (5,['reported','not_reported','reported'],['alternative_procedure']*2),
    (5,['reported','unresolved'],[None]),
]:save_run(store,str(step)+'-'+str(len(reports)),step,reports,procedures)
snapshot=bd.snapshot(store,lens='procedure',experiment='approach-followup-controls',a_start=0,a_end=2,b_start=3,b_end=5)
(root/'authored.json').write_text(json.dumps(snapshot),encoding='utf-8')
replays=[]
if public:
    for fixture in json.loads(Path(public,'fixture.json').read_text(encoding='utf-8')):
        d=bd.snapshot(store,lens='procedure',observer=fixture['observer'],population_mode='task_mix')
        f=d['approach_followup']['overall'];counts={key:sum(r['counts'][key] for r in f['rows']) for key in ('reported_again','no_reported_error','followup_unknown')}
        measured=fixture['error_measure']
        assert counts['reported_again']==measured['numerator']
        assert counts['reported_again']+counts['no_reported_error']==measured['denominator']
        assert counts['followup_unknown']==measured['unknown']
        replays.append(dict(observer=fixture['observer'],counts=counts,snapshot_id=d['snapshot_id'],total=f['total'],
                            prior_report_unknown=f['prior_report_unknown'],no_prior_error=f['no_prior_error']))
(root/'public-replay.json').write_text(json.dumps(replays,indent=2),encoding='utf-8')
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    def stop():sys.stdin.read();instance.shutdown()
    threading.Thread(target=stop,daemon=True).start();return instance
server.LocalServer=managed
server.serve(store,port=0)
