"""Producer-reported evaluations, separate from agent-visible source and rewards.

Content identity preserves a report; it does not authenticate its author or
prove that the declared artifacts were used. No commands or URLs are executed.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re

from .schema import InputError, digest, dumps

VERSION = 'evaluation-receipt/1'
INPUTS = ('task', 'criterion', 'artifact', 'evaluator', 'environment', 'output_boundary')
MATCH_INPUTS = ('task', 'criterion', 'artifact', 'environment', 'output_boundary')
COMPARISON_VERSION = 'evaluation-comparison/2'
PURPOSES = {'reward', 'independent_check', 'repair_check'}
EXECUTIONS = {'completed', 'error', 'incomplete', 'not_run'}
VERDICTS = {'passed', 'failed', 'unknown'}
CITATION_ROLES = {'requirement', 'implementation', 'action', 'observation', 'context'}
CITATION_BASIS = 'source-event-text/unicode-codepoints/1'
CITATION_FIELDS = ('role', 'run_id', 'source_hash', 'event_id', 'source_pointer', 'start', 'end', 'text', 'basis')
BOUNDARY = ('Producer-reported evaluation, outside the agent-visible trace. Hashes pin declared inputs; '
            'Rilldex has not executed the check, verified artifact contents or authenticated independence. '
            'Disagreement is not a reward-hacking verdict.')
VIEW_SQL = """SELECT id evaluation_id,run_id,received_at,
    json_extract(document,'$.source_hash') source_hash,
    json_extract(document,'$.label') label,json_extract(document,'$.producer') producer,
    json_extract(document,'$.purpose') purpose,json_extract(document,'$.performed_at') performed_at,
    json_extract(document,'$.execution') execution,json_extract(document,'$.verdict') verdict,
    json_extract(document,'$.score') score,document receipt_json FROM evaluation_receipts"""
EMPTY_SQL = 'SELECT '+','.join('NULL '+name for name in (
    'evaluation_id','run_id','received_at','source_hash','label','producer','purpose',
    'performed_at','execution','verdict','score','receipt_json'))+' WHERE 0'


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS evaluation_receipts('
              'id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),'
              'document TEXT NOT NULL,received_at TEXT NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS evaluation_receipt_run ON evaluation_receipts(run_id,received_at,id)')


def fields(raw, required, optional=()):
    if not isinstance(raw, dict) or set(raw) - set(required) - set(optional) or set(required) - set(raw):
        raise InputError('Unexpected or missing evaluation fields')


def text(value, name, limit=240):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise InputError('Invalid evaluation ' + name)


def identity(value, name):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise InputError('Use a lowercase SHA-256 for ' + name)


def finite(value):
    try: return type(value) in (int, float) and math.isfinite(value)
    except OverflowError: return False


def validate(raw):
    fields(raw, ('schema', 'label', 'producer', 'performed_at', 'run_id', 'source_hash',
                 'purpose', 'inputs', 'execution', 'verdict', 'score', 'summary', 'evidence'), ('source_citations',))
    if raw['schema'] != VERSION: raise InputError('Unsupported evaluation receipt')
    for name in ('label', 'producer', 'run_id'): text(raw[name], name)
    text(raw['summary'], 'summary', 6000)
    identity(raw['source_hash'], 'source_hash')
    if not isinstance(raw['purpose'], str) or raw['purpose'] not in PURPOSES:
        raise InputError('Unknown evaluation purpose')
    if not isinstance(raw['execution'], str) or raw['execution'] not in EXECUTIONS:
        raise InputError('Unknown evaluation execution status')
    if not isinstance(raw['verdict'], str) or raw['verdict'] not in VERDICTS:
        raise InputError('Unknown evaluation verdict')
    if raw['execution'] != 'completed' and (raw['verdict'] != 'unknown' or raw['score'] is not None):
        raise InputError('An unfinished or errored evaluation has unknown verdict and no score')
    if raw['score'] is not None and not finite(raw['score']):
        raise InputError('Evaluation score must be finite or null')
    if raw['performed_at'] is not None:
        text(raw['performed_at'], 'performed_at', 64)
        try: stamp = datetime.fromisoformat(raw['performed_at'].replace('Z', '+00:00'))
        except ValueError as error: raise InputError('Use an ISO timestamp with timezone') from error
        if stamp.tzinfo is None: raise InputError('Evaluation time requires a timezone')
    # Earlier receipts lacked criterion scope. Preserve their report identity;
    # comparisons mark that scope missing rather than equating arbitrary checks.
    if not isinstance(raw['inputs'], dict) or set(raw['inputs']) not in (set(INPUTS), set(INPUTS)-{'criterion'}):
        raise InputError('Unexpected or missing evaluation input fields')
    for role, value in raw['inputs'].items():
        if value is None: continue
        fields(value, ('label', 'sha256'))
        text(value['label'], role)
        identity(value['sha256'], role)
    if not isinstance(raw['evidence'], list) or len(raw['evidence']) > 16:
        raise InputError('Attach at most 16 bounded evidence excerpts')
    for item in raw['evidence']:
        fields(item, ('label', 'text'))
        text(item['label'], 'evidence label')
        text(item['text'], 'evidence text', 12000)
    citations = raw.get('source_citations', [])
    if not isinstance(citations, list) or len(citations) > 32:
        raise InputError('Attach at most 32 source citations')
    seen = set()
    for item in citations:
        validate_citation(item)
        if item['run_id'] != raw['run_id'] or item['source_hash'] != raw['source_hash']:
            raise InputError('Source citation belongs to another rollout revision')
        key = digest(item)
        if key in seen: raise InputError('Duplicate source citation')
        seen.add(key)
    if len(dumps(raw).encode('utf-8')) > 256000: raise InputError('Evaluation receipt exceeds 256 KB')


def validate_citation(item):
    fields(item, CITATION_FIELDS)
    if not isinstance(item['role'], str) or item['role'] not in CITATION_ROLES:
        raise InputError('Unknown source citation role')
    if item['basis'] != CITATION_BASIS: raise InputError('Unknown source citation offset basis')
    for name in ('run_id', 'event_id'): text(item[name], name)
    # Some importers use an empty JSON pointer for their root object.
    if not isinstance(item['source_pointer'], str) or len(item['source_pointer']) > 4096:
        raise InputError('Invalid source citation pointer')
    identity(item['source_hash'], 'source citation')
    text(item['text'], 'source citation text', 12000)
    if (type(item['start']) is not int or type(item['end']) is not int
            or not 0 <= item['start'] < item['end'] or item['end'] - item['start'] != len(item['text'])):
        raise InputError('Invalid source citation boundaries')


def cite_source(run, event_id, *, role, quote=None, start=None, end=None):
    """Construct an exact citation; its role is the caller's interpretation."""
    event = next((e for e in run['events'] if e['id'] == event_id), None)
    if event is None: raise InputError('Unknown source citation event')
    if quote is not None:
        if start is not None or end is not None: raise InputError('Use a unique quote or explicit source offsets')
        text(quote, 'source quote', 12000)
        start = event['text'].find(quote)
        if start < 0: raise InputError('Quote is absent from the source event')
        if event['text'].find(quote, start + 1) >= 0:
            raise InputError('Quote occurs more than once; use explicit source offsets')
        end = start + len(quote)
    else:
        start = 0 if start is None else start
        end = len(event['text']) if end is None else end
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(event['text']):
        raise InputError('Invalid source citation boundaries')
    value = dict(role=role, run_id=run['id'], source_hash=digest(run), event_id=event_id,
                 source_pointer=event['source_pointer'], start=start, end=end,
                 text=event['text'][start:end], basis=CITATION_BASIS)
    validate_citation(value)
    return value


