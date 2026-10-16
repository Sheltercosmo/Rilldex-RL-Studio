"""Lossless boundary proposals for model text, independent of its RL producer.

Recognizes a small Markdown syntax subset, not a full CommonMark parser or
semantic segmenter. Stable unit identity is based on source spans; parser version
is tracked separately so unchanged exact Jev requests can safely reuse results.
"""
import re

SEGMENTATION_VERSION = "text-boundaries/2"
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\r\n]*)[\r\n]*$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
LIST = re.compile(r"^[ \t]*(?:[-+*][ \t]+|[0-9]{1,9}[.)][ \t]+)")
SENTENCE = re.compile(r"[.!?](?:[\"')\]]?)(?=\s+[A-Z])\s*")


def code_spans(text):
    """Paired backtick runs only; an unmatched delimiter is ordinary text."""
    tokens = list(re.finditer(r"`+", text))
    next_equal, latest = {}, {}
    for j in range(len(tokens) - 1, -1, -1):
        length = len(tokens[j][0])
        next_equal[j] = latest.get(length)
        latest[length] = j
    i = 0
    while i < len(tokens):
        first = tokens[i]; end = next_equal[i]
        if end is None:
            i += 1
        else:
            yield first.start(), tokens[end].end()
            i = end + 1


def segments(text):
    """Partition every code point without splitting ordinal prefixes or code.

    Headings stay together. Quoted lines and fenced payloads retain their prior
    separate syntax role. Sentence boundaries inside inline code are suppressed.
    Remaining line/sentence boundaries are proposals, not semantic truth.
    """
    cursor, start, fence = 0, 0, None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = FENCE.match(line)
        if fence:
            cursor += len(line)
            # A language/info suffix cannot close a fence. Keep internal lines
            # intact until a same-character, long-enough, otherwise blank close.
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                yield start, cursor, "code_or_payload"
                fence = None; start = cursor
            continue
        if marker and (marker[1][0] != "`" or "`" not in marker[2]):
            fence = marker[1]; start = cursor; cursor += len(line)
            continue
        kind = "quoted" if stripped.startswith(">") else "text"
        protected = list(code_spans(line))
        list_prefix = LIST.match(line)
        if list_prefix: protected.append((0, list_prefix.end()))
        # Protect the complete ATX heading, including numbered/emphasized text.
        if HEADING.match(line): protected.append((0, len(line)))
        ends = [] if kind == "quoted" else [m.end() for m in SENTENCE.finditer(line)
                if not any(a <= m.start() < b for a, b in protected)]
        local = 0
        for end in ends + [len(line)]:
            if end > local:
                yield cursor + local, cursor + end, kind
                local = end
        cursor += len(line); start = cursor
    if fence:
        yield start, len(text), "code_or_payload"
