"""Exact consecutive repetition over a declared alphabet, with source positions.

This is a bounded-period scan, not semantic inference or conformance checking.
None is a barrier: missing observations must never be removed to create adjacency.
"""
from .schema import InputError, digest

VERSION = 'consecutive-patterns/1'
DEFAULT_MAX_PERIOD = 64


def primitive(word):
    """Whether a word is not an integer power of a shorter word."""
    size = len(word)
    prefix = [0] * size
    for i in range(1, size):
        k = prefix[i - 1]
        while k and word[k] != word[i]:
            k = prefix[k - 1]
        if word[k] == word[i]:
            k += 1
        prefix[i] = k
    period = size - prefix[-1]
    return period == size or size % period != 0


def find(tokens, *, max_period=DEFAULT_MAX_PERIOD):
    """Maximal periodic intervals, shortest period, at least two full copies.

    Ranges are zero-based, half-open. A maximal interval may end in a partial
    copy; it is retained explicitly. Different intervals can overlap. Repeated
    positions are the union after the first period, never a sum of run lengths.
    """
    if (not isinstance(tokens, list) or
            any(t is not None and (not isinstance(t, str) or not t) for t in tokens)):
        raise InputError('Sequence tokens must be nonempty strings or explicit missing values')
    if isinstance(max_period, bool) or not isinstance(max_period, int) or not 1 <= max_period <= 1024:
        raise InputError('Maximum pattern period must be between 1 and 1024')
    size = len(tokens)
    considered = min(max_period, size // 2)
    runs = []
    for period in range(1, considered + 1):
        matches = 0
        for i in range(period, size + 1):
            equal = (i < size and tokens[i] is not None and
                     tokens[i - period] is not None and tokens[i] == tokens[i - period])
            if equal:
                matches += 1
                continue
            if matches >= period:
                start = i - matches - period
                word = tokens[start:start + period]
                if primitive(word):
                    length = i - start
                    row = {'start': start, 'end': i, 'period': period,
                           'pattern': word, 'full_copies': length // period,
                           'partial_tail': length % period}
                    row['id'] = 'repeat-' + digest(row)[:20]
                    runs.append(row)
            matches = 0
    runs.sort(key=lambda r: (r['start'], r['end'], r['period']))
    repeated = sorted({i for r in runs for i in range(r['start'] + r['period'], r['end'])})
    result = {
        'version': VERSION, 'max_period': max_period, 'considered_period': considered,
        'token_hash': digest(tokens), 'positions': size,
        'missing_positions': [i for i, token in enumerate(tokens) if token is None],
        'runs': runs, 'repeated_positions': repeated,
        'definition': 'Maximal consecutive periodic intervals with at least two complete copies and the shortest period, up to the configured maximum. Partial trailing copies are explicit. Overlapping regions do not duplicate repeated-position counts.',
        'scope': 'Exact equality in the supplied alphabet. Missing tokens break repetition. No cause, progress, strategy or outcome is inferred.'
    }
    result['id'] = digest(result)[:24]
    return result


def source_measure(tokens):
    """Conservative per-record counts; unknown tokens can bridge known sections.

    Observed repeated positions stay a lower bound. With missing tokens every
    other position except the first is unresolved, including known tokens that
    could become part of a repeat across a missing token. These are conservative
    missingness bounds, not tight bounds or uncertainty about extraction labels.
    """
    patterns = find(tokens)
    repeated = set(patterns['repeated_positions'])
    unknown = sorted(set(range(1, len(tokens))) - repeated) if patterns['missing_positions'] else []
    return patterns, {'numerator': len(repeated), 'denominator': len(tokens), 'unknown': len(unknown)}, unknown
