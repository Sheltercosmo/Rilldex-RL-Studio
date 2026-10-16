"""Bounded prior-work search; retrieval never establishes work identity."""
from collections import defaultdict
from copy import deepcopy
import sqlite3

from . import contribution_work as cw, contribution_scope_pairs as pairs, graph_store, work_subjects as ws
from .feedback_retrieval import terms
from .readable_context import DATA_URI
from .schema import InputError, digest, dumps
from .semantic_extraction import checked_span

VERSION = 'prior-work-retrieval/1'


def require(ok, message):
    if not ok:
        raise InputError('Prior work retrieval: ' + message)


class WorkIndex:
    """FTS5 corpus contains only eligible prior units at the current query.

    Append-only prefixes reuse an in-memory index. Backward or incomparable
    queries rebuild it so future or parallel-sibling text cannot affect BM25.
    No provider client, persisted index, or semantic classification is involved.
    """
    def __init__(self, run, units):
        self.run = run
        self.units = {u['id']:deepcopy(u) for u in units}
        require(len(self.units) == len(units), 'duplicate unit IDs')
        self.events = {e['id']:e for e in run['events']}
        self.scopes = defaultdict(list)
        self.states = {}
        for unit in self.units.values():
            require(unit.get('status') == 'selected', 'selected units required')
            event = checked_span(run, unit['source'])
            require(event.get('actor') == unit.get('actor') == 'agent', 'agent attribution differs')
            for ref in cw.immediate_target(unit, cw.GRAPH_INPUT).get('evidence', []):
                checked_span(run, ref, unit['source'])
            self.scopes[ws.lane(unit,self.events)].append(unit)
        for rows in self.scopes.values():
            rows.sort(key=lambda u:ws.position(u,self.events))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for state in self.states.values():
            state['db'].close()

    def before(self, prior, current):
        # Equivalent to cw.ordered_before, after source validation at indexing.
        a, b = self.events[prior['source']['event_id']], self.events[current['source']['event_id']]
        if prior['id'] == current['id'] or ws.lane(prior,self.events) != ws.lane(current,self.events):
            return False
        if (a['index'],prior['source']['end']) > (b['index'],current['source']['start']):
            return False
        return not (a['kind'] == b['kind'] == 'action' and (
            a.get('parent_id') and a['parent_id'] == b.get('parent_id') or
            a.get('source_message_index') is not None and a['source_message_index'] == b.get('source_message_index')))

    def _index(self, key, eligible):
        ids = [u['id'] for u in eligible]
        state = self.states.get(key)
        if state and state['ids'] != ids[:len(state['ids'])]:
            state['db'].close(); state = None
        if state is None:
            db = sqlite3.connect(':memory:')
            try:
                db.execute("CREATE VIRTUAL TABLE work USING fts5(uid UNINDEXED, target, source, tokenize='porter unicode61')")
            except sqlite3.OperationalError as error:
                db.close(); raise InputError('Prior work retrieval needs SQLite FTS5') from error
            state = dict(db=db,ids=[])
            self.states[key] = state
        for unit in eligible[len(state['ids']):]:
            target = cw.immediate_target(unit,cw.GRAPH_INPUT).get('text','')
            state['db'].execute('INSERT INTO work(uid,target,source) VALUES(?,?,?)',
                (unit['id'], DATA_URI.sub(' ',target), DATA_URI.sub(' ',unit['source']['text'])))
        state['ids'] = ids
        return state['db']

    def select(self, unit_id, limit=8, recent=2, exclude=()):
        require(type(limit) is int and 1 <= limit <= pairs.LIMIT, 'candidate limit must be 1–16')
        require(type(recent) is int and 0 <= recent <= limit, 'recent slots must fit candidate limit')
        require(unit_id in self.units, 'unknown current unit')
        current = self.units[unit_id]; key = ws.lane(current,self.events)
        eligible = [u for u in self.scopes[key] if self.before(u,current)]
        excluded = set(exclude)
        require(excluded <= {u['id'] for u in eligible}, 'excluded pair is not an eligible predecessor')
        db = self._index(key,eligible)
        candidates = [u for u in eligible if u['id'] not in excluded]
        query = terms(DATA_URI.sub(' ',cw.immediate_target(current,cw.GRAPH_INPUT).get('text','')+'\n'+current['source']['text']))
        chosen = {u['id']:dict(method='retained_recent',lexical_score=None) for u in candidates[-recent:] if recent}
        if query:
            expression = ' OR '.join('"'+term.replace('"','""')+'"' for term in query)
            for uid,score in db.execute('SELECT uid,bm25(work,0,3,1) FROM work WHERE work MATCH ? ORDER BY 2,rowid DESC',(expression,)):
                if len(chosen) >= limit:break
                if uid not in excluded and uid not in chosen:
                    chosen[uid] = dict(method='lexical_match',lexical_score=score)
        for unit in reversed(candidates):
            if len(chosen) >= limit:break
            chosen.setdefault(unit['id'],dict(method='recent_fallback',lexical_score=None))
        selected = [deepcopy(u) for u in candidates if u['id'] in chosen]
        report = dict(schema=VERSION,current_unit_id=unit_id,cutoff=deepcopy(current['source']),
            engine='SQLite FTS5 porter/unicode61 BM25, target weight 3, source weight 1',sqlite_version=sqlite3.sqlite_version,
            candidate_limit=limit,recent_slots=recent,query_terms=query,query_term_limit=32,
            eligible_priors=len(eligible),already_observed_priors=len(excluded),
            selected_priors=len(selected),omitted_priors=len(candidates)-len(selected),
            selected=[dict(unit_id=u['id'],**chosen[u['id']]) for u in selected],
            limitation='Ranked candidates only. Paraphrases and implicit references can be missed. '
                       'Omitted pairs remain unknown; this is not complete work grouping or evidence of novelty.')
        return selected, report


