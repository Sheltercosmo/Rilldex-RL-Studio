"""Audit retained live-model results without credentials or further inference.

This checks software/evidence/metric consistency, not semantic accuracy. The
sample manifest and actual provider receipts remain the provenance boundary.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if not sys.flags.isolated:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import graph_store, monitoring, semantic_catalog, semantic_watch, semantic_workspace
from tracker.rollout_metrics import report as metric_report
from tracker.schema import digest
from tracker.semantic_extraction import read, write
from tracker.store import Store
from tracker.workspace_analysis import Workspace


def audit(root, output):
    package_path=Path(semantic_watch.__file__).resolve()
    if sys.flags.isolated and 'site-packages' not in package_path.parts:
        raise ValueError('Isolated audit must import an ordinarily installed package')
    root=root.resolve();store=Store(root/'workspace.sqlite');manifest=read(root/'sample.json')
    if manifest['schema']!='fresh-semantic-validation/1':raise ValueError('Expected a frozen live-trial manifest')
    before=semantic_watch.status(store,root/'observer')
    if before['current_published']!=len(manifest['sample']):raise ValueError('Trial still has unpublished sources')
    def forbidden(_):raise AssertionError('Audit/restart attempted fresh inference')
    after=semantic_watch.run_once(Store(store.path),root/'observer',forbidden)
    assert before['used']==after['used'] and before['provider_usage']==after['provider_usage']
    measured=metric_report(store);summaries=[];by_stage={};models=Counter();all_activities=Counter()
    for item in manifest['sample']:
        directory=root/'observer/runs'/item['run_id'];config,run=semantic_workspace.load(directory)
        assert digest(run)==item['source_hash']
        checked=semantic_workspace.audit(directory)
        bundle=semantic_catalog.load(run,after['observer'],store)
        job=next(j for j in after['jobs'] if j['run_id']==run['id'])
        graph=graph_store.read(store,job['details']['graph_id'])
        graph_store.validate(graph)
        assert graph['source_hash']==item['source_hash'] and not graph['counts']['unresolved_endpoints']
        units=bundle['raw_extraction']['units'];activities=Counter(u['activity'] for u in units)
        assert all(u['source']['text'].strip() for u in units)
        all_activities.update(activities)
        decisions=list((directory/'decisions').glob('*.json'));calls=Counter();tokens=Counter()
        for path in decisions:
            saved=read(path);key=digest(saved['request']);assert path.stem==key
            wire=list((directory/'wire'/key).glob('*.json'))
            assert len(wire)==1 and read(wire[0])['response']==saved['response']
            stage=saved['request']['state']['stage'];calls[stage]+=1
            usage=saved['response'].get('usage',{});tokens.update(usage)
            group=by_stage.setdefault(stage,{'calls':0,'reported_usage':Counter()})
            group['calls']+=1;group['reported_usage'].update(usage)
            models[str(saved['response'].get('model'))]+=1
        row=next(r for r in measured['rows'] if r['run_id']==run['id'] and r['observer']==after['observer'])
        assert row['agent_activity_counts']==activities
        assert row['metrics']['agent_verify_unit_share']['denominator']==len(units)
        assert row['metrics']['agent_verify_unit_share']['numerator']==activities['verify']
        assert row['metrics']['recovery_rate']['value'] is None
        assert run['metadata'].get('training_step') is None  # Do not fabricate a training curve.
        summaries.append({'run_id':run['id'],'dataset':item['dataset'],'task_id':item['task_id'],
            'source_hash':item['source_hash'],'graph_id':graph['id'],'units':len(units),'activities':dict(activities),
            'native_feedback_links':sum(e['type']=='feedback_for' for e in graph['edges']),
            'calls_by_stage':dict(calls),'reported_usage':dict(tokens),'audit':checked,
            'verify_prose':row['metrics']['activity_verify_share'],
            'verify_all_tagged_activities':row['metrics']['agent_verify_unit_share'],
            'selected_content':[{'unit_id':u['id'],'event':u['source']['event_id'],'activity':u['activity'],
                'text':u['source']['text'],'content':u['content']} for u in units]})
    scope=Workspace(store.path,observer=after['observer'])
    sql_counts={r['activity']:r['units'] for r in scope.activity_counts().rows}
    assert sql_counts==all_activities
    monitor=monitoring.create(store,{'name':'Verify share across tagged activities','kind':'metric',
        'metric':'agent_verify_unit_share','observer':after['observer']})
    relationship=monitoring.create(store,{'name':'Feedback assessment · requires relation observation','kind':'graph',
        'observer':after['observer'],'requirement':monitoring.graph_queries.PRESETS['assessment_of_inspection_feedback']})
    monitoring.sync(store);monitors=monitoring.snapshot(store)['monitors']
    selected=next(m for m in monitors if m['id']==monitor['id'])
    unknown=next(m for m in monitors if m['id']==relationship['id'])
    assert selected['coverage']['available']==len(summaries) and unknown['coverage']['available']==0
    assert sum(v['calls'] for v in by_stage.values())==after['used']['jev_requests']
    result={'schema':'live-semantic-result-audit/1','status':'passed','observer':after['observer'],
        'runtime':{'isolated':bool(sys.flags.isolated),'package_path':str(package_path)},
        'sources':len(summaries),'selected_units':sum(all_activities.values()),'activities':dict(all_activities),
        'provider_usage':after['provider_usage'],'model_responses':dict(models),'by_stage':by_stage,
        'rows':summaries,'restart_added_calls':0,'sql_counts_match':True,
        'monitor_available_rollouts':selected['coverage']['available'],
        'relationship_monitor_available_rollouts':unknown['coverage']['available'],
        'limits':{'accuracy':'No independent semantic reference; structural/citation checks are not accuracy.',
            'runtime':'Fresh semantic inference on recorded public traces; no adaptive task agent or RL optimizer.',
            'candidate_usage':'Fresh Luna file handoff. Subagent token usage not supplied; no zero-cost inference.',
            'population':'Two short task groups selected by length/hash, now development-exposed; not a representative throughput or cost estimate.',
            'time':'No native training coordinate. No training-curve or online-prefix quality claim.'}}
    write(output,result)
    return {k:result[k] for k in ('status','sources','selected_units','activities','provider_usage',
        'model_responses','restart_added_calls','sql_counts_match','monitor_available_rollouts',
        'relationship_monitor_available_rollouts','limits')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();print(json.dumps(audit(args.root,args.output),indent=2))
