"""Repeated contiguous blocks separated by recorded work, over one alphabet.

Bounded suffix sorting and common-prefix intervals avoid enumerating all pairs
of source positions. No symbol is removed and no semantic comparison is made.
"""
from bisect import bisect_right

from .repeated_sequences import find as consecutive
from .schema import InputError, digest

VERSION = 'returning-sequences/1'
MAX_POSITIONS = 20000


def find(tokens, *, max_length=64):
    if (not isinstance(tokens, list) or
            any(t is not None and (not isinstance(t, str) or not t) for t in tokens)):
        raise InputError('Sequence tokens must be nonempty strings or explicit missing values')
    if isinstance(max_length, bool) or not isinstance(max_length, int) or not 2 <= max_length <= 1024:
        raise InputError('Maximum sequence length must be between 2 and 1024')
    result = {'version': VERSION, 'status': 'complete', 'positions': len(tokens),
              'token_hash': digest(tokens), 'max_length': max_length, 'position_limit': MAX_POSITIONS,
              'patterns': [],
              'definition': 'Contiguous blocks with at least two distinct symbols and two disjoint occurrences separated by at least one position. Patterns are maximal over all their recorded occurrences within the configured length. Each later occurrence references its nearest earlier disjoint occurrence. Continuous periodic intervals are excluded. Overlapping patterns and occurrences are retained, not summed as unique work.',
              'scope': 'Missing tokens cannot match inside a block. Unknown intervening positions stay in the gap. A return describes source order and selected equality, not agent intention or a cause.'}
    if len(tokens) > MAX_POSITIONS:
        result['status'] = 'requires_segment_selection'
        return result
    size = len(tokens)
    limit = min(max_length, (size - 1) // 2)
    if limit < 2:
        return result
    # Unknowns have distinct ordering sentinels; LCP calculation also stops
    # explicitly at them, so no repeated block can cross a missing observation.
    alphabet = {t: i for i, t in enumerate(sorted({t for t in tokens if t is not None}))}
    encoded = [alphabet[t] if t is not None else -i - 1 for i, t in enumerate(tokens)]
    suffixes = sorted(range(size), key=lambda i: tuple(encoded[i:i + limit]))
    lcp = [0] * size
    for i in range(1, size):
        a, b = suffixes[i - 1], suffixes[i]
        length = 0
        while (length < limit and a + length < size and b + length < size and
               tokens[a + length] is not None and tokens[a + length] == tokens[b + length]):
            length += 1
        lcp[i] = length
    # At each popped common-prefix interval, every suffix shares exactly the
    # candidate word; shorter right-extendable prefixes are not separate rows.
    stack, candidates = [], []
    for i in range(1, size + 1):
        height = lcp[i] if i < size else 0
        left = i - 1
        while stack and stack[-1][0] > height:
            length, left = stack.pop()
            if length >= 2:
                candidates.append((length, sorted(suffixes[left:i])))
        if height >= 2 and (not stack or stack[-1][0] < height):
            stack.append((height, left))
    # A gap within the same continuous periodic run is not a separated return.
    periodic = consecutive(tokens, max_period=max_length)
    cover = [0] * size
    for row in periodic['runs']:
        cover[row['start']] = max(cover[row['start']], row['end'])
    for i in range(1, size):
        cover[i] = max(cover[i], cover[i - 1])
    for length, starts in candidates:
        word = tokens[starts[0]:starts[0] + length]
        if len(set(word)) < 2:
            continue  # Single-target recurrence already has its own history.
        left_context = {tokens[i - 1] if i and tokens[i - 1] is not None else ('boundary', i)
                        for i in starts}
        if len(left_context) == 1 and length < max_length:
            continue
        returns = []
        for current in starts:
            previous_index = bisect_right(starts, current - length) - 1
            if previous_index < 0:
                continue
            previous = starts[previous_index]
            gap_start, gap_end = previous + length, current
            if gap_end <= gap_start or cover[previous] >= current + length:
                continue
            returns.append({'previous_start': previous, 'current_start': current,
                            'length': length, 'gap_start': gap_start, 'gap_end': gap_end,
                            'missing_gap_positions': [i for i in range(gap_start, gap_end) if tokens[i] is None]})
        if not returns:
            continue
        row = {'pattern': word, 'length': length, 'starts': starts, 'returns': returns,
               'at_length_limit': length == max_length}
        row['id'] = 'return-pattern-' + digest(row)[:20]
        result['patterns'].append(row)
    result['patterns'].sort(key=lambda p: (p['starts'][0], -p['length'], p['starts']))
    return result