def check_citations(run, raw):
    from .semantic_extraction import checked_span
    for item in raw.get('source_citations', []):
        checked_span(run, item)


def receive(store, raw):
    validate(raw)
    identifier = 'evaluation-' + digest(raw)
    with store.connect() as c:
        row = c.execute('SELECT document FROM runs WHERE id=?', (raw['run_id'],)).fetchone()
        run = json.loads(row[0]) if row else None
        if run is None or digest(run) != raw['source_hash']:
            raise InputError('Evaluation must bind an available exact rollout source revision')
        check_citations(run, raw)
        c.execute('INSERT OR IGNORE INTO evaluation_receipts VALUES(?,?,?,?)',
                  (identifier, raw['run_id'], dumps(raw), datetime.now(timezone.utc).isoformat()))
    return read(store, identifier)


def decode(identifier, document):
    raw = json.loads(document)
    validate(raw)
    if identifier != 'evaluation-' + digest(raw): raise InputError('Evaluation receipt identity mismatch')
    return dict(id=identifier, **raw)


def read(store, identifier):
    text(identifier, 'identity', 100)
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evaluation_receipts'").fetchone():
            raise InputError('Evaluation receipt not found')
        row = c.execute('SELECT document FROM evaluation_receipts WHERE id=?', (identifier,)).fetchone()
    if not row: raise InputError('Evaluation receipt not found')
    return decode(identifier, row[0])


