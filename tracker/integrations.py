"""Evidence-backed capture routes and side-effect-free source preflight.

A bridge route is not a tested native integration. Keep upstream API evidence,
local validation and measurement availability separate.
"""
from collections import Counter

from .adapters import FORMATS, normalize
from .capabilities import links
from .rollout_metrics import DEFINITIONS, source_record
from .schema import InputError

VERSION='integration-contracts/1'
ROUTES=[
 {'name':'mini-SWE-agent v2','route':'Public save hook → MiniCapture → durable outbox',
  'validation':'Native 2.4.6 DefaultAgent + LocalEnvironment: seven deterministic cases, capture-on/off equality, 39 delivered revisions and 14 evidence-linked measurements',
  'boundary':'Text, tool-call and Responses records tested. Parsed actions do not prove execution; normal limit stops remain complete traces without implying success. Authored outputs do not establish policy quality, container compatibility or distributed training.',
  'sources':[('Capture recipe','/integration-guide#mini-agent'),('Default agent API','https://mini-swe-agent.com/latest/reference/agents/default/')]},
 {'name':'Harbor / ATIF / SWE-agent','route':'Native files → directory watcher, or ATIF → outbox',
  'validation':'Public trajectory replays + local live-file tests',
  'boundary':'Preserves recorded steps, native call links and available sidecars. A watcher sees saved snapshots; it cannot see unwritten steps. ATIF support is a decoded subset, not full schema conformance.',
  'sources':[('ATIF specification','https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md'),('SWE-agent trajectories','https://swe-agent.com/latest/usage/trajectories/')]},
 {'name':'Gymnasium','route':'reset / step → Episode → outbox',
  'validation':'Runtime audit: Gymnasium 1.4.0 FrozenLake + TimeLimit',
  'boundary':'Preserves action/observation/reward and separate terminated/truncated flags. State arrays need a deliberate JSON projection. Ending does not imply success.',
  'sources':[('Environment API','https://gymnasium.farama.org/api/env/')]},
 {'name':'OpenEnv','route':'Observation + Action → Episode.openenv_step → outbox',
  'validation':'Authored protocol tests; no live OpenEnv server tested',
  'boundary':'Preserves native done and reward. Does not manufacture Gymnasium termination/truncation semantics. Only agent-visible fields belong in observation.',
  'sources':[('First environment','https://huggingface.co/docs/openenv/en/guides/first-environment')]},
 {'name':'verl','route':'Existing generation export; structured rollout history → chat / ATIF bridge',
  'validation':'JSONL generation batches tested through CLI, HTTP and browser; structured trainer bridge untested',
  'boundary':'Capture before flattening and record sampling policy. Trace sample limits apply per worker and selected prompt repeats. A logged step is not automatically a generating policy version.',
  'sources':[('Rollout traces','https://verl.readthedocs.io/en/latest/advance/rollout_trace.html'),('Asynchronous identity','https://verl.readthedocs.io/en/latest/advance/skip_manager.html')]},
 {'name':'TRL GRPO','route':'Public reward function → GRPOCapture → durable outbox',
  'validation':'Actual TRL 1.13.0 CPU training + evaluation; two independent concurrent trainers deliver 328 completions with capture-on/off equality, retry recovery and live dashboard checks',
  'boundary':'Captures one named reward component and callback clock, not weighted trainer reward or optimizer-use proof. GPU/distributed/vLLM and live tools untested. TRL 1.15.0 failed on this Windows CPU at its Triton-dependent fused path; do not assume current-release runtime support.',
  'sources':[('Capture recipe','/integration-guide#trl-grpo'),('GRPO trainer','https://huggingface.co/docs/trl/main/en/grpo_trainer'),('Release history','https://github.com/huggingface/trl/releases')]},
 {'name':'OpenRLHF','route':'Agent executor / agent function → chat or ATIF bridge',
  'validation':'Upstream hook documented; trainer integration untested',
  'boundary':'Record per-worker rollout identity, policy version and clocks in the agent execution path. The tracker does not implement its token-level training protocol.',
  'sources':[('Agent function example','https://github.com/OpenRLHF/OpenRLHF/blob/main/examples/python/agent_func.py'),('Project documentation','https://github.com/OpenRLHF/OpenRLHF')]},
 {'name':'slime','route':'custom_generate sample hook → chat / generation bridge',
  'validation':'Upstream hook documented; trainer integration untested',
  'boundary':'Record the trajectory before packing; preserve whether filtering included it in training. Hooking a finished Sample alone may lose intermediate agent steps.',
  'sources':[('Customization hooks','https://thudm.github.io/slime/get_started/customization.html')]},
 {'name':'AReaL','route':'Agent workflow async run → chat / ATIF bridge',
  'validation':'Upstream hook documented; trainer integration untested',
  'boundary':'Record generation and learner clocks separately. Preserve per-call policy identity if weights change during a trajectory. Legacy RolloutWorkflow is not the preferred new agent interface.',
  'sources':[('Agent workflow','https://github.com/areal-project/AReaL/blob/main/docs/en/reference/agent_workflow.md')]},
 {'name':'ART','route':'Trajectory.messages() + reward → chat bridge',
  'validation':'Upstream API documented; ART integration untested',
  'boundary':'Materialize messages from choices. Keep additional histories and subagents separate; use a structured trajectory export when branches matter.',
  'sources':[('Client / trajectories','https://art.openpipe.ai/fundamentals/art-client/'),('Additional histories','https://art.openpipe.ai/features/additional-histories/')]},
 {'name':'NeMo RL / NeMo Gym','route':'Full result export → explicit bridge; ATIF export where supplied',
  'validation':'Upstream integration documented; native decoder not implemented',
  'boundary':'Scalar-only logging cannot support behavior inspection. Responses-style events are not chat-completion messages; they require an explicit translator.',
  'sources':[('NeMo Gym integration','https://docs.nvidia.com/nemo/rl/nightly/design-docs/nemo-gym-integration.html')]},
 {'name':'BrowserGym / browser agents','route':'Gym transition bridge + explicit DOM/text/media projection',
  'validation':'Gym contract tested; browser runtime and visual inspection untested',
  'boundary':'Screenshots remain uninspected media references. DOM coverage, action validity and navigation outcomes need environment-specific evidence.',
  'sources':[('BrowserGym','https://github.com/ServiceNow/BrowserGym')]},
 {'name':'τ-bench / dual-control workflows','route':'Native text Results bundle or SimulationRun → file import / HTTP',
  'validation':'656 published airline/telecom simulations replayed; native simulator execution untested',
  'boundary':'Preserves participant identity, pending native call/result links and evaluator provenance. Private user tools stay outside assistant context. τ³ voice/chunk/tick streams are rejected. Evaluation trials are not training steps.',
  'sources':[('Pinned native message schema','https://github.com/sierra-research/tau2-bench/blob/4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699/src/tau2/data_model/message.py'),('Pinned simulation schema','https://github.com/sierra-research/tau2-bench/blob/4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699/src/tau2/data_model/simulation.py')]},
]


