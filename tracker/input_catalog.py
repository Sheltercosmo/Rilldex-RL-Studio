"""One catalog for record shapes and file layouts, independent of RL framework.

These describe readers, not claims that a trainer has been run end to end.
The native layout is deliberately narrow because it joins framework sidecars.
"""
from .adapters import FORMATS

GROUPS = [
    ('Common records', [
        ('chat-messages', 'Conversation · messages, calls and results'),
        ('environment-episode', 'Environment episode · actions and observations'),
        ('generation', 'Generation · prompt and completion'),
        ('atif', 'ATIF · structured agent trajectory'),
    ]),
    ('Framework exports', [
        ('verl-generation', 'verl · generation export'),
        ('slime-debug', 'slime · debug record'),
        ('harbor', 'Harbor · trajectory'),
        ('swe-agent', 'SWE-agent · trajectory'),
        ('mini-swe-agent', 'mini-SWE-agent · saved history'),
        ('tau-bench', 'τ-bench · text simulation'),
    ]),
    ('Dataset and bundle readers', [
        ('swe-rl', 'SWE RL'), ('nebius', 'Nebius'),
        ('nebius-openhands', 'Nebius OpenHands'),
        ('agent-process-bench', 'AgentProcessBench'), ('devai', 'DevAI'),
        ('harbor-bundle', 'Harbor bundle'),
    ]),
]


def catalog():
    formats = [{'id': 'auto', 'label': 'Detect from record contents', 'group': '',
                'collection_modes': ['exports', 'snapshots', 'native']}]
    for group, entries in GROUPS:
        for key, label in entries:
            formats.append({'id': key, 'label': label, 'group': group,
                            'collection_modes': ['exports', 'snapshots'] +
                            (['native'] if key in {'harbor', 'swe-agent'} else [])})
    # A new decoder cannot silently disappear from setup or import controls.
    known = {row['id'] for row in formats}
    formats.extend({'id': key, 'label': key, 'group': 'Additional readers',
                    'collection_modes': ['exports', 'snapshots']}
                   for key in FORMATS if key not in known)
    return {'formats': formats, 'default_collection_mode': 'exports', 'modes': [
        {'id': 'exports', 'label': 'JSONL · appended records or revisions',
         'detail': 'Each line contains one rollout record, or an explicit rollout/revision/state envelope. Existing and newly appended lines are collected. Token chunks need assembly; multi-rollout bundles use Import files.'},
        {'id': 'snapshots', 'label': 'JSON · one updating file per rollout',
         'detail': 'One conversation, environment episode, generation or supported trajectory per file. Changes create revisions; partial JSON waits. Keep relative filenames stable across restarts. Multi-rollout bundles use Import files.'},
        {'id': 'native', 'label': 'Multi-file job · Harbor / SWE-agent',
         'detail': 'Specialized reader for trajectory files plus companion results. This layout supports Harbor and SWE-agent; the JSON and JSONL layouts accept the broader record catalog.'},
    ]}
