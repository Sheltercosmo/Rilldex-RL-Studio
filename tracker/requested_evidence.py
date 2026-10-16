"""Review saved requested terms against bounded source candidates, without inference.

This projects existing clause versions. It neither decomposes new prose nor
decides applicability, fulfillment, authorization or factual truth.
"""
from copy import deepcopy

from .schema import InputError, digest
from .semantic_extraction import checked_span
from . import source_evidence

VERSION = 'requested-evidence-review/2'
KINDS = {'requirement', 'requested_check', 'attributed_claim'}
BOUNDARY = ('Saved requested terms, not independently verified interpretations. Current means the latest '
            'recorded version before this contribution in the same recorded context. It does not mean '
            'applicable, authorized or fulfilled. Candidate retrieval never answers a condition; '
            'absence, copied history and the originating request are not proof of compliance.')


def validate(query):
    if not isinstance(query, dict) or set(query) - {'anchor', 'question_ids', 'source_types', 'strategy', 'limit', 'max_chars', 'cursor'}:
        raise InputError('Requested-term review needs an anchor and optional question_ids and retrieval options')
    source_evidence.validate({k: v for k, v in query.items() if k not in {'question_ids', 'source_types'}})
    kinds = query.get('source_types', ['action', 'feedback', 'prose'])
    if (not isinstance(kinds, list) or not kinds or any(k not in ('action', 'feedback', 'prose') for k in kinds)
            or len(kinds) != len(set(kinds))):
        raise InputError('Candidate record types must be unique action, feedback or prose values')
    ids = query.get('question_ids', [])
    if (not isinstance(ids, list) or len(ids) > min(8, query.get('limit', 8)) or
            any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids)):
        raise InputError('Select up to eight distinct recorded questions within the match limit')
    if query.get('cursor') and not ids:
        raise InputError('Continuation requires the original selected questions')


def review(run, graph, query):
    validate(query)
    if graph['source_hash'] != digest(run) or graph['run_id'] != run['id']:
        raise InputError('Requested-term graph belongs to a different source revision')
    anchor, start, end, prefix, scope, _, _ = source_evidence.visible_prefix(run, query['anchor'])
    visible = {e['id']: e for e in prefix}
    nodes = {n['id']: n for n in graph['nodes']}
    events = {e['id']: e for e in run['events']}
    records = []; excluded = []; blocked = set()

    def in_prefix(ref):
        event = checked_span(run, ref)
        shown = visible.get(event['id'])
        return (not event.get('copied_context') and shown is not None
                and ref['end'] <= len(shown['text']))

    for node in graph['nodes']:
        if node['kind'] != 'requested_work_version':
            continue
        record = deepcopy(node['properties']); owner = nodes.get(record.get('source_unit_id'))
        if owner is None or not owner.get('properties', {}).get('source'):
            raise InputError('Requested version has no source contribution')
        ref = owner['properties']['source']; event = checked_span(run, ref)
        # Out-of-scope and future versions cannot change a past review.
        if (event['trajectory_id'] != anchor['trajectory_id'] or event.get('context_id') != anchor.get('context_id')
                or event['index'] > anchor['index'] or event['id'] == anchor['id'] and ref['end'] > start):
            continue
        if (record.get('actor') != 'user' or event['actor'] != 'user' or record.get('trajectory_id') != event['trajectory_id'] or
                owner.get('trajectory_id') != event['trajectory_id'] or
                record.get('kind') not in {'work', 'condition'} or record.get('status') not in {'requested', 'withdrawn'}):
            raise InputError('Requested version attribution, kind or status differs')
        refs = [ref, *record.get('evidence', [])]
        for clause in record.get('clauses', []):
            if clause.get('kind') not in KINDS or not clause.get('evidence'):
                raise InputError('Requested clause needs a supported kind and exact evidence')
            refs.extend(clause['evidence'])
        if not record.get('evidence') or not all(in_prefix(r) for r in refs):
            excluded.append(dict(record_id=record['id'], version_id=record['version_id'],
                                 reason='source_not_established_in_review_prefix'))
            # Do not silently fall back to older terms after an unreadable revision.
            blocked.add(record['id']); continue
        records.append(dict(record=record, source=ref, position=[event['index'], ref['end']]))

    groups = {}
    for row in records:
        groups.setdefault(row['record']['id'], []).append(row)
    questions = []; history = []; missing = []
    for rid, rows in sorted(groups.items()):
        rows.sort(key=lambda r: (r['position'], r['record']['version_id']))
        if len({tuple(r['position']) for r in rows}) != len(rows):
            blocked.add(rid)
            excluded.append(dict(record_id=rid, reason='ambiguous_version_order'))
        latest = rows[-1]['record']
        for row in rows:
            record = row['record']
            status = ('unresolved' if rid in blocked else 'superseded' if record is not latest
                      else 'withdrawn' if record['status'] == 'withdrawn' else 'current')
            history.append(dict(record_id=rid, record_version_id=record['version_id'],
                lifecycle=status, text=record['text'], source=row['source'],
                clauses=deepcopy(record.get('clauses', []))))
            if status != 'current': continue
            if record['kind'] == 'work':
                contents = [dict(id=rid, version_id=record['version_id'], kind='work',
                                 text=record['text'], evidence=record['evidence'])]
            else:
                contents = record.get('clauses', [])
                if not contents:
                    missing.append(dict(record_id=rid, reason='condition_has_no_saved_clauses'))
            for clause in contents:
                questions.append(dict(id='term-'+digest([rid, clause['version_id']])[:24],
                    kind=clause['kind'], text=clause['text'], evidence=deepcopy(clause['evidence']),
                    record_id=rid, record_version_id=record['version_id'], clause_version_id=clause['version_id'],
                    originating_request_event_ids=sorted({r['event_id'] for r in clause['evidence']}),
                    verdict='not_assessed', retrieval_status='not_searched'))
    selected = query.get('question_ids', []); by_id = {q['id']: q for q in questions}
    if any(qid not in by_id for qid in selected):
        raise InputError('Selected question is unavailable at this cutoff; reload recorded terms')
    packet = None
    if selected:
        search_query = dict(strategy='source', limit=8, max_chars=16000)
        search_query.update({k: deepcopy(v) for k, v in query.items() if k not in {'question_ids', 'source_types'}})
        search_query['questions'] = [dict(id=qid, text=by_id[qid]['text'],
            source_types=query.get('source_types', ['action', 'feedback', 'prose'])) for qid in selected]
        packet = source_evidence.search(run, search_query)
        for result in packet['questions']:
            row = by_id[result['id']]; origin = set(row['originating_request_event_ids'])
            others = [eid for eid in result['retained_match_event_ids'] if eid not in origin]
            row.update(retrieval_status='candidates_to_review' if others else
                       'originating_request_only' if result['retained_match_event_ids'] else 'no_candidates_retained',
                       candidate_event_ids=others, search_status=result['status'])
    result = dict(schema=VERSION, run_id=run['id'], source_hash=digest(run), graph_id=graph['id'],
        anchor=dict(event_id=anchor['id'], start=start, end=end), scope=scope,
        questions=questions, selected_question_ids=deepcopy(selected), history=history,
        coverage=dict(recorded_terms_available=bool(records), excluded_versions=excluded,
                      unresolved_record_ids=sorted(blocked), missing_prerequisites=missing,
                      total_questions=len(questions), searched_questions=len(selected),
                      unsearched_question_ids=[q['id'] for q in questions if q['id'] not in selected]),
        evidence=packet, boundary=BOUNDARY)
    return dict(id='requested-evidence-'+digest(result), **result)
