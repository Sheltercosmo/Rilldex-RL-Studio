"""Bounded earlier-source retrieval. Matches are evidence candidates, not links.

The corpus is built from the visible prefix before the selected contribution,
so future text and parallel trajectories cannot change retrieval or BM25 ranks.
Returned offsets always refer to original text; encoded media is not indexed.
"""
from copy import deepcopy
import re
import sqlite3

from .capabilities import links
from .feedback_retrieval import terms
from .readable_context import DATA_URI, merged, subtract
from .schema import InputError, digest

VERSION = 'source-evidence-search/7'
SEARCH_CHARS = 320
SEARCH_STRIDE = 256
CONTEXT_CHARS = 1200
BOUNDARY = ('Lexical candidates and recorded context only. A match is not a semantic '
            'relationship, verified claim, causal explanation or complete search. '
            'Omitted evidence and paraphrases can change the interpretation. '
            'No model calls or new behavior annotations are made.')


def index_text(text):
    """Split code identifiers for matching without changing source offsets."""
    def expand(match):
        original = match.group(0)
        split = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', original)
        split = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', split)
        return original if split == original else original + ' ' + split
    return re.sub(r'[^\W_]+', expand, text)


def search_chunks(text):
    for first, last in subtract([(0, len(text))],
                               [(m.start(), m.end()) for m in DATA_URI.finditer(text)]):
        for start in range(first, last, SEARCH_STRIDE):
            end = min(last, start + SEARCH_CHARS)
            if text[start:end].strip():
                yield start, end, text[start:end], first, last
            if end == last: break


