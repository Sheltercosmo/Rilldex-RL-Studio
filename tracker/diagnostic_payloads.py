"""Preserve bounded recorded command objects as citation units, without executing them."""
import json
import re

from .diagnostic_excerpts import _leaves

VERSION = 'diagnostic-payload-boundaries/1'
MAX_RECORD_CHARS = 262144
KEYS = {'command', 'cmd', 'tool', 'tool_calls', 'function', 'arguments',
        'file_edit_payload', 'code_execution_payload', 'source', 'action'}


def objects(text):
    """Literal JSON objects in exporter text; markers never confer actor roles."""
    decoder = json.JSONDecoder(); consumed = 0
    for match in re.finditer(r'(?m)^[ \t]*(?:\[action\][ \t]*)?\{', text):
        start = match.end() - 1
        if start < consumed: continue
        try:
            value, end = decoder.raw_decode(text, start)
        except (ValueError, RecursionError):
            continue
        consumed = end
        if isinstance(value, dict) and KEYS.intersection(value):
            yield start, end


def boundaries(text, start, end, metadata, *, maximum):
    """Original serialized ranges; no role changes or new action/result links."""
    if metadata.get('kind') in {'action', 'action_dispatch'} and end - start <= maximum:
        return [(start, end)]
    if end - start > MAX_RECORD_CHARS: return []
    result = []
    try:
        leaves = _leaves(text[start:end], list(range(start, end + 1)), expand_nested=False)
        for _, value, edges in leaves:
            for a, b in objects(value):
                left, right = edges[a], edges[b]
                if right - left <= maximum:
                    result.append((left, right))
    except (ValueError, IndexError, RecursionError):
        return []
    return sorted(set(result))


def source_boundaries(text, *, maximum):
    """Decode top-level exporter envelopes even when their role is unknown."""
    if not text.lstrip().startswith('['): return []
    decoder = json.JSONDecoder(); pos = text.index('[') + 1; result = []
    try:
        while pos < len(text):
            while pos < len(text) and text[pos] in ' \t\r\n,': pos += 1
            if pos == len(text) or text[pos] == ']': break
            _, end = decoder.raw_decode(text, pos)
            result.extend(boundaries(text, pos, end, {}, maximum=maximum))
            pos = end
    except (ValueError, IndexError, RecursionError): return []
    return sorted(set(result))


def partition(text, start, end, metadata, *, fallback, maximum, spans=()):
    """Lossless fallback around complete payloads; oversized objects stay paged."""
    cursor = start
    if metadata.get('kind') in {'action', 'action_dispatch'} and end - start <= maximum:
        yield start, end
        return
    for left, right in spans:
        if left < start or right > end: continue
        if left < cursor: continue
        # Short exporter delimiters stay with their payload, not in empty cards.
        if left - cursor < fallback // 4 and right - cursor <= maximum: left = cursor
        for a in range(cursor, left, fallback):
            yield a, min(a + fallback, left)
        yield left, right
        cursor = right
    for a in range(cursor, end, fallback):
        yield a, min(a + fallback, end)
