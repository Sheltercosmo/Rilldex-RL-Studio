"""Audit the retained incremental feedback trial without keys or model calls.

Validates publication, exact base reuse, coverage and measurement lineage.
It does not supply independent semantic labels or measure accuracy.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if not sys.flags.isolated:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import (decision_cache, feedback_opportunities, graph_store,
    monitoring, monitor_evidence, semantic_catalog, semantic_watch, semantic_workspace)
from tracker.schema import digest
from tracker.semantic_extraction import read, write
from tracker.store import Store
from tracker.workspace_analysis import Workspace


def audit(root, output):
    root=root.resolve();manifest=read(root/'sample.json')
    if manifest['schema']!='continuous-feedback-live-trial/1':
        raise ValueError('Expected the frozen incremental feedback trial')
    package=Path(semantic_watch.__file__).resolve()
    if sys.flags.isolated and 'site-packages' not in package.parts:
        raise ValueError('Isolated audit must use an ordinarily installed package')
    store=Store(manifest['database']);before=semantic_watch.status(store,root/'observer')
    def forbidden(_):raise AssertionError('Retained-result audit attempted new inference')
    after=semantic_watch.run_once(Store(store.path),root/'observer',forbidden)
    assert before['used']==after['used'] and before['provider_usage']==after['provider_usage']
    assert after['current_published']==len(manifest['sample'])
    definition=monitoring.create(store,{'name':'Explicit feedback reference · three text events',
        'kind':'analysis','observer':after['observer'],'analysis':{'measure':'feedback_reference'}})
    monitoring.sync(store)
    values=monitoring.values(store,definition['id'],{s['run_id'] for s in manifest['sample']})
    summaries=[];new_calls=0;reused=0;all_activities=Counter();all_relations=0
    for item in manifest['sample']:
        directory=root/'observer/runs'/item['run_id']
        _,run=semantic_workspace.load(directory)
        assert digest(run)==item['source_hash']
        checked=semantic_workspace.audit(directory);reuse=decision_cache.audit(directory)
        assert reuse['exact_reused_decisions']==item['reused_decisions']
        reused+=reuse['exact_reused_decisions']
        current=semantic_catalog.load(run,after['observer'],store)
        base=semantic_catalog.load(run,manifest['base_observer'],store)
        assert digest(current['raw_extraction'])==digest(base['raw_extraction'])==item['base_extraction_hash']
        job=next(j for j in after['jobs'] if j['run_id']==run['id'])
        graph=graph_store.read(store,job['details']['graph_id']);graph_store.validate(graph)
        assert graph['source_hash']==item['source_hash'] and graph['counts']['unresolved_endpoints']==0
        with store.connect() as c:
            parent=c.execute('SELECT id FROM rollout_graphs WHERE run_id=? AND observer=? AND source_hash=?',
                (run['id'],manifest['base_observer'],item['source_hash'])).fetchall()
        assert len(parent)==1
        base_opportunities=feedback_opportunities.project(graph_store.read(store,parent[0][0]))
        opportunities=feedback_opportunities.project(graph)
        assert base_opportunities['metrics']['denominator']==0
        assert base_opportunities['metrics']['opportunities']==opportunities['metrics']['opportunities']
        measured=values[run['id']]
        for key in ('value','numerator','denominator','opportunities','unknown'):
            assert measured[key]==opportunities['metrics'][key],key
        receipt=monitor_evidence.read(store,measured['id'])
        assert receipt['review_context']['graph_id']==graph['id']
        assert len(receipt['explanation']['analysis_cases'])==opportunities['metrics']['opportunities']
        node_ids={n['id'] for n in graph['nodes']};edge_ids={e['id'] for e in graph['edges']}
        for case in opportunities['observations']:
            assert set(case['node_ids'])<=node_ids and set(case['edge_ids'])<=edge_ids
        units=current['raw_extraction']['units'];all_activities.update(u['activity'] for u in units)
        assert all(u['source']['text'].strip() for u in units)
        decisions=[]
        for path in (directory/'decisions').glob('*.json'):
            saved=read(path);key=digest(saved['request']);assert path.stem==key
            if key in reuse['request_hashes']:continue
            assert saved['request']['state']['stage']=='feedback_assessment'
            wire=list((directory/'wire'/key).glob('*.json'))
            assert len(wire)==1 and read(wire[0])['response']==saved['response']
            new_calls+=1
            decisions.append({'request_hash':key,'answers':saved['answers'],
                'reported_usage':saved['response'].get('usage',{})})
        assert len(decisions)==item['preflight']['request_count']
        relations=[e for e in graph['edges'] if e['type']=='assesses'];all_relations+=len(relations)
        assert run['metadata'].get('training_step') is None
        summaries.append({'run_id':run['id'],'task_id':item['task_id'],'dataset':item['dataset'],
            'source_hash':item['source_hash'],'base_unchanged':True,'reused_decisions':reuse['exact_reused_decisions'],
            'graph_id':graph['id'],'audit':checked,'new_decisions':decisions,
            'base_opportunities':base_opportunities,'feedback_opportunities':opportunities,
            'measurement_id':measured['id'],'measurement_status':measured['status'],
            'selected_references':[{'source':e['source'],'target':e['target'],'properties':e['properties']} for e in relations]})
    assert new_calls==after['used']['jev_requests']==manifest['new_feedback_requests_planned']
    assert after['used']['candidate_requests']==0
    scope=Workspace(store.path,observer=after['observer'])
    assert {r['activity']:r['units'] for r in scope.activity_counts().rows}==all_activities
    assert len(scope.relations(relation='assesses').rows)==all_relations
    native=scope.table('monitor_values',monitor_id=definition['id']).rows
    assert len(native)==len(summaries)
    for row in native:
        assert row['value']==values[row['run_id']]['value']
    displayed=next(m for m in monitoring.snapshot(store)['monitors'] if m['id']==definition['id'])
    assert displayed['coverage']['available']==sum(s['feedback_opportunities']['metrics']['denominator']>0 for s in summaries)
    result={'schema':'live-feedback-result-audit/1','status':'passed',
        'runtime':{'isolated':bool(sys.flags.isolated),'package_path':str(package)},
        'observer':after['observer'],'monitor_id':definition['id'],'rows':summaries,
        'new_calls':new_calls,'exact_reused_base_decisions':reused,'restart_added_calls':0,
        'provider_usage':after['provider_usage'],'sql_counts_match':True,
        'monitor_available_rollouts':displayed['coverage']['available'],
        'limits':{'accuracy':'No independent semantic reference. Citation, argmax and lineage checks are not accuracy.',
            'meaning':'Observable feedback references, not correct interpretation, causal use, recovery or task success.',
            'negative':'No-reference selections need complete observation/candidate windows to support a negative rate.',
            'population':'Two already development-exposed short public tasks; no training coordinate or generalization estimate.',
            'runtime':'Fresh feedback API selection over recorded trajectories, not an adaptive policy or native RL run.'}}
    write(output,result)
    return {k:result[k] for k in ('status','observer','monitor_id','new_calls','exact_reused_base_decisions',
        'restart_added_calls','monitor_available_rollouts','sql_counts_match','limits')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();print(json.dumps(audit(args.root,args.output),indent=2))
