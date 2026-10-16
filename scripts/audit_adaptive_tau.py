"""Check fresh native rollout provenance and capture, without model calls."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

if not sys.flags.isolated:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import graph_store
from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.store import Store
from rilldex import Workspace


def audit(root,output):
    root=root.resolve()
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    spec=importlib.util.spec_from_file_location('adaptive',Path(__file__).with_name('run_adaptive_tau.py'))
    h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    report=read(root/'report.json');manifest=read(root/'manifest.json');document=read(root/'latest-document.json')
    assert report['status'] in {'completed','turn_limit'}
    history=[];messages=document['simulation']['messages'];policy_turns=[]
    for row in report['requests']:
        stem=f"{row['turn']:03}";directory=root/row['role']
        packet=read(directory/'requests'/f'{stem}.json');reply=read(directory/'responses'/f'{stem}.json')
        assert h.digest(packet)==row['request_hash']==reply['request_hash']
        assert packet['messages']==h.visible_messages(history,row['role'])
        assert packet['role']==row['role'] and packet['turn']==row['turn']
        if row['role']=='assistant':
            assert packet['system']==manifest['info']['environment_info']['policy']
            assert packet['tools']==manifest['info']['environment_info']['tool_defs']
        else:assert packet['tools']==[]
        selected=h.validate_response(packet,reply)
        assert h.digest(selected)==row['response_hash']
        native=messages[len(history)]
        assert native['role']==row['role'] and native['content']==selected['content']
        history.append(native)
        if selected['tool_calls']:
            assert len(native['tool_calls'])==1
            call=native['tool_calls'][0];supplied=selected['tool_calls'][0]
            assert call['name']==supplied['name'] and call['arguments']==supplied['arguments']
            recorded=next(r for r in report['calls'] if r['turn']==row['turn'])
            assert recorded['request']==call
            actual=messages[len(history)];assert actual==recorded['response']
            assert actual['id']==call['id'] and actual['requestor']=='assistant'
            history.append(actual)
        policy_turns.append({'turn':row['turn'],'role':row['role'],
            'request_bytes':len(json.dumps(packet,ensure_ascii=False).encode()),
            'message_chars':len(selected['content'] or ''),'tool_calls':len(selected['tool_calls'])})
    assert history==messages
    assert len({r['request']['id'] for r in report['calls']})==len(report['calls'])
    store=Store(report['database']);latest=store.get(report['run_id'],raw=True)['run']
    expected=normalize(document,'tau-bench',{'experiment':report['experiment']})[0]
    assert latest['events']==expected['events']
    assert all(not e['source_pointer'].startswith('/task') for e in latest['events'])
    for prefix in report['prefixes']:
        saved=store.get(prefix['run_id'],raw=True)['run']
        assert saved['raw']['simulation']['messages']==messages[:prefix['messages']]
        if prefix['state']=='in_progress':assert saved['outcome']['recorded_reward'] is None
        native_feedback=sum(m['role']=='tool' for m in messages[:prefix['messages']])
        assert len({r['feedback_id'] for r in links(saved)['records']})==native_feedback
    link=links(latest)
    bound={r['feedback_id'] for r in link['records']}
    assert len(bound)==len(report['calls'])
    data=Workspace(store.path,experiment=report['experiment'],observer='source')
    graphs=data.graphs().rows;assert len(graphs)==1
    graph=graph_store.read(store,graphs[0]['graph_id']);graph_store.validate(graph)
    assert graph['counts']['unresolved_endpoints']==0
    source_metrics={r['metric']:r for r in data.metrics(limit=1000).rows}
    error=source_metrics['environment_tool_error_fraction']
    assert error['denominator']==len(report['calls'])
    assert error['numerator']==sum(c['response']['error'] for c in report['calls'])
    assert latest['metadata'].get('training_step') is None
    result={'schema':'adaptive-native-audit/1','status':'passed','run_id':latest['id'],
        'runtime':{'package':str(Path(sys.modules['rilldex'].__file__).resolve()),'isolated':bool(sys.flags.isolated)},
        'policy_turns':policy_turns,'fresh_policy_messages':len(policy_turns),'native_tool_calls':len(report['calls']),
        'state_changes':sum(c['before']!=c['after'] for c in report['calls']),
        'published_revisions':len(report['prefixes']),'tool_error_metric':error,
        'request_prefixes_match':True,'private_customer_state_excluded_from_agent':True,
        'tool_feedback_excluded_from_customer':True,'graph_id':graph['id'],
        'recorded_reward':latest['outcome']['recorded_reward'],
        'limits':{'model':'Fresh Luna subagent responses; usage counters not exposed; no claim of zero cost.',
            'accuracy':'Native capture/visibility/integrity only; no independent semantic reference.',
            'benchmark':'Custom file-handoff policies and customer prompt, native environment and deterministic evaluators. Not an official tau2 benchmark score.',
            'training':'Single adaptive development case, no optimizer or distributed scheduling.'}}
    if sys.flags.isolated:assert 'site-packages' in result['runtime']['package']
    h.write(output,result)
    return {k:result[k] for k in ('status','run_id','fresh_policy_messages','native_tool_calls','state_changes',
        'published_revisions','recorded_reward','request_prefixes_match','limits')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(audit(args.root,args.output),indent=2))
