'use strict';
const CustomMonitorSetup=(()=>{
 const literal=value=>JSON.stringify(String(value));
 function script({database,name,observer,experiment,version,description,group}){
  const scope=[literal(database||'workspace.sqlite'),`observer=${literal(observer||'source')}`];
  if(experiment)scope.push(`experiment=${literal(experiment)}`);
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
 return {script};
})();
if(typeof module!=='undefined')module.exports=CustomMonitorSetup;