def catalog():
    from .input_catalog import catalog as input_catalog
    return {'schema':VERSION,'reviewed_at':'2026-10-11','formats':list(FORMATS),'routes':ROUTES,
        'inputs':input_catalog(),
        'scope':'Local collector and outbox/API transport. Listed bridges reuse tested source contracts; they are not claims of end-to-end trainer validation. Upstream main/latest/nightly APIs must be checked against your installed version.',
        'guide':'/integration-guide'}


def check(body):
    if not isinstance(body.get('metadata',{}),dict):raise InputError('metadata must be an object')
    if 'document' not in body:raise InputError('Supply document, format and optional metadata')
    runs=normalize(body['document'],body.get('format','auto'),body.get('metadata'),body.get('sources'))
    return {'schema':VERSION,'persisted':False,'runs':[inspect(run) for run in runs]}


def inspect(run):
    from .source_grain import describe
    events=[e for e in run['events'] if not e.get('copied_context')]
    counts=Counter(e['kind'] for e in events);bound=links(run)
    record=source_record(run);meta=run['metadata']
    keys=['actions','agent_text_chars','feedback_link_rate','exact_dispatch_repeat_rate','recorded_reward','recorded_success',
          'environment_steps','environment_episode_return','environment_terminated','environment_truncated','environment_done','environment_model_response_fraction']
    metrics=[{'id':key,'label':DEFINITIONS[key][0],'definition':DEFINITIONS[key][1],**record['metrics'][key]} for key in keys]
    clocks={k:meta[k] for k in ('experiment','training_step','training_step_basis','generation_step','learner_step','policy_version','checkpoint','sample_id','rollout_n','split','sampling','training_inclusion') if k in meta}
    missing=[]
    if not meta.get('experiment'):missing.append('experiment')
    if type(meta.get('training_step')) is not int:missing.append('training_step')
    if not meta.get('training_step_basis'):missing.append('training_step_basis')
    media=sum(bool(e.get('media')) for e in events)
    functions=[
      {'name':'Recorded timeline and source links','state':'available','detail':f"{len(events)} events; {len(bound['records'])} source-bound action/result links. This does not establish why an action was taken."},
      {'name':'Training trend comparability','state':'needs_metadata' if missing else 'declared',
       'detail':'Missing: '+', '.join(missing) if missing else 'Explicit plotting clock supplied. Policy, task, sampling and reward comparability still need matching cohorts.'},
      {'name':'Semantic activities, plans and failure/revision relations','state':'needs_analysis',
       'detail':'Import does not establish semantic accuracy. Use a versioned observer with suitable source coverage and reviewed examples for this domain.'},
      {'name':'Sample groups, filtering and training use','state':'requires_training_records',
       'detail':'Deliver training-records/1 facts for one sample per rollout, or training-records/2 for independent samples with pinned episode mappings. A reward callback or imported trace alone does not establish backward or optimizer use.'},
      {'name':'Visual / audio behavior','state':'uninspected' if media else 'not_recorded',
       'detail':f'{media} events contain media references. Text-only measurements do not inspect their contents.'},
    ]
    return {'adapter':run['adapter'],'adapter_version':run['adapter_version'],'source_id':run['id'],
      'source_unit':describe(run),
      'counts':dict(counts),'trajectory_count':len({e['trajectory_id'] for e in events}),
      'linked_responses':len(bound['records']),'unlinked_responses':len(bound['unlinked_ids']),
      'clocks':clocks,'warnings':run['warnings'],'metrics':metrics,'functions':functions,
      'note':'A successful preflight validates this supplied snapshot. It does not verify exporter completeness, live connectivity or semantic accuracy.'}
