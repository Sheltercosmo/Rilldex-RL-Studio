"""Reusable, source-bound extraction workspaces; no trajectory-specific answers."""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import time

from .base_standard import VERSION as ACTIVITY_VERSION
from .schema import InputError, digest
from .semantic_extraction import (
    FileCandidates, Pipeline, PARTITION_CANDIDATE_STANDARD, SEMANTIC_PARTITIONS,
    audit_result, partition, read, replay_decision, windows, write,
    ACTIVITY_ROUTING,activity_choices,
    partition_contract, WORK_PHASE_STANDARD,
)

VERSION = 'semantic-workspace/1'
DEFAULT_CONTEXT = {'schema': 'readable-context/3', 'recent_events': 8,
                   'max_event_chars': 4000, 'extra_ranges': []}


@contextmanager
def exclusive(directory):
    """OS-owned lock releases on process exit; a leftover file is not a live lock."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.workspace.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise InputError('Another process is using this extraction workspace') from None
        try:
            yield root
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def initialize(directory, run, *, include_user=True, context_policy=None,activity_routing=ACTIVITY_ROUTING,reading_protocol='contribution-readings/1',partition_standard=PARTITION_CANDIDATE_STANDARD,feedback_profile=None,requested_profile=None,action_target_version=None,plan_relation_version=None,execution_report_version=None,method_comparison_version=None):
    from .semantic_layers import profile,requested_profile as validate_requested
    profile(feedback_profile)
    validate_requested(requested_profile,include_user)
    from .contribution_readings import protocol,VERSION as READING_VERSION
    protocol(reading_protocol)
    activity_choices(activity_routing)
    if partition_standard not in {PARTITION_CANDIDATE_STANDARD, WORK_PHASE_STANDARD}:
        raise InputError('Unsupported workspace partition standard')
    partition_contract(partition_standard)
    policy = deepcopy(DEFAULT_CONTEXT if context_policy is None else context_policy)
    if not run.get('id', '').isalnum():
        raise InputError('Invalid normalized run ID')
    config = {'schema': VERSION, 'run_id': run['id'], 'source_hash': digest(run),
              'include_user': include_user, 'context_policy': policy,
              'partition_standard': partition_standard,
              'partition_policy': SEMANTIC_PARTITIONS, 'contribution_readings': True,
              'activity_standard': ACTIVITY_VERSION}
    if activity_routing!=ACTIVITY_ROUTING:config['activity_routing']=activity_routing
    if reading_protocol!=READING_VERSION:config['reading_protocol']=reading_protocol
    if feedback_profile is not None:config['feedback_profile']=feedback_profile
    if requested_profile is not None:config['requested_profile']=requested_profile
    if action_target_version is not None:
        from .action_targets import PAGED_VERSION
        if action_target_version!=PAGED_VERSION:raise InputError('Unsupported workspace action correspondence version')
        config['action_target_version']=action_target_version
    if plan_relation_version is not None:
        from .plan_relations import PAGED_VERSIONS
        if plan_relation_version not in PAGED_VERSIONS:raise InputError('Unsupported workspace Plan correspondence version')
        config['plan_relation_version']=plan_relation_version
    if execution_report_version is not None:
        from .execution_reports import VERSION as REPORT_VERSION
        if execution_report_version!=REPORT_VERSION:raise InputError('Unsupported execution report version')
        config['execution_report_version']=execution_report_version
    if method_comparison_version is not None:
        from .method_comparison import NATIVE_VERSION
        if method_comparison_version!=NATIVE_VERSION or not action_target_version:
            raise InputError('Approach comparison requires the current method protocol and work-target links')
        config['method_comparison_version']=method_comparison_version
    with exclusive(directory) as root:
        config_path = root / 'workspace.json'
        if config_path.exists():
            if context_policy is None:config['context_policy']=read(config_path)['context_policy']
            if read(config_path) != config:
                raise InputError('Workspace source or observer configuration changed; use a new directory')
            load(root)
            return config
        if any(p.name != '.workspace.lock' for p in root.iterdir()):
            raise InputError('A new workspace requires an empty directory')
        # Source is frozen before any candidate or prediction is produced.
        write(root / 'runs' / f'{run["id"]}.json', run)
        write(config_path, config)
    return config


def load(directory):
    from .contribution_readings import protocol,VERSION as READING_VERSION
    root = Path(directory)
    config = read(root / 'workspace.json')
    from .semantic_layers import profile,requested_profile
    profile(config.get('feedback_profile'))
    requested_profile(config.get('requested_profile'),config.get('include_user'))
    activity_choices(config.get('activity_routing',ACTIVITY_ROUTING))
    protocol(config.get('reading_protocol',READING_VERSION))
    from .action_targets import PAGED_VERSION
    if config.get('action_target_version') not in {None,PAGED_VERSION}:
        raise InputError('Unsupported workspace action correspondence version')
    from .plan_relations import PAGED_VERSIONS
    if config.get('plan_relation_version') not in {None,*PAGED_VERSIONS}:
        raise InputError('Unsupported workspace Plan correspondence version')
    from .execution_reports import VERSION as REPORT_VERSION
    if config.get('execution_report_version') not in {None,REPORT_VERSION}:
        raise InputError('Unsupported execution report version')
    from .method_comparison import NATIVE_VERSION
    if config.get('method_comparison_version') not in {None,NATIVE_VERSION} or (config.get('method_comparison_version') and not config.get('action_target_version')):
        raise InputError('Unsupported approach comparison configuration')
    if (config.get('schema') != VERSION or not config.get('run_id', '').isalnum()
            or config.get('activity_standard') != ACTIVITY_VERSION
            or config.get('partition_standard') not in {PARTITION_CANDIDATE_STANDARD, WORK_PHASE_STANDARD}
            or config.get('partition_policy') != SEMANTIC_PARTITIONS
            or config.get('contribution_readings') is not True
            or not isinstance(config.get('include_user'), bool)):
        raise InputError('Unknown or incompatible extraction workspace contract')
    run = read(root / 'runs' / f'{config["run_id"]}.json')
    if run.get('id') != config['run_id'] or digest(run) != config.get('source_hash'):
        raise InputError('Frozen workspace source changed')
    return config, run


def provider(directory, config, command=None, producer=None, execution_budget=None, citation_format=None, cache_directories=()):
    options = dict(context_policy=config['context_policy'],
                   partition_standard=config['partition_standard'],
                   partition_policy=config['partition_policy'], contribution_readings=True,
                   activity_routing=config.get('activity_routing',ACTIVITY_ROUTING),
                   reading_protocol=config.get('reading_protocol','contribution-readings/1'),
                   cache_directories=cache_directories)
    if command:
        from .candidate_worker import CommandCandidates
        return CommandCandidates(Path(directory) / 'candidates', command, producer,
                                 execution_budget=execution_budget, citation_format=citation_format, **options)
    if producer or citation_format:
        raise InputError('Candidate producer and citation format settings require a candidate command')
    return FileCandidates(Path(directory) / 'candidates', **options)


def prepare(directory):
    """Queue independent first-stage requests over the full run without inference."""
    with exclusive(directory) as root:
        config, run = load(root)
        candidates = provider(root, config)
        for window in windows(run, include_user=config['include_user']):
            if window['kind'] == 'action_dispatch':
                ref = partition(run, window, [window])[0]
                candidates.readings(run, ref)
            else:
                candidates.partitions(run, window, needed=True)
        return status(root)


def target_status(directory, result, version, filename='action-target-progress.json'):
    if not version:return {'status':'not_requested'}
    if not result or result.get('status')!='complete_local_extraction':return {'status':'awaiting_local_annotations'}
    path=Path(directory)/filename
    if path.exists():
        saved=read(path)
        if saved.get('extraction_hash')==digest(result) and saved.get('schema')==version:
            return {'status':saved['status'],'coverage':saved['coverage'],'version':version}
    return {'status':'pending','version':version}


def status(directory):
    from .semantic_budget import summary
    root = Path(directory)
    config, run = load(root)
    pending = []
    for path in sorted([*(root/'candidates'/'requests').glob('*.json'),*(root/'work_candidates'/'requests').glob('*.json')]):
        request = read(path)
        if path.stem != digest(request):
            raise InputError('Candidate request content differs from its identity')
        source = request['source']
        pending.append({'request_hash': path.stem,
                        'stage': request.get('stage', 'partition'),
                        'event_id': source['event_id'],
                        'response_supplied': (path.parent.parent / 'responses' / path.name).exists(),
                        'request_path': str(path.resolve())})
    checkpoint = root / 'checkpoints' / f'{run["id"]}.json'
    result = read(checkpoint) if checkpoint.exists() else None
    published = root / 'results' / f'{run["id"]}.json'
    last_execution = read(root / 'last-execution.json') if (root / 'last-execution.json').exists() else None
    eligible = windows(run, include_user=config['include_user'])
    eligible_bytes = sum(len(w['text'].encode('utf-8')) for w in eligible)
    selected_units = [u for u in result['units'] if u['status'] == 'selected'] if result else []
    selected_bytes = sum(len(u['source']['text'].encode('utf-8')) for u in selected_units)
    from .semantic_layers import feedback_status,requested_status
    feedback=feedback_status(root,result,config.get('feedback_profile'))
    requested=requested_status(root,result,config.get('requested_profile'),config['context_policy'])
    targets=target_status(root,result,config.get('action_target_version'))
    plans=target_status(root,result,config.get('plan_relation_version'),'plan-relation-progress.json')
    from .execution_reports import status as report_status
    reports=report_status(root,run,config.get('execution_report_version'))
    methods=target_status(root,result,config.get('method_comparison_version'),'method-comparison-progress.json')
    # Queue presence is not validation or a selected annotation.
    return {'schema': 'semantic-workspace-status/1', 'run_id': run['id'],
            'source_hash': config['source_hash'],
            'activity_routing':config.get('activity_routing',ACTIVITY_ROUTING),
            'reading_protocol':config.get('reading_protocol','contribution-readings/1'),
            'eligible_windows': len(eligible),
            'status': (last_execution['status'] if last_execution and last_execution['status'] in {'budget_reached', 'interrupted'}
                       else 'needs_layers' if feedback['status']=='pending' or requested['status']=='pending' or any(r['status'] in {'pending','running','validating','needs_evidence'} for r in (targets,plans,reports,methods))
                       else result.get('status', 'interrupted') if result else 'prepared'),
            'layers':{'feedback':feedback,'requested_conditions':requested,'action_targets':targets,'plan_relations':plans,'execution_reports':reports,'method_comparison':methods},
            'coverage': {'eligible_windows': len(eligible),
                         'visited_windows': len(result['windows']) if result else 0,
                         'unvisited_windows': len(eligible) - len(result['windows']) if result else len(eligible),
                         'selected_units': len(selected_units),
                         'eligible_source_bytes': eligible_bytes,
                         'selected_source_bytes': selected_bytes,
                         'selected_source_fraction': selected_bytes / eligible_bytes if eligible_bytes else None,
                         'basis': 'UTF-8 bytes of eligible agent/user expressions and dispatch payloads; whitespace between units may be excluded. This is annotation coverage, not accuracy or coverage of tool feedback.'},
            'unit_status_counts': dict(Counter(u['status'] for u in result['units'])) if result else {},
            'window_status_counts': dict(Counter(w['status'] for w in result['windows'])) if result else {},
            'last_complete_result_present': published.exists(),
            'candidate_requests': len(pending),
            'responses_supplied': sum(row['response_supplied'] for row in pending),
            'requests_without_responses': [row for row in pending if not row['response_supplied']],
            'queue_note': 'Response presence is not validation. Rejected candidates may still need repair; run/resume to inspect dependent stages.',
            'last_execution': last_execution, 'provider_usage': summary(root),
            'accuracy': 'Not independently measured'}


def check_configuration(result, config, directory=None):
    from .semantic_extraction import PARTICIPANT_SCOPE
    if (result.get('whole_run') is not True
            or result.get('reading_context_policy') != config['context_policy']
            or result.get('partition_policy') != config['partition_policy']
            or result.get('activity_standard') != config['activity_standard']
            or result.get('activity_routing',ACTIVITY_ROUTING)!=config.get('activity_routing',ACTIVITY_ROUTING)
            or result.get('activity_reading_contract') != config.get('reading_protocol','contribution-readings/1')
            or (result.get('participant_scope') == PARTICIPANT_SCOPE) != config['include_user']):
        raise InputError('Saved extraction differs from its workspace configuration')
    if directory is not None:
        for row in result['windows']:
            if row.get('partition_request'):
                selected = read(Path(directory) / 'decisions' / f'{row["partition_request"]}.json')
                if selected['request']['state'].get('partition_standard') != config['partition_standard']:
                    raise InputError('Saved partition decision differs from the workspace configuration')


def execute(directory, transport, *, command=None, producer=None, progress=None, budget_limits=None, citation_format=None, budget_ledger=None, cache_directories=()):
    from .semantic_budget import BudgetReached, ExecutionBudget
    with exclusive(directory) as root:
        config, run = load(root)
        execution_id = time.time_ns()
        budget = ExecutionBudget(root, execution_id, budget_limits, ledger=budget_ledger)
        candidates = provider(root, config, command, producer, budget, citation_format, cache_directories)
        from .semantic_layers import requested_provider
        work_candidates = requested_provider(root,command,producer,budget,citation_format,cache_directories) if config.get('requested_profile') else None
        calls = 0
        start = time.monotonic()

        def send(request):
            nonlocal calls
            response = transport(request)
            calls += 1
            # Preserve completed provider responses even if answer validation fails.
            key = digest(request)
            destination = root / 'wire' / key / f'{time.time_ns()}.json'
            write(destination, {'request': request, 'response': response})
            return response

        def recorded_transport(request):
            return budget.invoke('jev', request, lambda: send(request))

        engine = Pipeline(root, candidates, recorded_transport, cache_directories=cache_directories)
        receipt = {'schema': 'semantic-workspace-execution/1', 'status': 'running',
                   'source_hash': config['source_hash'],
                   'candidate_mode': 'command' if command else 'file',
                   'candidate_producer': producer, 'started_at_ns': execution_id,
                   'budget_limits': budget.limits, 'budget_scope': 'New invocations in this execution; resume starts a new allowance. Cached work is free.'}
        if budget_ledger is not None:
            receipt['budget_scope'] = 'Per-execution limits plus a persistent worker allowance; restart does not replenish the worker budget.'
        if citation_format is not None:receipt['configured_citation_format']=citation_format
        write(root / 'last-execution.json', receipt)
        try:
            result = engine.run(run, include_user=config['include_user'], progress=progress)
            check_configuration(result, config, root)
            audit_result(run, result, root)
            if result['status']=='complete_local_extraction':
                if config.get('plan_relation_version'):
                    from .plan_relations import execute as execute_plans
                    plans,validation=execute_plans(run,result,engine,version=config['plan_relation_version'],
                        progress=lambda value:write(root/'plan-relation-progress.json',value))
                    receipt['plan_relations']={'status':plans['status'],'coverage':plans['coverage'],'validation':validation}
                if config.get('action_target_version'):
                    from .action_targets import execute as execute_targets
                    targets,validation=execute_targets(run,result,engine,version=config['action_target_version'],
                        progress=lambda value:write(root/'action-target-progress.json',value))
                    receipt['action_targets']={'status':targets['status'],'coverage':targets['coverage'],'validation':validation}
                if config.get('execution_report_version'):
                    from .execution_reports import execute as execute_reports
                    reports,validation=execute_reports(run,engine,
                        progress=lambda value:write(root/'execution-report-progress.json',value))
                    receipt['execution_reports']={'status':'complete','counts':reports['counts'],'validation':validation}
                if config.get('method_comparison_version') and all(receipt.get(name,{}).get('status','complete')=='complete' for name in ('action_targets','plan_relations')):
                    from .semantic_extraction import load_extraction
                    from .method_comparison import execute as execute_methods
                    document=load_extraction(run,root,action_target_version=config.get('action_target_version'),
                        plan_relation_version=config.get('plan_relation_version'))['document']
                    methods,validation=execute_methods(run,document,engine,version=config['method_comparison_version'],
                        progress=lambda value:write(root/'method-comparison-progress.json',{**value,'extraction_hash':digest(result)}))
                    receipt['method_comparison']={'status':'complete','counts':methods.get('counts',{}),'validation':validation}
                from .semantic_layers import execute_feedback,execute_requested
                layer=execute_feedback(run,result,engine,config.get('feedback_profile'))
                if layer:receipt['feedback_layer']=layer
                requested=execute_requested(run,result,engine,work_candidates,config.get('requested_profile'),config['context_policy'])
                if requested:receipt['requested_layer']=requested
            receipt['status'] = result['status']
            if receipt.get('requested_layer',{}).get('status')=='needs_work':receipt['status']='needs_layers'
            if receipt.get('action_targets',{}).get('status')=='needs_evidence':receipt['status']='needs_layers'
            if receipt.get('plan_relations',{}).get('status')=='needs_evidence':receipt['status']='needs_layers'
        except BudgetReached as exc:
            receipt['status'] = 'budget_reached'
            receipt['budget_stop'] = exc.reason
        except (Exception, KeyboardInterrupt):
            # Provider error strings can contain sensitive response text. Keep them
            # out of persistent receipts; already saved decisions remain resumable.
            receipt['status'] = 'interrupted'
            raise
        finally:
            receipt.update(provider_responses_this_execution=calls,
                           exact_reused_decisions=len(engine.reused_decisions),
                           cached_decisions_this_execution=len(engine.cached_decisions),
                           validated_decisions_this_execution=engine.calls,
                           candidate_calls_this_execution=getattr(candidates, 'generation_calls', 0)+getattr(work_candidates,'generation_calls',0),
                           budget_used=budget.used,
                           elapsed_seconds=round(time.monotonic() - start, 3))
            write(root / 'last-execution.json', receipt)
            write(root / 'executions' / f'{receipt["started_at_ns"]}.json', receipt)
        return status(root)


def audit(directory):
    with exclusive(directory) as root:
        config, run = load(root)
        selected = root / 'results' / f'{run["id"]}.json'
        checkpoint = root / 'checkpoints' / f'{run["id"]}.json'
        validations = {}
        for name, path in [('last_complete', selected), ('checkpoint', checkpoint)]:
            if path.exists():
                result = read(path)
                if 'status' not in result or result['status'] == 'interrupted':
                    validations[name] = {'status': 'interrupted; resume before full coverage audit'}
                else:
                    check_configuration(result, config, root)
                    validations[name] = audit_result(run, result, root)
        usage = Counter()
        for path in (root / 'decisions').glob('*.json'):
            saved = read(path)
            if path.stem != digest(saved['request']) or saved['answers'] != replay_decision(saved):
                raise InputError('Saved decision identity or raw argmax differs')
            usage.update(saved['response'].get('usage') or {})
        from .semantic_budget import summary
        report = {'schema': 'semantic-workspace-audit/1', 'run_id': run['id'],
                  'source_hash': config['source_hash'], 'validation': validations,
                  'saved_decisions': len(list((root / 'decisions').glob('*.json'))),
                  'validated_decision_usage': dict(usage),
                  'provider_usage': summary(root),
                  'limits': 'Software/source checks, not independent semantic accuracy. Usage covers validated decisions; wire responses and execution receipts retain failed attempts separately.'}
        if config.get('feedback_profile') and selected.exists():
            from .semantic_layers import audit_feedback
            report['feedback_layer']=audit_feedback(run,read(selected),root,config['feedback_profile'])
        if config.get('requested_profile') and selected.exists():
            from .semantic_layers import audit_requested
            report['requested_layer']=audit_requested(run,read(selected),root,config['requested_profile'],config['context_policy'])
        if config.get('action_target_version') and selected.exists():
            from .action_targets import audit as audit_targets,path_for
            result=read(selected);path=path_for(root,result,config['action_target_version'])
            if path.exists():report['action_targets']=audit_targets(run,result,read(path),root)
        if config.get('plan_relation_version') and selected.exists():
            from .plan_relations import audit as audit_plans,path_for
            result=read(selected);path=path_for(root,result,config['plan_relation_version'])
            if path.exists():report['plan_relations']=audit_plans(run,result,read(path),root)
        if config.get('execution_report_version'):
            from .execution_reports import audit as audit_reports,path_for
            path=path_for(root,run)
            if path.exists():report['execution_reports']=audit_reports(run,read(path),root)
        if config.get('method_comparison_version') and selected.exists():
            from .semantic_extraction import load_extraction
            from .method_comparison import base_document,audit as audit_methods
            document=load_extraction(run,root,action_target_version=config.get('action_target_version'),
                plan_relation_version=config.get('plan_relation_version'))['document']
            path=root/'results'/f'{digest(base_document(document))}.json'
            if path.exists():report['method_comparison']=audit_methods(run,document,read(path),root)
        write(root / 'audit.json', report)
        return report
