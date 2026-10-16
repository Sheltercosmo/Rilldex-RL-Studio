/* Bind a saved measurement case to its original plan evidence, without inference. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PlanCaseContext=api;})(typeof window==='undefined'?this:window,()=>{
 'use strict';
 function resolve(graph,record){
  if(!record||(!record.plan_declaration&&!record.declared_plan_change))return null;
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),event=id=>nodes.get('event:'+id);
  const snapshots=[],items=[],events=[];
  if(record.plan_declaration){const s=record.plan_declaration;snapshots.push(s.id);events.push(s.event_id);if(record.initial_item)items.push(record.initial_item.id);}
  else{const c=record.declared_plan_change;snapshots.push(c.previous_id,c.current_id);events.push(...c.event_ids);items.push(c.before.id);if(c.after)items.push(c.after.id);for(const candidate of c.candidates||[])items.push(candidate.id);}
  for(const id of snapshots)if(nodes.get(id)?.kind!=='declared_plan_snapshot')throw Error('The saved case refers to a task list outside this graph.');
  for(const id of items)if(nodes.get(id)?.kind!=='declared_plan_item')throw Error('The saved case refers to an item outside this graph.');
  if(!events.length||events.some(id=>!event(id)||event(id).event_index==null))throw Error('The saved case has no complete recorded cutoff.');
  const witnessedEvents=new Set(snapshots.map(id=>nodes.get(id).properties.event_id));
  if(events.some(id=>!witnessedEvents.has(id))||[...witnessedEvents].some(id=>!events.includes(id)))throw Error('The saved case cutoff differs from its witnessed declarations.');
  const lanes=new Set(snapshots.map(id=>{const n=nodes.get(id),p=n.properties;return JSON.stringify([n.trajectory_id,p.actor,p.context_id,p.profile]);}));
  // Profile changes are valid unresolved cases. Do not pretend they are one persistent list.
  for(const id of items)if(!snapshots.some(sid=>nodes.get(sid).properties.items.some(i=>i.id===id)))throw Error('The measured item is not in the witnessed declarations.');
  const cutoff=[...events].sort((a,b)=>event(a).event_index-event(b).event_index).at(-1);
  const state=s=>({completed:'reported complete',active:'reported in progress',pending:'reported pending'}[s]||'reported state unknown');
  const change=record.declared_plan_change;
  return {case_id:record.id,graph_id:graph.id,label:record.label,status:record.status,taken:record.taken,
   cutoff_event_id:cutoff,cutoff_event_index:event(cutoff).event_index,
   item_ids:[...new Set(items)],snapshot_ids:[...new Set(snapshots)],event_ids:[...new Set(events)],
   scope:change?'adjacent declarations':record.initial_item?'initial captured item':'issued task list',
   summary:change?state(change.before.status)+' → '+(change.after?state(change.after.status):'item correspondence unresolved'):
     record.initial_item?state(record.initial_item.status):`${record.plan_declaration.items.length} recorded list entries`,
   reason:change?.reason||null,comparable_lanes:lanes.size===1};
 }
 function matches(node,context){return !!context&&(node.source_node_ids||[]).some(id=>(context.item_ids.length?context.item_ids:context.snapshot_ids).includes(id));}
 function rootFor(data,context){const matched=new Set(data.nodes.filter(n=>matches(n,context)).map(n=>n.id)),roots=data.roots.filter(id=>matched.has(id)||data.links.some(e=>e.source===id&&e.type==='contains'&&matched.has(e.target)));return roots.length>1?'all':roots[0]||null;}
 function monitorUrl(receipt){if(!receipt?.monitor?.id)return null;const m=receipt.run?.metadata||{};return '/?'+new URLSearchParams({monitor:receipt.monitor.id,experiment:m.experiment||'__unassigned__',environment:m.environment||''});}
 return {resolve,matches,rootFor,monitorUrl};
});
