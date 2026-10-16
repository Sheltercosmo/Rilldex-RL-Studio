"""An opt-in software-repair phase baseline, separate from semantic activities.

Inspired by Graphectory's history-sensitive phase mapping. This deliberately
supports fewer command forms: opaque dispatches remain visible gaps. It records
attempts, never successful edits, tests, private intent, or task completion.
"""
from collections import Counter, defaultdict
from pathlib import PurePosixPath
import re
import shlex

from .schema import InputError, digest

VERSION = 'repair-phases/1'
PROFILE = 'software_repair'
CATEGORIES = {
    'localization': {'label': 'Localize / reproduce', 'color': '#9682d6'},
    'patch': {'label': 'Patch attempt', 'color': '#d5ab54'},
    'validation': {'label': 'Check after patch attempt', 'color': '#74a787'},
    'submission': {'label': 'Submit attempt', 'color': '#7c899b'},
    'unknown': {'label': 'Unclassified dispatch', 'color': '#c4c9d2'},
}
LIMIT = ('Experimental command-and-history rules for explicitly identified software-repair tasks. '
         'Phases describe dispatched operations, not semantic unit activities or established intent. '
         'A patch/test/submit attempt does not prove a change, passing test, or completion. '
         'Filename conventions are heuristic. Unsupported commands remain gaps; gaps are never bridged. '
         'Only recorded action events are counted; unparsed prose is outside this action-level baseline.')
SOURCE_EXTENSIONS = {'.py', '.pyi', '.js', '.jsx', '.ts', '.tsx', '.java', '.c', '.cc', '.cpp', '.h',
                     '.hpp', '.rs', '.go', '.rb', '.php', '.cs', '.swift', '.kt', '.scala', '.sh'}
EDIT_TOOLS = {'str_replace_editor', 'str_replace_based_edit_tool', 'file_editor'}


def target_role(path):
    if not isinstance(path, str) or not path.strip():
        return 'unknown'
    p = PurePosixPath(path.replace('\\', '/').lower())
    if (set(p.parts) & {'test', 'tests', '__tests__'} or
            re.match(r'^(test_|repro(?:duce|duction)?(?:_|\.|$))', p.name) or
            re.search(r'(?:_test|\.test|\.spec)\.[^.]+$', p.name)):
        return 'test'
    return 'source' if p.suffix in SOURCE_EXTENSIONS else 'unknown'


def operation(event):
    """Parse one native dispatch without executing it or inspecting future text."""
    args = event.get('arguments') or {}
    if not isinstance(args, dict):
        return {'kind': 'unknown', 'rule': 'opaque_arguments'}
    tool = event.get('tool')
    if tool in EDIT_TOOLS:
        command = args.get('command')
        path = args.get('path')
        return editor(command, path)
    text = args.get('command', event.get('text', ''))
    if tool not in {'shell', 'bash', 'terminal', 'execute', 'exec_command', 'run', None} or not isinstance(text, str):
        return {'kind': 'unknown', 'rule': 'unsupported_tool'}
    # Quoted multiline editor contents are one argument. Outside quotes, shell
    # control operators/newlines represent compound dispatches and stay opaque.
    if re.search(r'`|\$\(', text):
        return {'kind': 'unknown', 'rule': 'shell_substitution'}
    try:
        lexer = shlex.shlex(text.strip(), posix=True, punctuation_chars=';&|<>\n')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        lexer.commenters = ''
        tokens = list(lexer)
    except ValueError:
        return {'kind': 'unknown', 'rule': 'unparsed_shell'}
    if not tokens or any(t and all(c in ';&|<>\n' for c in t) for t in tokens):
        return {'kind': 'unknown', 'rule': 'compound_or_empty_dispatch'}
    name = PurePosixPath(tokens[0]).name
    if name in EDIT_TOOLS:
        return editor(tokens[1] if len(tokens) > 1 else None, tokens[2] if len(tokens) > 2 else None)
    if tokens == ['submit']:
        return {'kind': 'submission', 'rule': 'explicit_submit'}
    if name == 'pytest' or name in {'python', 'python3'} and tokens[1:3] == ['-m', 'pytest']:
        # Unknown options may run arbitrary plugins, but this is still a test
        # runner invocation, not proof that it ran or passed tests.
        return {'kind': 'test', 'rule': 'test_runner_dispatch'}
    if name in {'python', 'python3'} and len(tokens) >= 2 and target_role(tokens[1]) == 'test':
        return {'kind': 'test', 'rule': 'test_script_filename', 'target': tokens[1]}
    if name in {'cat', 'head', 'tail', 'nl', 'ls', 'grep', 'rg', 'open', 'find_file', 'search_file', 'search_dir'}:
        # These forms cannot modify files by themselves. Do not treat generic
        # find/awk/sed, python, redirections or arbitrary scripts as read-only.
        paths = [t for t in tokens[1:] if not t.startswith('-') and target_role(t) != 'unknown']
        role = 'test' if paths and all(target_role(p) == 'test' for p in paths) else 'unknown'
        return {'kind': 'read', 'rule': 'read_dispatch', 'target_role': role}
    return {'kind': 'unknown', 'rule': 'unsupported_command'}