def context_range(start, end, first, last):
    """Return surrounding original text, constrained to its readable interval."""
    left = max(first, start - (CONTEXT_CHARS - (end-start)) // 2)
    right = min(last, left + CONTEXT_CHARS)
    return max(first, right-CONTEXT_CHARS), right


def validate(query):
    if (not isinstance(query, dict) or 'anchor' not in query or
            set(query) - {'anchor', 'text', 'questions', 'strategy', 'limit', 'max_chars', 'cursor'}):
        raise InputError('Evidence search requires an anchor and optional text, questions, strategy, limit, max_chars and cursor')
    anchor = query['anchor']
    if (not isinstance(anchor, dict) or set(anchor) - {'event_id', 'start', 'end'} or
            not isinstance(anchor.get('event_id'), str) or not anchor['event_id']):
        raise InputError('Select an exact source event and optional character range')
    for key in ('start', 'end'):
        if key in anchor and (type(anchor[key]) is not int or anchor[key] < 0):
            raise InputError('Source character boundaries must be nonnegative integers')
    if 'text' in query and (not isinstance(query['text'], str) or not query['text'].strip() or len(query['text']) > 6000):
        raise InputError('Search text must contain 1–6000 characters')
    if query.get('strategy', 'source') not in ('source', 'source_and_calls'):
        raise InputError('Evidence strategy must be source or source_and_calls')
    if 'cursor' in query:
        cursor=query['cursor']
        if (not isinstance(cursor,dict) or set(cursor)!={'search_id','offset'} or
                not isinstance(cursor['search_id'],str) or not re.fullmatch('evidence-search-[0-9a-f]{64}',cursor['search_id']) or
                type(cursor['offset']) is not int or cursor['offset']<1):
            raise InputError('Use the next_cursor returned by the same evidence search')
    for key, default, low, high in [('limit', 8, 1, 20), ('max_chars', 16000, 2000, 64000)]:
        value = query.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise InputError(f'{key} must be an integer from {low} to {high}')
    if 'questions' in query:
        questions = query['questions']
        if not isinstance(questions, list) or not 1 <= len(questions) <= min(8, query.get('limit', 8)):
            raise InputError('Supply 1–8 evidence questions, no more than the match limit')
        ids = set()
        for question in questions:
            if (not isinstance(question, dict) or set(question) - {'id', 'text', 'source_types'} or
                    not isinstance(question.get('id'), str) or
                    not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', question['id']) or
                    question['id'] in ids):
                raise InputError('Evidence questions need unique simple IDs of 1–80 characters')
            ids.add(question['id'])
            if (not isinstance(question.get('text'), str) or not question['text'].strip() or
                    len(question['text']) > 2000 or DATA_URI.search(question['text'])):
                raise InputError('Each evidence question needs 1–2000 readable characters')
            kinds = question.get('source_types', ['action', 'feedback', 'prose'])
            if (not isinstance(kinds, list) or not kinds or
                    any(k not in ('action', 'feedback', 'prose') for k in kinds) or
                    len(kinds) != len(set(kinds))):
                raise InputError('Question source_types must be unique action, feedback or prose values')
        if sum(len(q['text']) for q in questions) > 6000:
            raise InputError('Evidence questions may contain at most 6000 characters in total')


def source_type(event):
    if event['kind'] in ('action', 'feedback'):
        return event['kind']
    return 'prose'


def query_tokens(text):
    return [term for term in terms(index_text(DATA_URI.sub(' ', text)))
            if term not in {'what', 'which', 'where', 'when', 'how', 'why'}]


def diverse(candidates, lookup, limit):
    """Preserve native source-type diversity, without inferring activities."""
    selected = set()
    for kind in ('action', 'feedback', 'prose'):
        matching = [hit for hit in candidates if source_type(lookup[hit['event_id']]) == kind]
        selected.update(hit['event_id'] for hit in matching[:min(2, limit // 3)])
    for hit in candidates:
        if len(selected) >= limit: break
        selected.add(hit['event_id'])
    return [hit for hit in candidates if hit['event_id'] in selected]


def dispatch_groups(run, eligible, anchor):
    """Recorded message membership, never execution order or result attribution.

    Empty message envelopes still identify a group. Only readable actions from
    the already validated visible prefix can be expanded; parent metadata must
    obey that same scope and precede each action. No sibling at the anchor's
    parallel dispatch boundary is admitted here.
    """
    envelopes = {e['id']: e for e in run['events']}
    groups = {}
    for action in eligible:
        if action['kind'] != 'action' or action.get('copied_context'):
            continue
        parent = envelopes.get(action.get('parent_id'))
        if not parent or parent['kind'] not in {'message', 'reasoning'} or parent['actor'] != action['actor']:
            continue
        if (parent.get('copied_context') or parent.get('order_known') is False or
                parent.get('agent_visibility') == 'not_established' or
                parent['trajectory_id'] != action['trajectory_id'] or
                parent.get('context_id') != action.get('context_id') or
                not parent['index'] < action['index'] < anchor['index']):
            continue
        groups.setdefault(parent['id'], []).append(action['id'])
    return {action: dict(parent_id=parent, action_ids=members)
            for parent, members in groups.items() if len(members) > 1
            for action in members}


def visible_prefix(run, ref):
    """Shared exact cutoff for retrieval and source-bound review projections."""
    validate({'anchor': ref})
    events = {e['id']: e for e in run['events']}
    anchor = events.get(ref['event_id'])
    if not anchor:
        raise InputError('Unknown evidence-search anchor')
    start, end = ref.get('start', 0), ref.get('end', len(anchor['text']))
    if not 0 <= start < end <= len(anchor['text']):
        raise InputError('Anchor range is empty or outside the source')
    def visible(e):
        return not (e['kind'].startswith('external_') or e.get('agent_visibility') == 'not_established')
    if not visible(anchor):
        raise InputError('Anchor is not established as agent-visible')
    if DATA_URI.search(anchor['text'][start:end]):
        raise InputError('Select readable anchor text; encoded media is not inspected')

    # Same-event earlier characters may be relevant to a selected later unit.
    # Exclude the anchor itself and sibling dispatches in a parallel call batch.
    def sibling(e):
        return e['kind'] == anchor['kind'] == 'action' and e['id'] != anchor['id'] and (
            bool(e.get('parent_id')) and e.get('parent_id') == anchor.get('parent_id') or
            e.get('source_message_index') is not None and
            e.get('source_message_index') == anchor.get('source_message_index'))
    eligible = []
    excluded = []; scope_excluded = []
    scope = dict(trajectory_id=anchor['trajectory_id'], context_id=anchor.get('context_id'),
        context_boundary='recorded' if anchor.get('context_id') is not None else 'unspecified',
        anchor_order_established=anchor.get('order_known') is not False,
        earlier_records='available' if anchor.get('order_known') is not False else 'unavailable',
        boundary='Earlier agent-visible records in the same trajectory and recorded context only. '
                 'Missing context IDs share an unspecified scope; omitted session boundaries cannot be verified. '
                 'Unresolved anchor order permits only earlier characters in that same record. '
                 'Visible copied history is labeled source text, not evidence of a new execution.')
    for original in sorted(run['events'], key=lambda e: e['index']):
        if original['index'] > anchor['index'] or original['trajectory_id'] != anchor['trajectory_id']:
            continue
        if original.get('context_id') != anchor.get('context_id'):
            scope_excluded.append(dict(event_id=original['id'],reason='different_recorded_context')); continue
        if original['id'] != anchor['id'] and (original.get('order_known') is False or
                anchor.get('order_known') is False or original['index'] == anchor['index']):
            scope_excluded.append(dict(event_id=original['id'],reason='unresolved_source_order')); continue
        if not visible(original) or sibling(original):
            excluded.append(original['id']); continue
        e = deepcopy(original)
        if e['id'] == anchor['id']:
            e['text'] = e['text'][:start]
        if e['text'].strip(): eligible.append(e)
    return anchor, start, end, eligible, scope, excluded, scope_excluded


def search(run, query):
    validate(query)
    anchor, start, end, eligible, scope, excluded, scope_excluded = visible_prefix(run, query['anchor'])
    lookup = {e['id']: e for e in eligible}
    qtext = query.get('text', anchor['text'][start:end])
    query_terms = query_tokens(qtext)
    use_context = query.get('strategy', 'source') == 'source_and_calls'
    groups = dispatch_groups(run, eligible, anchor) if use_context else {}
    questions = deepcopy(query.get('questions', [dict(id='query', text=qtext)]))
    # A continuation belongs to this exact earlier visible source and query.
    # Later events or an unrelated trajectory cannot invalidate or reorder it.
    search_id='evidence-search-'+digest(dict(version=VERSION,run_id=run['id'],prefix=eligible,scope=scope,
        anchor=dict(event_id=anchor['id'],start=start,end=end,text=anchor['text'][start:end]),questions=questions,
        strategy=query.get('strategy','source'),dispatch_groups=groups,
        limit=query.get('limit',8),max_chars=query.get('max_chars',16000)))
    cursor=query.get('cursor');offset=cursor['offset'] if cursor else 0
    if cursor and cursor['search_id']!=search_id:
        raise InputError('Evidence search or visible source changed; start a new search')
    rankings = {}; chunk_refs = {}; matched_windows = {}
    # Index returns together with their recorded invocation/envelope. This is
    # source context, not an inferred claim that the call fulfilled its intent.
    # Resolve links from the visible prefix only: later duplicate IDs cannot
    # change an earlier search's correspondence or corpus statistics.
    prefix = dict(run, events=eligible)
    pairs = links(prefix)['by_action']; partners = {}; response_actions = {}
    for action, responses in pairs.items():
        for response in responses:
            rid = response['id'] if isinstance(response, dict) else response
            partners.setdefault(action, []).append((rid, 'recorded_response'))
            partners.setdefault(rid, []).append((action, 'recorded_dispatch'))
            response_actions.setdefault(rid, []).append(action)
    children = {}
    def recorded_parent(event):
        parent=lookup.get(event.get('parent_id'))
        if (parent and not event.get('copied_context') and not parent.get('copied_context')
                and parent['index']<event['index']):return parent['id']
        return None
    for event in eligible:
        parent=recorded_parent(event)
        if event['kind'] == 'action' and parent:
            children.setdefault(parent, []).append(event['id'])

    def index_context(event):
        actions = response_actions.get(event['id'], [])
        parent_ids = list(dict.fromkeys(recorded_parent(lookup[a]) for a in actions if a in lookup))
        if event['kind'] == 'action': parent_ids = [recorded_parent(event)]
        def snippets(ids):
            return '\n'.join(DATA_URI.sub(' ', lookup[eid]['text'])[:CONTEXT_CHARS]
                             for eid in ids if eid in lookup)[:2 * CONTEXT_CHARS]
        return snippets(actions), snippets(parent_ids)

    db = sqlite3.connect(':memory:')
    try:
        try:
            db.execute("CREATE VIRTUAL TABLE evidence USING fts5(text, tokenize='porter unicode61')")
            db.execute("CREATE VIRTUAL TABLE context_evidence USING fts5(dispatch, parent, tokenize='porter unicode61')")
        except sqlite3.OperationalError as error:
            raise InputError('Earlier evidence search needs SQLite FTS5') from error
        context_refs = {}; first_chunks = {}
        for e in eligible:
            dispatch, parent = index_context(e) if use_context else ('', '')
            if dispatch or parent:
                row = db.execute('INSERT INTO context_evidence(dispatch,parent) VALUES (?,?)',
                                 (index_text(dispatch), index_text(parent)))
                context_refs[row.lastrowid] = e['id']
            for a, b, text, first, last in search_chunks(e['text']):
                row = db.execute('INSERT INTO evidence(text) VALUES (?)', (index_text(text),))
                chunk_refs[row.lastrowid] = (e['id'], a, b, first, last)
                first_chunks.setdefault(e['id'], (a, b, first, last))
        for question in questions:
            ranked = {}; rankings[question['id']] = ranked
            tokens = query_tokens(question['text'])
            if not tokens: continue
            kinds = question.get('source_types', ['action', 'feedback', 'prose'])
            expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in tokens)
            for rowid, score in db.execute('SELECT rowid,bm25(evidence) FROM evidence WHERE evidence MATCH ? ORDER BY 2,rowid', (expression,)):
                eid, a, b, first, last = chunk_refs[rowid]
                if source_type(lookup[eid]) not in kinds: continue
                left, right = context_range(a, b, first, last)
                matched_windows.setdefault(eid, []).append((left, right))
                ranked.setdefault(eid, dict(event_id=eid, start=left, end=right,
                                            matched_start=a, matched_end=b, lexical_score=score,
                                            match_basis='source_text'))
            source_ranks = {eid: i for i, eid in enumerate(ranked, 1)}
            context_ranks = {}
            for rowid, score in db.execute('SELECT rowid,bm25(context_evidence) FROM context_evidence WHERE context_evidence MATCH ? ORDER BY 2,rowid', (expression,)):
                eid = context_refs[rowid]
                if source_type(lookup[eid]) not in kinds or eid not in first_chunks: continue
                context_ranks[eid] = len(context_ranks) + 1
                a, b, first, last = first_chunks[eid]
                left, right = context_range(a, b, first, last)
                ranked.setdefault(eid, dict(event_id=eid, start=left, end=right,
                    matched_start=a, matched_end=b, lexical_score=score, match_basis='recorded_context'))
            for eid, hit in ranked.items():
                hit['source_rank'] = source_ranks.get(eid)
                hit['context_rank'] = context_ranks.get(eid)
                hit['retrieval_score'] = sum(1/(60 + ranks[eid]) for ranks in (source_ranks, context_ranks) if eid in ranks)
            rankings[question['id']] = dict(sorted(ranked.items(), key=lambda item: -item[1]['retrieval_score']))
    finally:
        db.close()

    limit = query.get('limit', 8)
    # Independent rankings share one index and one source-character budget.
    # Round-robin selection prevents one question from consuming every slot;
    # scores from different queries are deliberately not compared or summed.
    queues={}
    for qid,hits in rankings.items():
        first=diverse(list(hits.values()),lookup,limit);ids={h['event_id'] for h in first}
        queues[qid]=iter(first+[h for eid,h in hits.items() if eid not in ids])
    ranks={qid:{eid:i for i,eid in enumerate(hits,1)} for qid,hits in rankings.items()}
    chosen_by_id = {}
    while True:
        progressed = False
        for qid, queue in queues.items():
            for hit in queue:
                if hit['event_id'] not in chosen_by_id:
                    chosen_by_id[hit['event_id']] = dict(hit, source_type=source_type(lookup[hit['event_id']]),
                        lexical_rank=ranks[qid][hit['event_id']])
                    progressed = True
                    break
        if not progressed: break
    ordered=list(chosen_by_id.values())
    if offset>=len(ordered) and cursor:
        raise InputError('Evidence cursor is outside the candidate list')
    chosen=ordered[offset:offset+limit];chosen_by_id={h['event_id']:h for h in chosen}
    records = {}; used = 0; deferred = []
    budget = query.get('max_chars', 16000)
    def retain(eid, a, b, reason):
        nonlocal used
        e = lookup.get(eid)
        if e is None: return False
        allowed = subtract([(a, min(b, len(e['text'])))],
                           [(m.start(), m.end()) for m in DATA_URI.finditer(e['text'])])
        if not allowed: return False
        old = records.get(eid, {}).get('ranges', [])
        extra = subtract(allowed, old)
        size = sum(y-x for x,y in extra)
        if used + size > budget:
            deferred.append(dict(event_id=eid, reason=reason, cause='text_budget',
                                 requested_ranges=[dict(start=x,end=y) for x,y in allowed])); return False
        used += size
        record = records.setdefault(eid, dict(event_id=eid, ranges=[], reasons=[]))
        record['ranges'] = merged(old + allowed)
        if reason not in record['reasons']: record['reasons'].append(reason)
        return bool(allowed)

    matches = []
    for rank, hit in enumerate(chosen, offset+1):
        reason = 'recorded_context_match' if hit['match_basis'] == 'recorded_context' else 'lexical_match'
        if retain(hit['event_id'], hit['start'], hit['end'], dict(kind=reason, rank=rank)):
            matches.append(dict(rank=rank, **hit))
        else:
            # Do not advance past a candidate omitted by this page's budget.
            # A later page can retain it with a fresh explicit budget.
            break
    chosen_by_id={h['event_id']:h for h in matches}
    next_offset=offset+len(matches)
    next_cursor={'search_id':search_id,'offset':next_offset} if next_offset<len(ordered) else None
    # Protect each supplied question's own matching passage before optional
    # request, native-call and surrounding-record context consumes the budget.
    # Prefer its readable window; a bounded exact matching chunk is useful
    # when the surrounding window does not fit. Neither is an answered claim.
    for question in questions:
        for eid, hit in rankings[question['id']].items():
            if eid in chosen_by_id:
                reason=dict(kind='question_match',question_id=question['id'])
                if not retain(eid,hit['start'],hit['end'],reason):
                    retain(eid,hit['matched_start'],hit['matched_end'],reason)
    # Task instructions are context, not a judgement of relevance or adoption.
    requests = [e for e in eligible if e['actor'] == 'user' and e['kind'] in {'instruction','message'}]
    request_ids = list(dict.fromkeys(e['id'] for e in (requests[:1] + requests[-1:])))
    for eid in request_ids:
        retain(eid, 0, min(1200, len(lookup[eid]['text'])), dict(kind='recorded_user_request'))

    positions = {e['id']: i for i,e in enumerate(eligible)}
    def context_windows(eid):
        text = lookup[eid]['text']
        readable = subtract([(0, len(text))], [(m.start(), m.end()) for m in DATA_URI.finditer(text)])
        if sum(b-a for a,b in readable) <= 2 * CONTEXT_CHARS:
            return readable
        windows = []
        for a,b in matched_windows.get(eid, []):
            new_chars = sum(d-c for c,d in subtract([(a,b)], merged(windows)))
            if new_chars >= min(CONTEXT_CHARS//2, b-a): windows.append((a,b))
            if len(windows) == 2: break
        # If only its call matched, expose both ends of a long returned record.
        # End-of-process results are often after setup logs. These are context,
        # never inferred outcomes, and encoded media is still excluded.
        if not windows and readable:
            windows = [(readable[0][0], min(readable[0][1], readable[0][0]+CONTEXT_CHARS)),
                       (max(readable[-1][0], readable[-1][1]-CONTEXT_CHARS), readable[-1][1])]
        return merged(windows)

    for hit in matches:
        eid = hit['event_id']
        context = [(other, kind, eid) for other, kind in partners.get(eid, [])]
        for action in response_actions.get(eid, []):
            parent = recorded_parent(lookup[action]) if action in lookup else None
            if parent in lookup: context.append((parent, 'recorded_parent', action))
        for child in children.get(eid, []):
            context.append((child, 'recorded_child_dispatch', eid))
            context.extend((other, kind, child) for other, kind in partners.get(child, []))
        parent = recorded_parent(lookup[eid])
        if lookup[eid]['kind'] == 'action' and parent in lookup:
            context.append((parent, 'recorded_parent', eid))
        # A command may be meaningful only alongside another command from its
        # source message. Keep this source membership even when the envelope's
        # commentary is blank; do not create action/result or causal edges.
        group = groups.get(eid)
        if group:
            for other in group['action_ids']:
                if other != eid:
                    for a, b in context_windows(other):
                        retain(other, a, b, dict(kind='recorded_dispatch_group',
                            of_event_id=eid, parent_event_id=group['parent_id']))
        for other, kind, of_event_id in context:
            if other in lookup:
                for a,b in context_windows(other):
                    retain(other, a, b, dict(kind=kind, of_event_id=of_event_id))
        pos = positions[eid]
        if pos:
            prior = eligible[pos-1]
            # Preserve nearby prose as context; never call this an assessment.
            if prior['actor'] == 'agent' and prior['kind'] in {'message','reasoning'}:
                retain(prior['id'], 0, min(1200, len(prior['text'])),
                       dict(kind='preceding_source_record', of_event_id=eid))

    # Additional passages in the same source record can qualify its strongest
    # match. Expand only after reserving matches, requests and native context.
    for hit in matches:
        for a,b in context_windows(hit['event_id']):
            retain(hit['event_id'], a, b, dict(kind='matching_record_context'))

    question_reports = []
    for question in questions:
        hits = rankings[question['id']]
        retained = [eid for eid, hit in hits.items() if eid in records and any(
            a <= hit['matched_start'] and hit['matched_end'] <= b for a,b in records[eid]['ranges'])]
        question_reports.append(dict(**question, query_terms=query_tokens(question['text']),
            lexically_matched_events=len(hits), retained_match_event_ids=retained,
            retained_match_ranges=[dict(event_id=eid,source_pointer=lookup[eid]['source_pointer'],
                start=hits[eid]['matched_start'],end=hits[eid]['matched_end'],
                match_basis=hits[eid]['match_basis']) for eid in retained],
            context_only_match_event_ids=[eid for eid in retained if hits[eid]['match_basis'] == 'recorded_context'],
            omitted_match_event_ids=[eid for eid in hits if eid not in retained],
            status='candidates_retained' if retained else 'candidates_omitted' if hits else 'no_lexical_matches'))

    output = []
    for e in eligible:
        if e['id'] not in records: continue
        saved = records[e['id']]
        fragments = [dict(event_id=e['id'], source_pointer=e['source_pointer'],
                          trajectory_id=e['trajectory_id'], start=a, end=b, text=e['text'][a:b])
                     for a,b in saved['ranges']]
        readable = len(e['text']) - sum(m.end()-m.start() for m in DATA_URI.finditer(e['text']))
        output.append(dict(event_id=e['id'], event_index=e['index'], actor=e['actor'], kind=e['kind'],
                           copied_context=bool(e.get('copied_context')), fragments=fragments,
                           reasons=saved['reasons'], omitted_text_chars=readable-sum(b-a for a,b in saved['ranges'])))
    # A compact question chunk may have been retained after its wider context
    # was deferred. Report the final missing ranges, not failed allocation
    # attempts that would misleadingly imply the entire match was omitted.
    missing=[];seen=set()
    for item in deferred:
        ranges=subtract([(r['start'],r['end']) for r in item['requested_ranges']],
                        records.get(item['event_id'],{}).get('ranges',[]))
        if not ranges:continue
        row=dict(item,omitted_ranges=[dict(start=a,end=b) for a,b in ranges],
                 omitted_source_chars=sum(b-a for a,b in ranges))
        key=digest(row)
        if key not in seen:missing.append(row);seen.add(key)
    body = dict(schema=VERSION, run_id=run['id'], source_hash=digest(run), query=deepcopy(query),
                scope=scope,anchor=dict(event_id=anchor['id'], source_pointer=anchor['source_pointer'],
                            trajectory_id=anchor['trajectory_id'], start=start, end=end),
                engine=('SQLite FTS5 porter/unicode61 BM25; reciprocal rank fusion of source and recorded context (k=60)' if use_context else 'SQLite FTS5 porter/unicode61 BM25'), sqlite_version=sqlite3.sqlite_version,
                selection='Rank small passages independently for each supplied question; share match slots round-robin. Reserve matching question passages before optional context, using the exact matching chunk when its surrounding window does not fit. Retain source-type diversity and recorded parent, dispatch and response context within one page text budget. Continue with the returned cursor to inspect further ranked event candidates. Candidate retention does not establish that a question is answered.',
                pagination=dict(search_id=search_id,offset=offset,candidates_total=len(ordered),
                    retained_candidates=len(matches),next_cursor=next_cursor,exhausted=next_cursor is None,
                    boundary='Pages continue primary event candidates, not every passage in each event. Context can recur on different pages and costs characters again. Exhaustion is not evidence of absence or semantic completeness.'),
                retrieval_windows=dict(search_chars=SEARCH_CHARS, search_stride=SEARCH_STRIDE,
                                       context_chars=CONTEXT_CHARS, base_context_windows_per_record=2,
                                       additional_question_windows=len(questions) if 'questions' in query else 0,
                                       max_index_chars_per_context_field=2 * CONTEXT_CHARS),
                dispatch_group_context=dict(enabled=use_context,
                    boundary='Other commands recorded in the same source message. Membership is context, not execution order, dependency or result attribution.'),
                query_terms=query_terms, query_term_limit=32, questions=question_reports, matches=matches, records=output,
                coverage=dict(eligible_events=len(eligible), lexically_matched_events=len(set().union(*(set(h) for h in rankings.values()))),
                    retained_matches=len(matches), retained_events=len(output), source_text_chars=used,
                    max_source_text_chars=budget, omitted_event_ids=[e['id'] for e in eligible if e['id'] not in records],
                    omitted_request_event_ids=[e['id'] for e in requests if e['id'] not in records],
                    excluded_not_visible_or_parallel=excluded,excluded_source_records=scope_excluded,deferred=missing),
                boundary=BOUNDARY, new_model_calls=0)
    return dict(id='source-evidence-'+digest(body), **body)
