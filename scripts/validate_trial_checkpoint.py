"""Native CPU PPO checkpoint branching through the installed trial workflow.

Run with stable-baselines3 installed and --output pointing to a new directory.
This validates execution and capture, not the efficacy of an RL intervention.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path


def validate(root):
    import torch
    import stable_baselines3
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.evaluation import evaluate_policy
    from rilldex import Run, TrialStudy
    from tracker import failure_investigations, investigation_followups, monitoring, telemetry_queries
    from tracker.store import Store

    root.mkdir(parents=True, exist_ok=False)
    db=root/'study.sqlite'; store=Store(db)
    torch.set_num_threads(1)

    def sources(experiment):
        with store.connect() as c:
            rows=c.execute("""SELECT DISTINCT r.document FROM runs r
                JOIN rollout_revisions v ON r.id=v.run_id
                WHERE json_extract(r.document,'$.metadata.experiment')=? AND v.state='complete'""",
                (experiment,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    checkpoint=root/'base.zip'
    with Run('base',project='checkpoint-controls',workspace=db,hardware=False,capture_console=False) as run:
        capture=run.stable_baselines(publish_every=32)
        env=capture.wrap_env(make_vec_env('CartPole-v1',n_envs=1,seed=31))
        try:
            base=PPO('MlpPolicy',env,n_steps=32,batch_size=32,n_epochs=1,learning_rate=.0003,
                     policy_kwargs=dict(net_arch=[16,16]),seed=31,device='cpu')
            base.learn(256,callback=capture.callback())
            base.save(checkpoint)
            initial_weights=deepcopy(base.policy.state_dict())
            initial_optimizer=deepcopy(base.policy.optimizer.state_dict())
            run.add_file(checkpoint)
        finally:env.close()
    original=sources('checkpoint-controls/base')[0]
    snap=failure_investigations.snapshot(store,run=original['id'])
    original_doc=failure_investigations.save(store,dict(controls=snap['controls'],snapshot_id=snap['snapshot_id'],
        title='Branch from a PPO checkpoint',hypothesis='Lower learning rate may affect held-out episode return',
        x='source:actions',y='source:recorded_reward'))
    design=dict(mode='train',run_id=original['id'],through_event_id=original['events'][-1]['id'],
        configuration=dict(values=dict(learning_rate=.0003)),
        checkpoint=dict(reference=str(checkpoint),available_state=['model','optimizer'],
                        reset_state=['scheduler','rng','data','environment']),
        variants=[dict(name='Lower learning rate',parameters=dict(learning_rate=.00003))],
        seeds=[7,19],budget=dict(max_trials=4,max_steps=128,max_tokens=1),
        measure=dict(key='eval_return',label='Held-out CartPole return',unit='reward'))
    prepared=investigation_followups.save(store,dict(parent_id=original_doc['id'],action='plan',check=dict(
        title='Learning rate control',hypothesis=original_doc['hypothesis'],procedure='Load the same model and optimizer; collect fresh seeded episodes.',
        expected_result='Measure return without assuming a direction.',trial=design)))
    check=prepared['follow_up']['checks'][0]
    study=TrialStudy.from_investigation(db,prepared['id'],check['id'])
    (root/'trial.json').write_text(json.dumps(study.manifest,indent=2),encoding='utf-8')
    executed=[]

    def runner(job):
        name=('reference' if job['arm']=='Reference' else 'lower-lr')+'-'+str(job['seed'])
        with Run(name,project='checkpoint-controls',workspace=db,hardware=False,capture_console=False,
                 config=dict(trial_job_id=job['id'],seed=job['seed'])) as run:
            capture=run.stable_baselines(publish_every=32)
            env=capture.wrap_env(make_vec_env('CartPole-v1',n_envs=1,seed=job['seed']))
            try:
                model=PPO.load(job['checkpoint']['reference'],env=env,device='cpu',
                               learning_rate=job['configuration']['learning_rate'],seed=job['seed'])
                for key,value in model.policy.state_dict().items():assert torch.equal(value,initial_weights[key]),key
                restored=model.policy.optimizer.state_dict()
                assert restored['param_groups']==initial_optimizer['param_groups']
                for key,values in initial_optimizer['state'].items():
                    for part,value in values.items():assert torch.equal(restored['state'][key][part],value),(key,part)
                model.set_random_seed(job['seed'])
                before=model.num_timesteps
                assert before==256
                model.learn(job['budget']['max_steps'],reset_num_timesteps=False,callback=capture.callback())
                assert model.num_timesteps-before==job['budget']['max_steps']
                actual_lr=float(model.policy.optimizer.param_groups[0]['lr'])
                assert actual_lr==job['configuration']['learning_rate']
                evaluation=make_vec_env('CartPole-v1',n_envs=1,seed=1000+job['seed'])
                try:score,_=evaluate_policy(model,evaluation,n_eval_episodes=4,deterministic=True)
                finally:evaluation.close()
                model.save(root/(name+'.zip'))
                run.add_file(root/(name+'.zip'))
                run.log_config(dict(learning_rate=actual_lr,trial_job_id=job['id'],seed=model.seed))
            finally:env.close()
        ids=[r['id'] for r in sources(run.experiment)]
        assert ids
        telemetry=telemetry_queries.query(store,experiment=run.experiment)
        assert telemetry['records']==4 and telemetry['clock']=='environment_timesteps'
        executed.append(dict(job_id=job['id'],experiment=run.experiment,transitions=128,eval_episodes=4,
                             rollouts=len(ids),native_logs=telemetry['records']))
        return dict(status='completed',metrics=dict(eval_return=float(score)),experiment=run.experiment,rollout_ids=ids,
            applied=dict(configuration=dict(learning_rate=actual_lr),context_append='',seed=model.seed,
                         checkpoint_reference=str(checkpoint),restored_state=['model','optimizer'],
                         reset_state=['scheduler','rng','data','environment']))

    # Interrupt between jobs, then reopen the serialized design and resume.
    def interrupted(job):
        if len(executed)==1:raise KeyboardInterrupt()
        return runner(job)
    output=root/'trial-results.json'
    try:study.run(interrupted,output=output)
    except KeyboardInterrupt:pass
    assert len(json.loads(output.read_text())['results'])==1
    study=TrialStudy.load(root/'trial.json')
    result=study.run(runner,output=output)
    assert len(executed)==len({j['job_id'] for j in executed})==4
    study.run(lambda _: (_ for _ in ()).throw(AssertionError('Completed trial reran')),output=output)
    assert result['comparison']['contrasts'][0]['paired']==2
    assert all(not row['issues'] for row in result['comparison']['rows'])
    saved=study.record_results(db,result)
    monitor=monitoring.create(store,dict(name='Training episode return',kind='metric',metric='recorded_reward',observer='source'))
    monitoring.sync(store)
    comparison=study.compare_behavior(db,investigation_id=saved['id'],arm='Lower learning rate',monitor_ids=[monitor['id']])
    assert all(comparison['snapshot']['population'].values())
    assert comparison['snapshot']['trial_selection']['seeds']==[7,19]
    assert failure_investigations.read(store,original_doc['id'])==original_doc
    result=dict(framework='stable-baselines3',version=stable_baselines3.__version__,environment='CartPole-v1',device='cpu',
        initial_transitions=256,branch_transitions=512,evaluation_episodes=16,executed=executed,
        comparison=result['comparison']['contrasts'],investigation=saved['id'],behavior_comparison=comparison['id'],
        provider_calls=0,checks=['identical restored model and optimizer','actual learning rate applied',
        'fresh environment and paired seeds','step budget respected','interruption and restart without duplicate jobs',
        'native telemetry and completed episodes','returned rollout comparison','original evidence unchanged'],
        limits='Small native CPU workflow validation. No claim of learning improvement or LLM/RL framework parity.')
    (root/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    validate(parser.parse_args().output.resolve())
