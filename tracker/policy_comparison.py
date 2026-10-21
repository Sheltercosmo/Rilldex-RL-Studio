"""Sampled-token comparison diagnostics; no model execution or optimizer changes."""
import math
from .schema import InputError


def compare_probabilities(behavior_logprobs, learner_logprobs, mask, *,
                          probability_thresholds=(), ratio_bounds=None):
    """Compare aligned natural-log probabilities over the supplied base mask.

    Threshold results replay exclusion rules on these tokens, not training runs.
    Inputs must use the same token positions and probability normalization.
    """
    a, b, m = list(behavior_logprobs), list(learner_logprobs), list(mask)
    if len(a) != len(b) or len(a) != len(m):
        raise InputError('Comparison arrays and mask must align exactly')
    thresholds = list(probability_thresholds)
    if len(thresholds) > 16 or any(type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= 1 for t in thresholds):
        raise InputError('Supply at most 16 probability thresholds between zero and one')
    thresholds = sorted(set(float(t) for t in thresholds))
    bounds = None
    if ratio_bounds is not None:
        bounds = list(ratio_bounds)
        if len(bounds) != 2 or any(type(t) not in (int, float) or not math.isfinite(t) or t <= 0 for t in bounds) or bounds[0] > bounds[1]:
            raise InputError('Ratio bounds must be finite, positive and ordered')
        bounds = [float(t) for t in bounds]
    differences, gaps = [], []
    for behavior, learner, include in zip(a, b, m):
        if include not in (0, 1, False, True):
            raise InputError('Comparison mask must be binary')
        if not include:
            continue
        try:
            p, q = float(behavior), float(learner)
        except (TypeError, ValueError, OverflowError):
            raise InputError('Compared log-probabilities must be finite and nonpositive')
        if not math.isfinite(p) or not math.isfinite(q) or p > 0 or q > 0:
            raise InputError('Compared log-probabilities must be finite and nonpositive')
        delta = q - p
        if not math.isfinite(delta):
            raise InputError('Log-probability difference is outside the finite numeric range')
        differences.append(delta)
        # Avoid cancellation for nearly identical probabilities; no ratio overflow.
        gaps.append(math.exp(max(p, q)) * -math.expm1(-abs(delta)))
    n = len(gaps)
    mean = lambda xs: math.fsum(v / n for v in xs) if n else None
    peak = max(differences, default=0)
    weights = [math.exp(d - peak) for d in differences]
    excluded = [d < math.log(bounds[0]) or d > math.log(bounds[1]) for d in differences] if bounds else None
    ordered = sorted(gaps)
    report = {
        'compared_tokens': n,
        'mean_absolute_gap': mean(map(abs, differences)),
        'mean_signed_gap': mean(differences),
        'max_absolute_gap': max(map(abs, differences), default=None),
        'token_weight_ess_fraction': math.fsum(weights) ** 2 / (n * math.fsum(w*w for w in weights)) if n else None,
        'mean_probability_gap': mean(gaps),
        'p95_probability_gap': ordered[math.ceil(.95*n)-1] if n else None,
        'max_probability_gap': max(gaps, default=None),
        'ratio': None,
        'thresholds': [],
    }
    if bounds:
        count = sum(excluded)
        report['ratio'] = dict(bounds=bounds, excluded_tokens=count, excluded_fraction=count/n if n else None)
    for threshold in thresholds:
        probability_excluded = [g > threshold for g in gaps]
        count = sum(probability_excluded)
        item = dict(threshold=threshold, excluded_tokens=count, excluded_fraction=count/n if n else None)
        if excluded is not None:
            item.update(probability_only_tokens=sum(p and not r for p, r in zip(probability_excluded, excluded)),
                        ratio_only_tokens=sum(r and not p for p, r in zip(probability_excluded, excluded)),
                        disagreement_fraction=sum(p != r for p, r in zip(probability_excluded, excluded))/n if n else None)
        report['thresholds'].append(item)
    return report