def editor(command, path):
    if not isinstance(path, str) or not path.strip():
        return {'kind': 'unknown', 'rule': 'missing_editor_target'}
    role = target_role(path)
    if command == 'view':
        return {'kind': 'read', 'rule': 'editor_view', 'target': path, 'target_role': role}
    if command in {'str_replace', 'create', 'insert', 'undo_edit'} and role != 'unknown':
        return {'kind': 'test_edit' if role == 'test' else 'patch', 'rule': 'editor_target_filename',
                'target': path, 'target_role': role}
    return {'kind': 'unknown', 'rule': 'unsupported_editor_operation_or_target', 'target': path}


def project(run, graph_id):
    applicable = run.get('metadata', {}).get('task_family') == PROFILE
    records = []
    histories = defaultdict(lambda: {'patch': None, 'opaque': False})
    actions = [e for e in sorted(run['events'], key=lambda e: e['index'])
               if e['kind'] == 'action' and e.get('actor') == 'agent' and not e.get('copied_context')]
    batches = Counter((e['trajectory_id'], e.get('parent_id')) for e in actions if e.get('parent_id'))
    if applicable:
        for e in actions:
            history = histories[e['trajectory_id']]
            op = operation(e)
            if e.get('batch_size', 0) > 1 or e.get('parent_id') and batches[(e['trajectory_id'], e['parent_id'])] > 1:
                op = {'kind': 'unknown', 'rule': 'unordered_batch'}
            kind = op['kind']
            contextual = kind in {'test', 'test_edit'} or kind == 'read' and op.get('target_role') == 'test'
            if contextual:
                phase = 'validation' if history['patch'] else 'unknown' if history['opaque'] else 'localization'
            else:
                phase = {'read': 'localization', 'patch': 'patch', 'submission': 'submission'}.get(kind, 'unknown')
            records.append({'event_id': e['id'], 'event_index': e['index'], 'trajectory_id': e['trajectory_id'],
                            'source_pointer': e['source_pointer'], 'text': e['text'], 'phase': phase,
                            'operation': op, 'prior_patch_event_id': history['patch'],
                            'history_has_unclassified_dispatch': history['opaque'],
                            'rule': 'ambiguous_prior_patch_history' if contextual and phase == 'unknown' else op['rule']})
            if kind == 'patch':
                history['patch'] = e['id']
            if kind == 'unknown':
                history['opaque'] = True
    lanes = defaultdict(list)
    for r in records:
        lane = lanes[r['trajectory_id']]
        if not lane or lane[-1]['phase'] != r['phase']:
            lane.append({'phase': r['phase'], 'event_ids': []})
        lane[-1]['event_ids'].append(r['event_id'])
    pairs = []
    for tid, blocks in lanes.items():
        for a, b in zip(blocks, blocks[1:]):
            if 'unknown' not in {a['phase'], b['phase']}:
                pairs.append({'from': a['phase'], 'to': b['phase'], 'trajectory_id': tid,
                              'from_event_id': a['event_ids'][-1], 'to_event_id': b['event_ids'][0]})
    counts = {k: sum(r['phase'] == k for r in records) for k in CATEGORIES}
    value = {'schema': VERSION, 'profile': PROFILE, 'run_id': run['id'], 'source_hash': digest(run),
             'graph_id': graph_id, 'applicable': applicable, 'activation': 'metadata.task_family=software_repair',
             'categories': CATEGORIES, 'records': records, 'paths': [{'trajectory_id': k, 'blocks': v} for k, v in lanes.items()],
             'pairs': pairs, 'counts': counts, 'action_count': len(records),
             'coverage': (len(records) - counts['unknown']) / len(records) if records else None,
             'limit': LIMIT}
    return {'id': 'repair-phases-' + digest(value), **value}


def compare(values, focus, reference):
    if len({v['run_id'] for v in values}) != len(values):
        raise InputError('Duplicate repair-phase rollout')
    groups = {}
    for name, ids in [('focus', focus), ('reference', reference)]:
        rows = [v for v in values if v['run_id'] in ids and v['applicable']]
        measured = [v for v in rows if v['action_count']]
        groups[name] = {'rollouts': len(ids), 'applicable': len(rows), 'measured': len(measured),
                        'mean_action_share': {k: sum(v['counts'][k] / v['action_count'] for v in measured) / len(measured)
                                              if measured else None for k in CATEGORIES},
                        'action_counts': {k: sum(v['counts'][k] for v in rows) for k in CATEGORIES},
                        'run_ids': [v['run_id'] for v in measured]}
    return {'schema': VERSION, 'groups': groups, 'categories': CATEGORIES, 'records': values,
            'definition': 'Equal-weight mean per-rollout action shares, including unclassified dispatches. '
                          'Transition positions count consecutive phase blocks, not elapsed time. ' + LIMIT}
