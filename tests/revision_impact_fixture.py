"""Authored parser-repair control with native calls/check states, not a model run."""
from tracker.adapters import normalize
from tracker.schema import digest
from tracker import graph_store


def captured_revision():
    raw = dict(instance_id='revision-impact-control',problem_statement='Repair nested parsing without regressing existing expressions.',trajectory=[
        dict(thought='Plan: reproduce the failure, revise the parser, then verify original and nested expressions.',action='pytest tests/test_original.py',observation='1 failed in 0.1s'),
        dict(thought='Establish the nested-expression baseline.',action='pytest tests/test_nested.py',observation='1 passed in 0.1s'),
        dict(thought='The regex rejects valid parentheses. I will widen its match, then check both cases.',action='apply_patch parser.py regex_v2',observation='Applied patch'),
        dict(thought='Check the original failure.',action='pytest tests/test_original.py',observation='1 passed in 0.1s'),
        dict(thought='Check whether nested expressions still work.',action='pytest tests/test_nested.py',observation='1 failed in 0.1s'),
        dict(thought='The wider regex fixed one case but broke nesting. Replace it with a stack parser and rerun both checks.',action='apply_patch parser.py stack_v3',observation='Applied patch'),
        dict(thought='Check the original case after switching methods.',action='pytest tests/test_original.py',observation='1 passed in 0.1s'),
        dict(thought='Check nested expressions after switching methods.',action='pytest tests/test_nested.py',observation='1 passed in 0.1s')])
    run=normalize(raw,'swe-agent')[0]
    actions=[e for e in run['events'] if e['kind']=='action'];responses=[e for e in run['events'] if e['kind']=='feedback']
    thoughts=[e for e in run['events'] if e['actor']=='agent' and e['kind']!='action']
    def snapshot(name,eid,version):return dict(id=name,event_id=eid,environment='parser-tests/v1',objects={'parser.py':version,'tests':'suite-v1'})
    def check(i,criterion,result,state):return dict(action_id=actions[i]['id'],result_event_id=responses[i]['id'],criterion_id=criterion,
        criterion_version='v1',snapshot_id=state,required_objects=['parser.py','tests'],binding='at_dispatch',state_stable=True,result=result)
    raw['work_state']=dict(schema='work-state-capture/1',snapshots=[snapshot('before',actions[0]['id'],'v1'),snapshot('regex',responses[2]['id'],'v2'),snapshot('stack',responses[5]['id'],'v3')],
        checks=[check(0,'Original expressions','failed','before'),check(1,'Nested expressions','passed','before'),check(3,'Original expressions','passed','regex'),check(4,'Nested expressions','failed','regex'),check(6,'Original expressions','passed','stack'),check(7,'Nested expressions','passed','stack')],
        edits=[dict(action_id=actions[i]['id'],result_event_id=responses[i]['id'],before_snapshot_id=a,after_snapshot_id=b) for i,a,b in [(2,'before','regex'),(5,'regex','stack')]])
    run=normalize(raw,'swe-agent')[0]
    run['metadata'].update(experiment='Authored revision impact control',task_id='Parser revision: gains and regressions',training_step=1)
    run['id']=digest(run)[:24]
    units=[]
    for e in run['events']:
        if e['actor'] not in {'agent','environment'}:continue
        u=dict(id='u-'+e['id'],actor=e['actor'],kind='action' if e['kind']=='action' else 'feedback' if e['kind']=='feedback' else 'semantic',
            activity='construct' if e['kind']=='action' else 'orient',trajectory_id=e['trajectory_id'],source=dict(event_id=e['id'],start=0,end=len(e['text']),text=e['text'],source_pointer=e.get('source_pointer')),content={'target':{'text':e['text']}})
        units.append(u)
    plan=next(u for u in units if u['source']['event_id']==thoughts[0]['id']);plan['activity']='plan'
    plan['plan_structure']=dict(steps=[dict(id=k,text=label,target=label,evidence=[plan['source']]) for k,label in [('reproduce','Reproduce & baseline'),('repair','Revise the parser'),('verify','Check benefit & regression')]],links=[],completion_criterion={'status':'not_expressed'})
    relations=[]
    def rel(a,b,kind,**extra):relations.append(dict(**{'from':a,'to':b},type=kind,**extra))
    for i,a in enumerate(actions):
        rel('u-'+a['id'],plan['id'],'attempts_plan_step',plan_step_id='reproduce' if i<2 else 'repair' if i in (2,5) else 'verify')
        rel('u-'+responses[i]['id'],'u-'+a['id'],'feedback_for')
    for change,prior,retry in [(2,0,3),(5,4,7)]:
        statement='u-'+thoughts[change]['id']
        rel(statement,'u-'+actions[prior]['id'],'adjustment_before_retry',via_action='u-'+actions[change]['id'],retry_unit_id='u-'+actions[retry]['id'])
        rel(statement,'u-'+responses[prior]['id'],'assesses')
    graph=graph_store.build(run,dict(observer={'id':'authored-revision-impact','label':'Authored revision impact control'},document=dict(source_hash=digest(run),units=units,relations=relations)))
    graph['semantic_context']['operation_results']={a['id']:dict(outcome='failed' if i in (0,4) else 'completed',observations=[dict(response_event_id=responses[i]['id'])]) for i,a in enumerate(actions)}
    graph.pop('id');graph['id']='graph-'+digest(graph)
    return run,graph