def prepare(run, graph, limit=8, recent=2, *, unit_ids=None, max_requests=128, max_bytes=4_000_000):
    """Prepare only new candidate comparisons; do not change complete grouping."""
    graph_store.validate(graph)
    require(type(limit) is int and 1 <= limit <= pairs.LIMIT, 'candidate limit must be 1–16')
    require(type(recent) is int and 0 <= recent <= limit, 'recent slots must fit candidate limit')
    require(type(max_requests) is int and 0 <= max_requests <= 1024, 'request budget must be 0–1024')
    require(type(max_bytes) is int and max_bytes >= 0, 'byte budget must be nonnegative')
    require(digest(run) == graph['source_hash'], 'source differs from graph')
    _, lookup, _, issues = ws.evidence_index(graph)
    require(not issues, 'repair invalid or overlapping units before retrieval')
    if unit_ids is not None:
        require(isinstance(unit_ids,list) and len(unit_ids)==len(set(unit_ids)) and set(unit_ids)<=set(lookup),
                'unique eligible current unit IDs required')
    known = {}
    if (graph.get('semantic_context') or {}).get('contribution_scope'):
        from .scope_membership import replay
        _, known = replay(run,graph)
    requests, searches, unavailable, deferred = [], [], [], []
    request_bytes = 0
    with WorkIndex(run,list(lookup.values())) as index:
        for unit in sorted(lookup.values(),key=lambda u:ws.position(u,index.events)):
            if unit_ids is not None and unit['id'] not in unit_ids:continue
            excluded = [prior for current,prior in known if current == unit['id']]
            selected, search = index.select(unit['id'],limit,recent,excluded)
            searches.append(search)
            if not selected:continue
            if cw.immediate_target(unit,cw.GRAPH_INPUT).get('status') != 'expressed':
                unavailable.append(dict(unit_id=unit['id'],prior_unit_ids=[u['id'] for u in selected],
                    reason='Current unit needs a readable, source-bound work target'))
                continue
            unreadable = [u for u in selected if cw.immediate_target(u,cw.GRAPH_INPUT).get('status') != 'expressed']
            if unreadable:
                unavailable.append(dict(unit_id=unit['id'],prior_unit_ids=[u['id'] for u in unreadable],
                    reason='Prior units need readable, source-bound work targets'))
                selected = [u for u in selected if u not in unreadable]
            if not selected:continue
            if len(requests) >= max_requests:
                deferred.append(dict(unit_id=unit['id'],prior_unit_ids=[u['id'] for u in selected],reason='request_budget'))
                continue
            try:
                req = pairs.request(run,unit,selected,version=pairs.TARGET_VERSION)
            except InputError as error:
                unavailable.append(dict(unit_id=unit['id'],prior_unit_ids=[u['id'] for u in selected],reason=str(error)))
                continue
            size = len(dumps(req).encode())
            if request_bytes + size > max_bytes:
                deferred.append(dict(unit_id=unit['id'],prior_unit_ids=[u['id'] for u in selected],reason='byte_budget'))
                continue
            requests.append(dict(request_hash=digest(req),request=req,current=deepcopy(unit),priors=selected))
            request_bytes += size
    result = dict(schema=VERSION,graph_id=graph['id'],source_hash=graph['source_hash'],unit_ids=deepcopy(unit_ids),
        requests=requests,searches=searches,unavailable=unavailable,deferred=deferred,provider_calls=0,
        budget=dict(max_requests=max_requests,max_bytes=max_bytes),
        counts=dict(eligible_pairs=sum(s['eligible_priors'] for s in searches),
            already_observed_pairs=sum(s['already_observed_priors'] for s in searches),
            selected_pairs=sum(s['selected_priors'] for s in searches),
            omitted_pairs=sum(s['omitted_priors'] for s in searches),
            prepared_pairs=sum(len(r['priors']) for r in requests),requests=len(requests),
            deferred_pairs=sum(len(r['prior_unit_ids']) for r in deferred),
            unavailable_pairs=sum(len(r['prior_unit_ids']) for r in unavailable),request_bytes=request_bytes),
        limits='Search budget only; no provider request is sent. The existing complete-pair grouping contract is unchanged. '
               'Unresolved saved choices are not re-requested, and unsearched pairs are not negative decisions.')
    return result
