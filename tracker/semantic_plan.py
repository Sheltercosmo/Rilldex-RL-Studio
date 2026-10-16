"""Local plan content: intended stages and expressed organization, never progress.

This is part of a coherent content candidate after base activity selection.
Cross-unit realization, revision and completion require later evidence.
"""
from .schema import InputError

VERSION = 'local-plan-content/1'
CONTRACT = {
    'schema': VERSION,
    'organization': 'staged or strategy. Staged means at least two substantive intended stages; a strategy can organize work without enumerated stages.',
    'steps': 'List only stages actually expressed. Each has a unique local id, a readable text, a target (readable text), and exact evidence. Keep rationale and purpose with their stage. Do not manufacture a stage per sentence.',
    'links': 'Only expressed organization: {from, to, kind: precedes|requires, evidence}. Precedes is stated order; requires is a prerequisite. Sequence does not alone establish a prerequisite. Requires points from the dependent to its prerequisite.',
    'completion_criterion': 'An explicit criterion for the plan outcome: {status: expressed, text, evidence} or {status: not_expressed}. A goal is not automatically a check or verification procedure.',
    'boundary': 'These are intended stages, not executed or completed tasks. No progress/status field, cross-unit identity or retrospective evidence. An ordinary local adjustment remains Orient and never reaches this contract.'
}


def validate_plan(value, anchor):
    def require(ok, message):
        if not ok:
            raise InputError('Plan content: '+message)
    def cited(item):
        require(isinstance(item, dict) and isinstance(item.get('text'), str) and bool(item['text'].strip()), 'readable meaning required')
        require(isinstance(item.get('evidence'), list) and bool(item['evidence']), 'evidence required')
        for ref in item['evidence']:
            anchor(ref)
    require(isinstance(value, dict) and set(value) == {'schema','organization','steps','links','completion_criterion'}, 'unexpected or missing fields')
    require(value['schema'] == VERSION and value['organization'] in {'staged','strategy'}, 'unknown contract or organization')
    steps, links = value['steps'], value['links']
    require(isinstance(steps, list) and isinstance(links, list), 'steps and links must be lists')
    require(value['organization'] != 'staged' or len(steps) >= 2, 'staged plan needs at least two stages')
    ids = set()
    for step in steps:
        require(isinstance(step, dict) and set(step) == {'id','text','target','evidence'}, 'stage fields differ or claim progress')
        require(isinstance(step['id'], str) and step['id'] and step['id'] not in ids, 'unique stage identity required')
        ids.add(step['id']);cited(step)
        require(isinstance(step['target'], str) and bool(step['target'].strip()), 'readable stage target required')
    graph = {key:set() for key in ids}; seen=set()
    for link in links:
        require(isinstance(link, dict) and set(link) == {'from','to','kind','evidence'}, 'link fields differ')
        a,b,k = link['from'],link['to'],link['kind']
        require(a in ids and b in ids and a != b and k in {'precedes','requires'}, 'invalid organization endpoint/type')
        require((a,b,k) not in seen, 'duplicate organization link');seen.add((a,b,k))
        require(isinstance(link['evidence'], list) and bool(link['evidence']), 'organization needs evidence')
        for ref in link['evidence']:anchor(ref)
        # Normalize prerequisite relations to execution order for cycle checks.
        graph[a if k=='precedes' else b].add(b if k=='precedes' else a)
    def visit(node, stack, done):
        require(node not in stack, 'cyclic stage order')
        if node in done:return
        for nxt in graph[node]:visit(nxt, stack|{node}, done)
        done.add(node)
    done=set()
    for node in graph:visit(node,set(),done)
    criterion = value['completion_criterion']
    require(isinstance(criterion, dict), 'criterion must state missingness')
    if criterion.get('status') == 'not_expressed':
        require(set(criterion) == {'status'}, 'absent criterion has a value')
    else:
        require(set(criterion) == {'status','text','evidence'} and criterion['status'] == 'expressed', 'invalid criterion')
        cited(criterion)
    return value
