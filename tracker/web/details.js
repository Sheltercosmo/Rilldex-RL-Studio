'use strict';

// Evidence and review views are separate from the graph layout. Source strings
// only enter text nodes, including option descriptions and review notes.
window.trackerDetails = (() => {
  const $ = selector => document.querySelector(selector);
  let bundle = null;
  let selection = null;
  let requestSequence = 0;
  let reviewerLabel = '';
  const humanize = value => String(value).replaceAll('_', ' ');

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function actionButton(text, id, className = '') {
    const button = node('button', text, className);
    button.type = 'button';
    button.addEventListener('click', () => {
      window.trackerSelectAction(id);
      $('#evidence-section').scrollIntoView({block: 'start', behavior: 'instant'});
    });
    return button;
  }

  function goalName(id) {
    const goal = bundle?.analysis.goal_tracking?.goals.find(g => g.id === id);
    return goal ? goal.kind === 'recorded_objective' ? 'Initial task' : goal.text : humanize(id);
  }

  function goalLanes(tracking) {
    const lanes = new Map();
    const transitions = new Map(tracking.transitions.map(t => [t.event_id, t]));
    for (const assignment of tracking.assignments) {
      const laneKey = JSON.stringify([assignment.trajectory_id, assignment.context_id ?? null]);
      if (!lanes.has(laneKey)) lanes.set(laneKey, {trajectory_id: assignment.trajectory_id,
        context_id: assignment.context_id ?? null, segments: []});
      const segments = lanes.get(laneKey).segments;
      const key = assignment.goal_id || assignment.status;
      const transition = transitions.get(assignment.event_id);
      const last = segments.at(-1);
      if (last?.key === key && last.order_known && assignment.order_known === true &&
          transition?.kind === 'continue' && transition.previous_event_id === last.ids.at(-1)) {
        last.ids.push(assignment.event_id);
      } else segments.push({key, goal: assignment.goal_id, ids: [assignment.event_id],
        order_known: assignment.order_known === true});
    }
    return [...lanes.values()];
  }

  function renderGoals() {
    const tracking = bundle.analysis.goal_tracking;
    const container = $('#goal-tracking');
    container.replaceChildren();
    if (!tracking) {
      container.append(node('p', 'Reindex this run to enable goal tracking.', 'muted'));
      return;
    }
    const c = tracking.coverage;
    container.append(node('p', `${c.assigned} of ${c.eligible} actions have an assigned goal · ${c.pursued_plans} of ${c.plan_candidates} expressed plans have observed pursuit`, 'goal-coverage'));
    container.append(node('p', 'Goal focus follows action evidence. A mentioned plan is a candidate; pursuit does not establish completion. Gaps stay unresolved.', 'muted'));

    const transitions = new Map(tracking.transitions.map(t => [t.event_id, t.kind]));
    for (const {trajectory_id: actor, context_id, segments} of goalLanes(tracking)) {
      const lane = node('div', undefined, 'focus-lane');
      lane.append(node('h3', context_id === null ? actor : `${actor} · ${context_id}`));
      const sequence = node('div', undefined, 'focus-sequence');
      for (const segment of segments) {
        const label = segment.goal ? goalName(segment.goal) : humanize(segment.key);
        const kind = transitions.get(segment.ids[0]);
        const button = actionButton('', segment.ids[0], 'focus-segment' + (segment.goal && segment.order_known ? '' : ' uncertain'));
        button.append(node('span', label.length > 90 ? label.slice(0,87) + '…' : label),
          node('small', `${segment.ids.length} actions${kind && kind !== 'continue' ? ' · ' + humanize(kind) : ''}`));
        button.title = `${label}\n${segment.ids[0]} to ${segment.ids.at(-1)}`;
        sequence.append(button);
      }
      lane.append(sequence); container.append(lane);
    }

    const registry = node('details', undefined, 'goal-registry');
    registry.append(node('summary', `Goal registry · ${tracking.goals.length} records and their source evidence`));
    for (const goal of tracking.goals) {
      const item = node('details', undefined, 'goal-record');
      const title = goal.kind === 'recorded_objective' ? 'Initial task' : goal.text;
      item.append(node('summary', `${title.slice(0,120)}${title.length > 120 ? '…' : ''} · ${goal.event_ids.length} actions · ${humanize(goal.pursuit_status)}`));
      item.append(node('pre', goal.text), node('p', `${goal.trajectory_id} · ${humanize(goal.kind)} · ${goal.visits} ordered focus segments · ${goal.returns} returns · attainment ${goal.attainment}`, 'muted'));
      for (const reference of goal.references) {
        const source = bundle.run.events.find(e => e.id === reference.event_id);
        const detail = node('details');
        detail.append(node('summary', `${reference.event_id} · ${reference.source_pointer}${reference.copied_context ? ' · retained context' : ''}`),
          node('pre', source?.text || 'No source text'));
        item.append(detail);
      }
      if (goal.event_ids.length) item.append(actionButton('Inspect first pursuing action', goal.event_ids[0]));
      registry.append(item);
    }
    container.append(registry);
    const lineage = bundle.ingestion;
    if (lineage) {
      const history = node('details', undefined, 'goal-registry');
      history.append(node('summary', `Producer revisions · ${lineage.producer} / ${lineage.rollout_id} · revision ${lineage.revision} · ${humanize(lineage.state)}`));
      history.append(node('p', 'Producer state describes recording status. Task success still requires environment evidence. Earlier snapshots remain inspectable.', 'muted'));
      for (const item of lineage.history) {
        const button = node('button', `Revision ${item.revision} · ${humanize(item.state)}`);
        button.type = 'button'; button.disabled = item.run_id === bundle.run.id;
        button.addEventListener('click', () => window.trackerOpenRun(item.run_id));
        history.append(button);
      }
      container.append(history);
    }
  }

  function renderQueue() {
    const queue = bundle.analysis.review_queue || [];
    const list = $('#review-queue');
    list.replaceChildren();
    $('#review-queue-count').textContent = `${queue.length} groups · ${queue.reduce((n,g) => n + g.event_ids.length, 0)} actions`;
    if (!queue.length) list.append(node('p', 'No cases from the current routing rules. This is not an exhaustive check of model behavior.', 'muted'));
    for (const group of queue.slice(0,40)) {
      const button = actionButton('', group.event_ids[0], 'queue-item');
      button.append(node('strong', `${group.event_ids.length} actions · ${group.reasons.join(' · ')}`), node('span', group.preview));
      list.append(button);
    }
    if (queue.length > 40) list.append(node('p', 'Showing the 40 largest groups. Export includes the full queue.', 'muted'));
  }

  function renderVerification() {
    const container = $('#verification-overview');
    container.replaceChildren();
    const v = bundle.analysis.verification;
    if (!v) { container.append(node('p','Reindex this run to enable verification evidence.','muted')); return; }
    const outcome = v.outcome;
    const status = outcome.dataset_verified_success === true ? 'Dataset reports task success' : outcome.dataset_verified_success === false ? 'Dataset reports task unsuccessful' : 'Task success is not recorded';
    container.append(node('p', `${v.checks.length} verification-purpose actions · ${v.checks.filter(c=>c.feedback_ids.length).length} with linked results · ${v.completion_claims.length} structured completion claims`, 'goal-coverage'));
    container.append(node('p', status + (outcome.termination ? ` · Recorded termination: ${outcome.termination}` : ''), 'muted'));
    if (outcome.rewards) container.append(node('p', 'Recorded verifier rewards: ' + Object.entries(outcome.rewards).map(([k,v])=>`${k} = ${v}`).join(' · ')));
    for (const tail of v.actor_tails) {
      const row = node('p', undefined, 'check-tail');
      row.append(node('span', `${tail.trajectory_id}: `));
      if (tail.status === 'unresolved') row.append(node('span', 'Closure unresolved: action purpose or order is incomplete. '));
      if (tail.last_check) row.append(actionButton(`Latest observed check ${tail.last_check}`,tail.last_check));
      else row.append(node('span','No verification-purpose action observed.'));
      if (tail.application_after_check.length) row.append(node('span', `${tail.application_after_check.length} application-purpose actions ${tail.last_check?'followed that check':'were recorded'}.`));
      row.title = tail.limitation;
      container.append(row);
    }
    const checkList = node('div', undefined, 'check-list');
    for (const check of v.checks) {
      const button = actionButton('',check.event_id,'queue-item');
      button.append(node('strong',`${check.event_id} · ${check.text.split('\n')[0]}`),
        node('span',check.reported_summary ? check.reported_summary.text : check.feedback_ids.length ? 'Result text is linked; scoped verdict not established' : 'No linked result recorded'));
      checkList.append(button);
    }
    container.append(checkList,node('p','A check attempt, printed test summary, completion claim and verified task outcome are distinct. Artifact versions and task-wide verification coverage are not established by these logs.','muted'));
    const usage = node('details',undefined,'resource-detail');
    usage.append(node('summary','Recorded resources and measurement coverage'));
    for (const report of v.resources.reports) {
      usage.append(node('h3',report.label));
      const list = node('dl',undefined,'context-facts');
      for (const [key,measurement] of Object.entries(report.values)) list.append(node('dt',humanize(key)),node('dd',String(measurement.value)));
      usage.append(list,node('p',`${report.source.source_id||'Original trajectory'} · ${report.source.pointer}`,'source-ref'));
    }
    if (!v.resources.reports.length) usage.append(node('p','Token and cost totals are not recorded in recognized producer fields.','muted'));
    const execution = v.resources.execution;
    usage.append(node('p',`${execution.recorded_actions}/${execution.eligible_actions} actions have execution durations${execution.seconds!==null?`; recorded sum ${execution.seconds.toFixed(3)} seconds`:''}. ${execution.complete?'Coverage is complete for the logged actions.':'Unrecorded durations remain unknown.'}`,'muted'),node('p',v.resources.definition,'muted'));
    container.append(usage);
    const context = node('details',undefined,'resource-detail');
    context.append(node('summary','Environment context and producer sources'));
    const facts = bundle.run.environment_context?.facts || [];
    if (!facts.length) context.append(node('p','No configuration or result sidecar has been attached. Recorded actions alone do not establish the complete environment rules.','muted'));
    for (const fact of facts) {
      const detail = node('details');
      detail.append(node('summary',`${fact.key} · ${fact.nature}`),node('pre',typeof fact.value==='string'?fact.value:JSON.stringify(fact.value,null,2)),node('p',`${fact.source_id} · ${fact.pointer}`,'source-ref'));
      context.append(detail);
    }
    for (const source of bundle.run.sources || []) {
      const detail = node('details');
      detail.append(node('summary',`${source.name}${source.projection?' · selected fields':''}`),node('pre',typeof source.data==='string'?source.data:JSON.stringify(source.data,null,2)),
        node('p',`Content ${source.content_hash}${source.source_sha256?' · Original file '+source.source_sha256:''}`,'source-ref'));
      context.append(detail);
    }
    container.append(context);
  }

  function probabilities(observation, name) {
    const detail = node('details', undefined, 'probability-detail');
    detail.append(node('summary', `${humanize(name)} · ${humanize(observation.value)} · ${humanize(observation.status)}`));
    if (observation.source === 'evidence_gate') {
      detail.append(node('p', observation.basis || 'Required evidence is unavailable.', 'muted'));
      detail.append(node('p', 'This status follows the recorded evidence requirements; it is not a model decision.', 'muted'));
      if (observation.withheld_observation) detail.append(probabilities(observation.withheld_observation, 'Withheld earlier observation'));
      return detail;
    }
    if (observation.source === 'review') {
      detail.append(node('p', `Reviewed by ${observation.reviewer}. ${observation.note || ''}`, 'muted'));
      if (observation.model_observation) detail.append(probabilities(observation.model_observation, 'Original model observation'));
      return detail;
    }
    const p = observation.probabilities || {};
    if (!Object.keys(p).length) detail.append(node('p', 'No probability distribution recorded.', 'muted'));
    for (const [choice, value] of Object.entries(p).sort((a,b) => b[1] - a[1])) {
      const row = node('div', undefined, 'probability-row');
      const bar = node('meter'); bar.min = 0; bar.max = 1; bar.value = value;
      const label = name === 'focus_goal' ? goalName(choice) : humanize(choice);
      bar.setAttribute('aria-label', label);
      row.append(node('span', label), bar, node('span', `${(value*100).toFixed(1)}%`));
      detail.append(row);
    }
    detail.append(node('p', observation.selection_policy==='argmax/1'?'Highest-probability supplied option; no probability or confidence threshold. Probabilities are not validated accuracy estimates.':observation.threshold!==undefined?`Historical selection: probability threshold ${observation.threshold}. Preserved for audit.`:'Selection policy not recorded.', 'muted'));
    if(observation.evidence_gate)detail.append(node('p','Evidence limitation: '+observation.evidence_gate,'muted'));
    if (observation.evidence) {
      const packet = node('details');
      packet.append(node('summary', 'Inspect the exact evidence packet'), node('pre', JSON.stringify(observation.evidence, null, 2)));
      detail.append(packet);
    }
    return detail;
  }

  async function select(eventId) {
    selection = eventId;
    const sequence = ++requestSequence;
    const action = bundle?.analysis.actions.find(a => a.event_id === eventId);
    $('#review-panel').hidden = !action;
    const inspector = $('#probability-inspector');
    inspector.replaceChildren();
    const form = $('#review-form'); form.replaceChildren();
    if (!action) return;
    for (const [key, observation] of Object.entries(action.semantic)) {
      if (!key.startsWith('_')) inspector.append(probabilities(observation, key));
    }
    const runId = bundle.run.id;
    const revision = bundle.review_revision;
    try {
      const query = new URLSearchParams({run_id: runId, event_id: eventId});
      const response = await fetch('/api/review-options?' + query);
      const data = await response.json();
      if (!response.ok) throw Error(data.error || 'Could not load review choices');
      if (requestSequence !== sequence) return;
      const field = node('select'); field.id = 'review-field';
      for (const key of Object.keys(data.options)) field.add(new Option(humanize(key), key));
      const value = node('select'); value.id = 'review-value';
      const description = node('p', undefined, 'review-criterion');
      const reviewer = node('input'); reviewer.id = 'reviewer'; reviewer.maxLength = 120;
      reviewer.required = true; reviewer.value = reviewerLabel; reviewer.placeholder = 'Reviewer name or label';
      reviewer.addEventListener('input', () => { reviewerLabel = reviewer.value; });
      const note = node('textarea'); note.id = 'review-note'; note.maxLength = 4000; note.rows = 2;
      note.placeholder = 'Evidence and rationale (optional)';
      const showCriterion = () => {
        const criterion = data.options[field.value][value.value];
        description.textContent = typeof criterion === 'string' ? criterion : `${criterion.goal} · ${humanize(criterion.origin)} · evidence: ${criterion.evidence_events.join(', ')}`;
      };
      const choices = () => {
        value.replaceChildren();
        value.add(new Option('Choose an observation…', ''));
        for (const [key, criterion] of Object.entries(data.options[field.value])) {
          const label = typeof criterion === 'object' ? criterion.goal : humanize(key);
          value.add(new Option(label.slice(0,180), key));
        }
        const current = action.semantic[field.value];
        if (current?.source === 'review') value.value = current.value;
        description.textContent = '';
        if (value.value) showCriterion();
      };
      field.addEventListener('change', choices);
      value.addEventListener('change', () => { if (value.value) showCriterion(); else description.textContent = ''; });
      choices();
      const grid = node('div', undefined, 'review-grid');
      for (const [text, control] of [['Observation', field], ['Choice', value], ['Reviewer', reviewer], ['Reason', note]]) {
        const label = node('label', text); label.append(control); grid.append(label);
      }
      const buttons = node('div', undefined, 'review-buttons');
      const save = node('button', 'Save review', 'primary'); save.type = 'submit';
      const clear = node('button', 'Clear override'); clear.type = 'button';
      const status = node('span'); status.id = 'review-status'; status.setAttribute('role', 'status');
      buttons.append(save, clear, status);
      form.append(grid, description, buttons);

      async function submit(clearing = false) {
        if (!form.reportValidity()) return;
        if (!clearing && !value.value) { status.textContent = 'Choose an observation first.'; return; }
        save.disabled = clear.disabled = true;
        const payload = {run_id: runId, event_id: eventId, field: field.value, value: clearing ? null : value.value,
          reviewer: reviewer.value.trim(), note: note.value, expected_revision: revision, evidence_ids: [eventId]};
        try {
          const response = await fetch('/api/reviews', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)});
          const result = await response.json();
          if (!response.ok) throw Error(result.error || 'Review was not saved');
          if (bundle.run.id === runId) await window.trackerReload(runId, eventId);
        } catch (error) { status.textContent = error.message; }
        finally { save.disabled = clear.disabled = false; }
      }
      form.onsubmit = event => { event.preventDefault(); submit(); };
      clear.addEventListener('click', () => submit(true));

      const audit = $('#review-audit'); audit.replaceChildren();
      for (const review of (bundle.reviews || []).filter(r => r.event_id === eventId).reverse()) {
        audit.append(node('p', `#${review.id} · ${review.reviewer} · ${humanize(review.field)} → ${review.value === null ? 'override cleared' : goalName(review.value)} · ${review.created_at}${review.note ? ' · ' + review.note : ''}`));
      }
      if (!audit.childElementCount) audit.append(node('p', 'No reviews for this action.', 'muted'));
    } catch (error) {
      if (requestSequence === sequence) form.append(node('p', error.message, 'error'));
    }
  }

  function comparison(container, result) {
    container.append(node('p', result.ordered_by_training_step
      ? `Ordered by recorded policy step. Reference: ${result.reference_checkpoint}.`
      : `Checkpoint order is alphabetical because distinct policy steps are unavailable. Reference: ${result.reference_checkpoint}; this is not a training timeline.`, 'compare-details'));
    const names = {explore:'Explore', apply:'Apply approach', verify:'Verify', coordinate:'Coordinate', report:'Report',
      unresolved:'Unresolved', connected:'Task connected', outside:'Outside task', conflicting:'Conflicting',
      repeat_rate:'Exact repeat rate', action_count:'Actions per rollout', goal_assignment_rate:'Goal assignment coverage'};
    for (const pair of result.paired_deltas || []) {
      const panel = node('details', undefined, 'delta-panel');
      panel.open = true;
      panel.append(node('summary', `${pair.checkpoint} compared with ${pair.reference}`));
      window.trackerComparison.flow(panel,result,pair);
      const label = node('label', 'Observation family ');
      const family = node('select'); family.setAttribute('aria-label', 'Delta observation family');
      for (const [value,text] of [['purpose.','Purpose'],['task_relation.','Task relation'],['feedback.','Feedback response'],['counts','Work and coverage']]) family.add(new Option(text,value));
      label.append(family);
      const rows = node('div', undefined, 'delta-rows');
      const format = (value, count) => `${value>0?'+':''}${(value*(count?1:100)).toFixed(1)} ${count?'actions':'pp'}`;
      const render = () => {
        rows.replaceChildren();
        const entries = Object.entries(pair.metrics).filter(([key]) => family.value==='counts' ? !key.includes('.') : key.startsWith(family.value));
        if (!entries.length) rows.append(node('p', 'No paired tasks with a recorded opportunity for this observation.', 'muted'));
        for (const [key, metric] of entries) {
          const count = key==='action_count';
          const short = key.includes('.') ? key.split('.')[1] : key;
          const row = node('div', undefined, 'delta-row');
          row.append(node('strong', names[short] || humanize(short)));
          const estimate = node('div');
          estimate.append(node('span', format(metric.delta,count), 'delta-value'));
          const interval = metric.interval_95;
          estimate.append(node('small', interval ? `95% interval ${format(interval[0],count)} to ${format(interval[1],count)}` : 'Interval unavailable: fewer than 5 paired tasks'));
          const inspect=node('button','Inspect evidence','metric-evidence-button');
          inspect.setAttribute('aria-label',`Inspect evidence for ${names[short] || humanize(short)}`);
          inspect.addEventListener('click',()=>window.trackerComparison.inspect(result,pair,key));
          const countAndLink=node('div');countAndLink.append(node('span', `${metric.task_count} tasks`, 'muted'),inspect);
          row.append(estimate,countAndLink);
          rows.append(row);
        }
      };
      family.addEventListener('change', render); render();
      panel.append(label, rows, node('p', 'pp = percentage points. Positive means more of the observed behavior; it does not automatically mean better.', 'compare-details'));
      const method = node('details');
      method.append(node('summary', 'Method and opportunity coverage'), node('p', pair.method, 'compare-details'),
        node('p', `Feedback response: ${pair.feedback_matched_tasks.length} paired tasks; ${pair.feedback_excluded_tasks.length} tasks excluded because one side has no recorded response opportunity.`, 'compare-details'));
      panel.append(method); container.append(panel);
    }
    const exclusions = node('details');
    exclusions.append(node('summary', `${result.excluded.length} excluded rollouts · inspect reasons`));
    for (const row of result.excluded) exclusions.append(node('p', `${row.id}: ${row.reason}`, 'source-ref'));
    container.append(exclusions);
  }

  function renderCapabilities() {
    const container = $('#measurement-support');
    const caption = $('#measurement-support-caption');
    container.replaceChildren();
    const evidence = bundle.analysis.capabilities;
    if (!evidence) {
      caption.textContent = 'Measurement evidence has not been assessed for this saved view';
      container.append(node('p', 'Reindex this run to assess the current measurement requirements.', 'muted'));
      return;
    }
    const names = {work_sequence: 'Work sequence', feedback_response: 'Response after feedback', verification_closure: 'Verification and closure'};
    const limited = Object.values(evidence.measurements).filter(m => m.status === 'limited' || m.status === 'unavailable').length;
    caption.textContent = `Measurement evidence · ${limited ? `${limited} measures have limited or unavailable evidence` : 'requirements assessed'}`;
    for (const key of Object.keys(names)) {
      const measure = evidence.measurements[key];
      if (!measure) continue;
      const row = node('div', undefined, 'measurement-row');
      row.append(node('h3', `${names[key] || humanize(key)} · ${humanize(measure.status)}`), node('p', measure.reason));
      const counts = node('dl', undefined, 'measurement-counts');
      for (const [label, value] of Object.entries(measure.counts)) {
        counts.append(node('dt', humanize(label)), node('dd', typeof value === 'boolean' ? value ? 'yes' : 'no' : String(value)));
      }
      row.append(counts); container.append(row);
    }
    container.append(node('p', `${evidence.source.linked_feedback} linked feedback records · ${evidence.source.unlinked_feedback_ids.length} unlinked · ${evidence.source.feedback_origins.harness || 0} from the harness. ${evidence.source.recorded_checkpoint ? 'Policy checkpoint recorded.' : 'No policy checkpoint recorded; excluded from training comparisons.'}`, 'muted'));
  }

  return {
    render(nextBundle) { bundle = nextBundle; renderCapabilities(); renderGoals(); renderQueue(); renderVerification(); },
    select,
    comparison,
    goalLanes,
  };
})();
