'use strict';

window.trackerComparison = (() => {
  const $ = selector => document.querySelector(selector);
  const modes = ['explore','apply','verify','coordinate','report','unresolved'];
  const labels = {explore:'Explore',apply:'Apply approach',verify:'Verify',coordinate:'Coordinate',report:'Report',unresolved:'Unresolved'};
  const short = {explore:'Explore',apply:'Apply',verify:'Verify',coordinate:'Coord.',report:'Report',unresolved:'Unres.'};
  const selectors = {experiment:'#compare-experiment',environment:'#compare-environment',environment_version:'#compare-environment-version',
    split:'#compare-split',inspector_signature:'#compare-inspector',sampling_hash:'#compare-sampling'};
  let runs=[], query=new URLSearchParams(), renderGeneration=0, evidenceGeneration=0;
  const node = (tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const format = (value,count=false,delta=false) => value===null?'No opportunity':`${delta&&value>0?'+':''}${(value*(count?1:100)).toFixed(1)} ${count?'actions':delta?'pp':'%'}`;
  function metricLabel(metric) {
    const [family,value,target]=metric.split('.');
    if(family==='transition')return `${labels[value]} → ${labels[target]}`;
    if(family==='purpose')return `Purpose: ${labels[value]}`;
    if(family==='task_relation')return `Task relation: ${value.replaceAll('_',' ')}`;
    if(family==='feedback')return `Response to feedback: ${value.replaceAll('_',' ')}`;
    return {repeat_rate:'Exact repeat rate',action_count:'Actions per rollout',goal_assignment_rate:'Goal assignment coverage'}[metric]||metric;
  }
  const fieldValue=(row,key)=>['inspector_signature','sampling_hash'].includes(key)?row[key]:row.metadata[key];
  async function request(url) {const r=await fetch(url);const data=await r.json();if(!r.ok)throw Error(data.error||'Could not load comparison');return data;}
  function fill(select, entries, label, auto=true) {
    const previous=select.value;select.replaceChildren(new Option(label,''),...entries.map(([value,text])=>new Option(text,value)));
    select.value=entries.some(([v])=>v===previous)?previous:auto&&entries.length===1?entries[0][0]:'';
  }
  function values(rows,key,labeler) {
    const found=new Map();for(const r of rows){const value=fieldValue(r,key);if(value)found.set(value,labeler?labeler(r):String(value));}
    return [...found].sort((a,b)=>a[1].localeCompare(b[1]));
  }
  function selectedRows(onlyPrimary=false) {
    return runs.filter(r=>Object.entries(selectors).every(([key,selector])=>
      onlyPrimary&&!['experiment','environment'].includes(key)||!$(selector).value||fieldValue(r,key)===$(selector).value));
  }
  function fillCohort() {
    const primary=selectedRows(true);
    fill($('#compare-environment-version'),values(primary,'environment_version'),'All environment versions');
    fill($('#compare-split'),values(primary,'split'),'All splits');
    fill($('#compare-inspector'),values(primary,'inspector_signature',r=>r.inspector_signature==='heuristic'?'Command/tool rules':
      r.inspector_profiles?.map(p=>`${p[0]} · ${p[1]} · selection ${p[2]}`).join('; ')||r.inspector_signature),'All observer profiles');
    fill($('#compare-sampling'),values(primary,'sampling_hash',r=>Object.keys(r.metadata.sampling||{}).length?JSON.stringify(r.metadata.sampling):'Sampling not recorded'),'All sampling settings');
    fillCheckpoints();
  }
  function fillCheckpoints() {
    const rows=selectedRows(), checkpoints=values(rows,'checkpoint');
    const box=$('#compare-checkpoints');box.replaceChildren(node('legend','Included policy checkpoints'));
    for(const [value] of checkpoints){
      const label=node('label'), input=node('input');input.type='checkbox';input.value=value;input.checked=true;
      input.addEventListener('change',()=>{fillReference();refresh();});
      const steps=[...new Set(rows.filter(r=>r.metadata.checkpoint===value).map(r=>r.metadata.training_step))];
      label.append(input,document.createTextNode(value+(steps.length===1&&steps[0]!==undefined&&steps[0]!==null?` · policy step ${steps[0]}`:'')));box.append(label);
    }
    fillReference();
  }
  function fillReference() {
    const included=[...$('#compare-checkpoints').querySelectorAll('input:checked')].map(n=>[n.value,n.value]);
    fill($('#compare-reference'),included,'Earliest recorded step, otherwise alphabetical',false);
  }
  function controlsQuery() {
    const params=new URLSearchParams();for(const [key,selector] of Object.entries(selectors))if($(selector).value)params.set(key,$(selector).value);
    for(const checkbox of $('#compare-checkpoints').querySelectorAll('input:checked'))params.append('checkpoints',checkbox.value);
    if($('#compare-reference').value)params.set('reference',$('#compare-reference').value);
    return params;
  }
  async function refresh() {
    const generation=++renderGeneration;++evidenceGeneration;
    $('#comparison-evidence').hidden=true;const div=$('#comparison');div.replaceChildren(node('p','Loading matched observations…','compare-details'));
    const params=controlsQuery();
    if(params.getAll('checkpoints').length<2){div.replaceChildren(node('p','At least two policy checkpoints with recorded provenance must be selected.','compare-empty'));return;}
    try {
      const result=await request('/api/compare?'+params);if(generation!==renderGeneration)return;query=params;
      div.replaceChildren();
      if(result.status!=='ok'){
        div.append(node('p',result.message,'compare-empty'),node('p',`${result.excluded.length} rollouts excluded. ${[...new Set(result.excluded.map(r=>r.reason))].join('; ')}`,'compare-details'));return;
      }
      div.append(node('p',result.definition,'compare-details'));
      const coverage=result.selection;
      if(coverage)div.append(node('p',`${coverage.selected_rollouts} of ${coverage.imported_rollouts} imported rollouts selected; ${coverage.matched_rollouts} retained across ${result.matched_tasks.length} matched tasks. Imported rollouts are not necessarily the full training population.`,'compare-details'));
      for(const cp of result.checkpoints){
        const row=node('div',undefined,'comparison-row'),label=node('div',undefined,'comparison-label');
        label.append(node('b',cp.checkpoint),node('span',`${cp.task_count} tasks · ${cp.rollout_count} rollouts`));
        const stack=node('div',undefined,'stack');
        for(const mode of modes){const segment=node('span');segment.style.width=(cp.modes[mode]*100)+'%';segment.style.background=`var(--${mode})`;segment.title=`${labels[mode]}: ${format(cp.modes[mode])}`;segment.setAttribute('aria-label',segment.title);stack.append(segment);}
        row.append(label,stack,node('p',modes.filter(m=>cp.modes[m]>0).map(m=>`${labels[m]} ${format(cp.modes[m])}`).join(' · '),'compare-details'),
          node('p',`Exact repeat rate ${format(cp.repeat_rate)} · Mean actions ${cp.action_count.toFixed(1)}`,'compare-details'));div.append(row);
      }
      window.trackerDetails.comparison(div,result);
      div.append(node('p',result.limitations.join(' '),'compare-details'));
    }catch(error){if(generation===renderGeneration)div.replaceChildren(node('p',error.message,'error'));}
  }
  function flow(panel,result,pair) {
    const section=node('section',undefined,'transition-section');
    section.append(node('h3','How the work sequence changed'));
    const data=pair.sequence;
    if(!data?.task_ids.length){section.append(node('p','No paired tasks have observable adjacent actions at both checkpoints. Reindex older imports if sequence coverage is absent.','compare-details'));panel.append(section);return;}
    section.append(node('p',`Same six purposes, measured in order. ${data.task_ids.length} paired tasks; ${data.excluded_task_ids.length} excluded because at least one checkpoint has no observable sequence.`,'compare-details'));
    const label=node('label','Transition view '),view=node('select');view.setAttribute('aria-label',`Transition view for ${pair.checkpoint}`);
    for(const [value,text] of [['delta','Change (percentage points)'],['before',`${pair.reference} share (%)`],['after',`${pair.checkpoint} share (%)`]])view.add(new Option(text,value));
    label.append(view);section.append(label,node('p','Rows: previous purpose. Columns: next purpose. Click a cell to inspect contributing tasks.','matrix-instructions'));
    const matrix=node('div',undefined,'transition-matrix');matrix.setAttribute('role','group');matrix.setAttribute('aria-label',`Purpose transitions: ${pair.checkpoint} compared with ${pair.reference}`);
    const render=()=>{
      matrix.replaceChildren(node('span','From ↓ / To →','matrix-axis'));
      for(const mode of modes){const h=node('span',short[mode],'matrix-label');h.title=labels[mode];matrix.append(h);}
      for(const source of modes){
        const h=node('strong',short[source],'matrix-label');h.title=labels[source];matrix.append(h);
        for(const target of modes){
          const key=source+'.'+target,metric=pair.metrics['transition.'+key],value=view.value==='delta'?metric.delta:data[view.value][key];
          const cell=node('button',(value>0&&view.value==='delta'?'+':'')+(value*100).toFixed(1),'transition-cell');
          cell.type='button';cell.dataset.transition=key;
          cell.setAttribute('aria-label',`${labels[source]} to ${labels[target]}: ${format(value,false,view.value==='delta')}`);
          cell.title=`${labels[source]} → ${labels[target]} · ${format(value,false,view.value==='delta')} · ${metric.task_count} paired tasks`;
          const color=view.value==='delta'&&value<0?'108,74,157':'37,104,154';cell.style.background=`rgba(${color},${Math.abs(value)===0?0:Math.min(.35,.08+Math.abs(value)*.4)})`;
          cell.addEventListener('click',()=>inspect(result,pair,'transition.'+key));matrix.append(cell);
        }
      }
    };
    view.addEventListener('change',render);render();section.append(matrix);
    section.append(node('p','Each cell is a share of all observed adjacent pairs, averaged within tasks. Change colors: blue for increases and purple for decreases; neither means better. Unresolved purpose stays visible.','compare-details'));
    const coverage=node('details');coverage.append(node('summary','Sequence coverage and interpretation'),node('p',data.definition,'compare-details'));
    for(const [side,cp] of [['before',pair.reference],['after',pair.checkpoint]]){const c=data.coverage[side];coverage.append(node('p',`${cp}: ${c.observed_pairs}/${c.possible_pairs} adjacent pairs observed; ${c.excluded_batch_pairs} excluded at tool batches; ${c.unresolved_pairs} involve unresolved purpose. ${c.eligible_rollouts}/${c.total_rollouts} rollouts in these tasks have sequence opportunities.`,'compare-details'));}
    if(data.excluded_task_ids.length)coverage.append(node('p','Excluded tasks: '+data.excluded_task_ids.join(', '),'source-ref'));
    section.append(coverage);panel.append(section);
  }
  async function inspect(result,pair,metric,selection={}) {
    const generation=++evidenceGeneration;
    const container=$('#comparison-evidence');container.hidden=false;container.replaceChildren(node('p','Loading task and action evidence…','compare-details'));
    const params=new URLSearchParams(query);params.set('comparison_id',result.comparison_id);params.set('metric',metric);params.set('reference',pair.reference);params.set('checkpoint',pair.checkpoint);
    for(const [key,value] of Object.entries(selection))if(value)params.set(key,value);
    try {
      const data=await request('/api/compare/evidence?'+params);if(generation!==evidenceGeneration)return;
      renderEvidence(container,data,result,pair,metric);
      container.scrollIntoView({block:'start',behavior:'instant'});
    }catch(error){
      if(generation!==evidenceGeneration)return;container.replaceChildren(node('p',error.message,'error'));
      const reload=node('button','Refresh comparison');reload.addEventListener('click',refresh);container.append(reload);
    }
  }
  function renderEvidence(container,data,result,pair,metric) {
    const count=metric==='action_count';container.replaceChildren(node('h3','Evidence behind this change'));
    container.append(node('p',`${metricLabel(metric)} · ${format(data.aggregate.delta,count,true)} · ${data.aggregate.task_count} paired tasks`,'evidence-change'));
    const interval=data.aggregate.interval_95;
    container.append(node('p',interval?`Pointwise 95% interval: ${format(interval[0],count,true)} to ${format(interval[1],count,true)}.`:'Interval unavailable: fewer than five paired tasks.','compare-details'));
    const label=node('label','Matched task '),task=node('select');task.setAttribute('aria-label','Evidence task');
    for(const item of data.tasks)task.add(new Option(`${item.task_id} · ${format(item.delta,count,true)}`,item.task_id));task.value=data.task_id;
    task.addEventListener('change',()=>inspect(result,pair,metric,{task_id:task.value}));label.append(task);
    container.append(label,node('p','Tasks are ordered by absolute observed change for inspection. This is not a significance ranking.','compare-details'));
    const contributions=node('details');contributions.append(node('summary',`All ${data.tasks.length} paired task contributions`));
    const table=node('table',undefined,'contribution-table'),head=node('tr');
    for(const text of ['Task','Reference','Compared','Contribution to mean'])head.append(node('th',text));
    table.append(head);for(const item of data.tasks){const tr=node('tr');for(const text of [item.task_id,format(item.before,count),format(item.after,count),format(item.contribution_to_mean,count,true)])tr.append(node('td',text));table.append(tr);}
    contributions.append(table,node('p',data.definition,'compare-details'));container.append(contributions);
    const columns=node('div',undefined,'comparison-evidence-columns');
    for(const side of ['before','after']){
      const column=data[side],section=node('section',undefined,'comparison-evidence-column');section.append(node('h4',column.checkpoint));
      const choose=node('label',`${column.rollouts.length} rollout${column.rollouts.length===1?'':'s'} for this task`),select=node('select');select.setAttribute('aria-label',`${side} evidence rollout`);
      for(const r of column.rollouts)select.add(new Option(`${r.id.slice(0,8)} · ${r.numerator}/${r.denominator} · ${format(r.value,count)}${r.seed?` · seed ${r.seed}`:''}`,r.id));select.value=column.selected_run.id;
      select.addEventListener('change',()=>inspect(result,pair,metric,{task_id:data.task_id,before_run:side==='before'?select.value:data.before.selected_run.id,after_run:side==='after'?select.value:data.after.selected_run.id}));choose.append(select);section.append(choose);
      const units=metric.startsWith('transition.')?'eligible adjacent pairs':metric.startsWith('feedback.')?'feedback opportunities':'recorded actions';
      const selected=column.selected_run;
      section.append(node('p',count?`${selected.numerator} recorded actions.`:`${selected.numerator} matches / ${selected.denominator} ${units} · ${format(selected.value)}`,'compare-details'));
      const open=node('button','Open full rollout');open.addEventListener('click',()=>openRun(column.selected_run.id));section.append(open);
      const outcome=column.verified_success===true?'Dataset task success: true':column.verified_success===false?'Dataset task success: false':'Task success not recorded';
      section.append(node('p',`${outcome}${column.termination?` · Termination: ${column.termination}`:''}`,'compare-details'));
      if(column.rewards) section.append(node('p','Recorded rewards: '+JSON.stringify(column.rewards),'compare-details'));
      section.append(node('p',`${column.match_count} matching observations. ${column.preview_policy}`,'compare-details'));
      if(!column.selected_run.denominator)section.append(node('p','This rollout has no opportunity for the selected metric and does not enter its task rate.','compare-details'));
      else if(!column.match_count)section.append(node('p','No matching observation in this rollout. Inspect its other work with “Open full rollout”.','compare-details'));
      for(const match of column.matches){
        const sample=node('div',undefined,'comparison-sample');
        for(const event of match){
          const button=node('button',`${event.event_id} · ${labels[event.purpose]}`);button.addEventListener('click',()=>openRun(column.selected_run.id,event.event_id));
          sample.append(button,node('pre',event.text+(event.truncated?'\n… Preview shortened; open the action for full text.':'')),node('p',`${event.trajectory_id} · ${event.source_pointer} · ${event.basis}`,'source-ref'));
        }
        section.append(sample);
      }
      columns.append(section);
    }
    container.append(columns);
  }
  async function openRun(id,eventId) {
    try{await window.trackerInspectRun(id,eventId);$('#compare-dialog').close();$('#return-comparison').hidden=false;document.querySelector(eventId?'#evidence-section':'#run-title').scrollIntoView({block:'start',behavior:'instant'});}
    catch(error){$('#comparison-evidence').append(node('p',error.message,'error'));}
  }
  function open(nextRuns) {
    runs=nextRuns;
    fill($('#compare-experiment'),values(runs,'experiment'),'All experiments');
    const experiment=$('#compare-experiment').value;
    fill($('#compare-environment'),values(runs.filter(r=>!experiment||r.metadata.experiment===experiment),'environment'),'All environments');
    fillCohort();$('#compare-dialog').showModal();refresh();
  }
  $('#compare-experiment').addEventListener('change',()=>{
    const experiment=$('#compare-experiment').value;fill($('#compare-environment'),values(runs.filter(r=>!experiment||r.metadata.experiment===experiment),'environment'),'All environments');fillCohort();refresh();
  });
  $('#compare-environment').addEventListener('change',()=>{fillCohort();refresh();});
  for(const id of ['#compare-environment-version','#compare-split','#compare-inspector','#compare-sampling'])$(id).addEventListener('change',()=>{fillCheckpoints();refresh();});
  $('#compare-reference').addEventListener('change',refresh);
  $('#return-comparison').addEventListener('click',()=>$('#compare-dialog').showModal());
  return {open,flow,inspect};
})();