def listing(store, *, run_id, limit=50, offset=0):
    text(run_id, 'run identity')
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise InputError('Invalid evaluation page')
    with store.connect() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evaluation_receipts'").fetchone()
        rows = c.execute('SELECT id,document FROM evaluation_receipts WHERE run_id=? '
                         'ORDER BY received_at DESC,id LIMIT ? OFFSET ?', (run_id, limit + 1, offset)).fetchall() if exists else []
    return dict(schema=VERSION, receipts=[decode(r[0], r[1]) for r in rows[:limit]],
                more=len(rows) > limit, limit=limit, offset=offset, boundary=BOUNDARY)


def resolve(store, reference):
    fields(reference, ('kind', 'id'))
    if reference['kind'] != 'evaluation': raise InputError('Expected evaluation reference')
    doc = read(store, reference['id'])
    return dict(kind='evaluation', id=doc['id'], title=doc['label'], run_id=doc['run_id'],
                receipt=doc, boundary=BOUNDARY)


def compare(left, right):
    """Compare explicit receipts; no automatic newest/best evaluator selection."""
    missing = [role for role in INPUTS if left['inputs'].get(role) is None or right['inputs'].get(role) is None]
    different = [role for role in MATCH_INPUTS if role not in missing and
                 left['inputs'][role]['sha256'] != right['inputs'][role]['sha256']]
    same_source = (left['run_id'], left['source_hash']) == (right['run_id'], right['source_hash'])
    if not same_source: status = 'different_source'
    elif 'error' in (left['execution'], right['execution']): status = 'execution_error'
    elif different: status = 'different_inputs'
    elif missing: status = 'missing_inputs'
    elif any(r['execution'] != 'completed' or r['verdict'] == 'unknown' for r in (left, right)):
        status = 'unresolved'
    else: status = 'agreement' if left['verdict'] == right['verdict'] else 'disagreement'
    return dict(schema=COMPARISON_VERSION, left=left['id'], right=right['id'], status=status, missing_inputs=missing,
                different_inputs=different,
                evaluator_changed=None if 'evaluator' in missing else
                left['inputs']['evaluator']['sha256'] != right['inputs']['evaluator']['sha256'],
                observations=[{k: deepcopy(r[k]) for k in ('id', 'label', 'purpose', 'execution', 'verdict', 'score', 'performed_at')}
                              for r in (left, right)], boundary=BOUNDARY)


def compare_ids(store, ids):
    if (not isinstance(ids, list) or not 2 <= len(ids) <= 8 or
            any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids)):
        raise InputError('Select two to eight distinct evaluation receipts')
    with store.read_snapshot() as saved:
        rows = [read(saved, i) for i in ids]
    return dict(schema=COMPARISON_VERSION, records=rows,
                pairs=[compare(a, b) for i, a in enumerate(rows) for b in rows[i + 1:]],
                boundary=BOUNDARY, model_calls=0)


def attached_comparisons(evidence):
    rows = [e['receipt'] for e in evidence if e['kind'] == 'evaluation']
    return [compare(a, b) for i, a in enumerate(rows) for b in rows[i + 1:]]
