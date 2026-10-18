"""Bounded exact passages from recorded action/result partners.

Retrieval selects text, never a risk label. Partial records remain partial;
all original source pages stay in the normal diagnostic scan.
"""
from . import diagnostic_relations as relations, diagnostic_context as context
from .requirement_retrieval import order
from .schema import digest, dumps

VERSION = 'diagnostic-linked-passages/1'
CHUNK_CHARS = 1400
OVERLAP_CHARS = 180


def fields(record):
    value = record['value']
    # Native argument strings are easier to inspect than a second JSON encoding
    # inside the normalized action text. Preserve their actual field paths.
    def strings(obj, path):
        if isinstance(obj, str):
            if obj: yield path, obj
        elif isinstance(obj, dict):
            for key, child in obj.items(): yield from strings(child, [*path, key])
        elif isinstance(obj, list):
            for i, child in enumerate(obj): yield from strings(child, [*path, i])
    if isinstance(value.get('arguments'), (dict, list)):
        arguments = list(strings(value['arguments'], ['arguments']))
        if arguments: return arguments
    for key in context.TEXT_FIELDS:
        if isinstance(value.get(key), str) and value[key]: return [([key], value[key])]
        if key == 'content' and isinstance(value.get(key), list):
            return [([key, i, 'text'], b['text']) for i, b in enumerate(value[key])
                    if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str)]
    return []


def chunks(record):
    result = []
    for path, text in fields(record):
        start = 0
        while start < len(text):
            if len(text) - start < CHUNK_CHARS: start = max(0, len(text) - CHUNK_CHARS)
            end = min(start + CHUNK_CHARS, len(text))
            if end < len(text):
                boundary = text.rfind('\n', start + CHUNK_CHARS // 2, end)
                if boundary >= 0: end = boundary + 1
            result.append(dict(id='linked-' + digest([record['id'], path, start, end])[:20],
                record_id=record['id'], event_id=record['event_id'], actor=record['actor'], kind=record['kind'],
                native_scope=record['scope'], field_path=path, start=start, end=end, text=text[start:end],
                source_record=dict(origin='trace', start=record['start'], end=record['end'], path=record['path']),
                complete_record=False))
            if end == len(text): break
            start = end - OVERLAP_CHARS
    return result


def ranked_chunks(record, queries):
    candidates = chunks(record)
    if not candidates: return []
    pages = [[dict(origin='trace', start=i, text=c['text'])] for i, c in enumerate(candidates)]
    ranked = order(pages, [dict(id=str(i), text=q, origin='task', end=0) for i, q in enumerate(queries)])['pages']
    # Keep one best lexical match plus both record boundaries. The remaining
    # hits diversify across detector clauses. This is not a relevance verdict.
    choices = [*ranked[:1], 0, len(candidates)-1, *ranked[1:]]
    return [candidates[i] for i in dict.fromkeys(choices)]


def packet(source, fragments, *, queries, indexed=None):
    indexed = relations.records(source) if indexed is None else indexed
    base = relations.packet(source, fragments, indexed=indexed)
    wanted = {r['id'] for r in base['linked_source_records']} | set(base['omitted_linked_record_ids'])
    selected = [r for r in indexed if r['id'] in wanted]
    budget = relations.LINK_LIMIT
    fair_share = budget // max(1, len(selected))
    options = []
    for record in selected:
        view = context.readable(record)
        view.update(event_id=record['event_id'], native_scope=record['scope'])
        if len(dumps(view)) <= fair_share:
            options.append([('whole', view)])
        else:
            options.append([('excerpt', c) for c in ranked_chunks(record, queries)])
    whole, excerpts, used = [], [], 0
    # Each partner receives a chance before one verbose result consumes the
    # budget. Whole records and excerpts share the existing 12k allocation.
    for depth in range(max(map(len, options), default=0)):
        for choices in options:
            if depth >= len(choices): continue
            kind, view = choices[depth]; cost = len(dumps(view))
            if used + cost > budget: continue
            (whole if kind == 'whole' else excerpts).append(view); used += cost
    complete = {v['id'] for v in whole}; partial = {v['record_id'] for v in excerpts}
    absent = sorted(wanted - complete - partial)
    base.update(linked_source_records=whole, linked_source_excerpts=excerpts,
        partial_linked_record_ids=sorted(partial), unrepresented_linked_record_ids=absent,
        omitted_linked_record_ids=absent, linked_evidence_chars=used)
    return base
