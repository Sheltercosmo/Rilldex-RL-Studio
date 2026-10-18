'use strict';
const CustomMonitorSetup=(()=>{
 const literal=value=>JSON.stringify(String(value));
 function script({database,name,observer,experiment,version,description,group,template,rewardDefinition,definitionPath,rewardPath,checkPath,subjectPath,threshold,direction,rewardProducer,checkProducer}){
  const scope=[literal(database||'workspace.sqlite'),`observer=${literal(observer||'source')}`];
  if(experiment)scope.push(`experiment=${literal(experiment)}`);
  if(template==='reward')return rewardScript({scope,name,version,description,rewardDefinition,definitionPath,rewardPath,checkPath,subjectPath,threshold,direction});
  if(template==='evaluations')return evaluationScript({scope,name,version,description,rewardDefinition,definitionPath,rewardProducer,checkProducer});
  return `from rilldex import Workspace

ws = Workspace(${scope.join(', ')})
monitor = ws.monitor(
    ${literal(name||'My custom monitor')},
    version=${literal(version||'1')},
    description=${literal(description||'Count recorded agent actions; replace measure() with your analysis.')},
    unit="value", aggregation="mean", group=${literal(group||'Behavior')},
)

def measure(ctx):
    # Replace this example with your own analysis. ctx.graph contains typed
    # nodes and edges; ctx.workspace provides SQL and built-in analysis functions.
    actions = [e for e in ctx.run["events"]
               if e["kind"] == "action" and e["actor"] == "agent"
               and not e.get("copied_context")]
    return {
        "value": len(actions),
        "evidence_ids": ["event:" + e["id"] for e in actions],
        "feedback": {
            "severity": "info",  # info, warning, or critical
            "summary": f"{len(actions)} recorded agent actions",
            "next_check": "Open the linked rollout to inspect these actions.",
        },
        "details": {"action_count": len(actions)},
    }

if __name__ == "__main__":
    # Change this revision when callback logic or external inputs change.
    dependencies = {"code_revision": "v1"}
    print(monitor.run(measure, dependencies=dependencies))  # existing rollouts
    monitor.follow(measure, interval=5, dependencies=dependencies)  # new arrivals
`;
 }
 function rewardScript({scope,name,version,description,rewardDefinition,definitionPath,rewardPath,checkPath,subjectPath,threshold,direction}){
  const cutoff=Number(threshold??1);if(!Number.isFinite(cutoff)||(typeof threshold==='string'&&!threshold.trim()))throw Error('Use a finite reward threshold');
  return `import math
from rilldex import Workspace

ws = Workspace(${scope.join(', ')})
monitor = ws.reward_detector(
    ${literal(name||'Reward / check disagreement')}, version=${literal(version||'1')},
    description=${literal(description||'Reward crosses the configured threshold while a matched recorded check fails.')},
    reward_definition=${literal(rewardDefinition||'my-reward/v1')},
    definition_path=${literal(definitionPath||'/metadata/reward_definition')}, stage="reward_disagreement",
    inputs={
        "reward": ${literal(rewardPath||'/outcome/recorded_reward')},
        "check": ${literal(checkPath||'/raw/independent_check')},
        "subject": ${literal(subjectPath||'/raw/evaluation_subject')},
    },
    config={"threshold": ${cutoff}, "direction": ${literal(direction==='le'?'le':'ge')}},
)

def detect(ctx):
    # Adapt this function for your reward: rules, local models or an API.
    # Missing inputs / a different reward definition are handled before this call.
    reward, check, subject = (ctx.inputs[k] for k in ("reward", "check", "subject"))
    if type(reward) not in (int, float) or not math.isfinite(reward):
        return {"status": "unknown", "summary": "Reward is not a finite scalar."}
    if not isinstance(subject, str) or not subject.strip() or not isinstance(check, dict):
        return {"status": "unknown", "summary": "A versioned subject ID and check record are required."}
    if (check.get("subject_id") != subject or
            check.get("reward_definition") != ctx.reward_definition or
            type(check.get("passed")) is not bool):
        return {"status": "unknown", "summary": "Check does not match this subject and reward definition."}
    eligible = (reward >= ctx.config["threshold"] if ctx.config["direction"] == "ge"
                else reward <= ctx.config["threshold"])
    if not eligible:
        return {"status": "not_applicable", "summary": "Reward is outside the configured comparison range."}
    flagged = not check["passed"]
    return {
        "status": "flagged" if flagged else "clear",
        "summary": "Reward / check disagreement." if flagged else "Matched check passed.",
        "input_evidence": ["reward", "check", "subject"],
        "next_check": "Inspect the matched check and source; disagreement alone does not prove reward hacking.",
    }

if __name__ == "__main__":
    # Change version/config when the rule changes. Revision external inputs in
    # dependencies; unchanged source/graph/dependencies are reused on restart.
    dependencies = {"code_revision": "v1"}
    print(monitor.run(detect, dependencies=dependencies))
    monitor.follow(detect, interval=5, dependencies=dependencies)
`;
 }
 function evaluationScript({scope,name,version,description,rewardDefinition,definitionPath,rewardProducer,checkProducer}){
  const selector=(purpose,producer)=>'{"purpose": '+literal(purpose)+(producer?.trim()?', "producer": '+literal(producer.trim()):'')+'}';
  return `from rilldex import Workspace

ws = Workspace(${scope.join(', ')})
monitor = ws.reward_detector(
    ${literal(name||'Reward / evaluator disagreement')}, version=${literal(version||'1')},
    description=${literal(description||'Reward and independent-check verdicts disagree on matching task, criterion, artifact and output inputs.')},
    reward_definition=${literal(rewardDefinition||'my-reward/v1')},
    definition_path=${literal(definitionPath||'/metadata/reward_definition')}, stage="reward_disagreement",
    inputs={"definition": ${literal(definitionPath||'/metadata/reward_definition')}},
    evaluations={
        "reward": ${selector('reward',rewardProducer)},
        "check": ${selector('independent_check',checkProducer)},
    },
)

def detect(ctx):
    # Selectors return all matching reports for this exact source revision.
    # Add label, criterion_sha256 or evaluator_sha256 filters when needed.
    comparison = ctx.compare_evaluations("reward", "check")
    status = comparison["status"]
    summaries = {
        "agreement": "The reward evaluation and selected check report the same verdict.",
        "disagreement": "The reward evaluation and selected check disagree on matching inputs.",
        "missing_reports": "Waiting for both evaluator reports.",
        "ambiguous_reports": "Multiple reports match an input; narrow the evaluator selectors.",
        "same_report": "Both inputs select the same report.",
        "different_inputs": "The reports evaluated different task, criterion, artifact or output inputs.",
        "missing_inputs": "The reports lack input revisions needed for comparison.",
        "execution_error": "An evaluator reported an execution error.",
        "unresolved": "An evaluator is unfinished or its verdict is unknown.",
    }
    ids = sorted({r["id"] for rows in ctx.evaluations.values() for r in rows})
    return {
        "status": "flagged" if status == "disagreement" else "clear" if status == "agreement" else "unknown",
        "summary": summaries.get(status, "Comparison unresolved: " + status),
        "evaluation_ids": ids[:32],  # The input receipt retains every selected ID.
        "details": {"comparison": comparison},
        "next_check": "Open the cited reports. A disagreement identifies a review case, not a confirmed exploit.",
    }

if __name__ == "__main__":
    # Declared evaluator inputs are tracked automatically, including late reports.
    # Version code changes; add explicit revisions for other external data.
    dependencies = {"code_revision": "v1"}
    print(monitor.run(detect, dependencies=dependencies))
    monitor.follow(detect, interval=5, dependencies=dependencies)
`;
 }
 return {script};
})();
if(typeof module!=='undefined')module.exports=CustomMonitorSetup;
