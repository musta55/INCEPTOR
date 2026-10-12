"""Agreement between two phase labellings of the same actions (codebook §11.1, spec §9).

A labelling is one label per action of a trajectory; a stretch is a maximal run of equal
labels, and a boundary is the index k (1-based position in the sequence, k >= 1) of an action
whose label differs from the one before it.  Every measure takes a list of (reference,
hypothesis) pairs, one per trajectory, so that it can pool over trajectories:

kappa          Cohen's kappa over all actions, pooled (one contingency table)
accuracy       share of actions with the same label, pooled
boundary F1    boundaries matched one-to-one within ``tol`` actions (closest pairs first);
               precision, recall and F1 from the pooled counts (tol 0 = exact)
WindowDiff     Pevzner & Hearst (2002): the share of windows of k actions in which the two
               labellings hold a different number of boundaries; k is half the mean length of
               the reference's stretches; the mean over trajectories (lower is better)
sequence       the order of the stretches, ignoring their lengths: each labelling becomes its
               phase sequence (localization -> repair -> validation), and the Levenshtein
               distance between the two sequences counts the stretches to insert, delete or
               relabel; normalised by the longer sequence (0 = same order, 1 = nothing in
               common), the mean over trajectories, and the share of identical sequences

A label of None (a baseline that gives an action no phase) counts as its own label, so it
always disagrees with a human phase; ``coverage`` reports how many actions had one.
``bootstrap`` resamples trajectories, the unit of the sample, for confidence intervals.
"""
from __future__ import annotations

import collections
import random
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Labels = Sequence[Optional[str]]
Pairs = List[Tuple[Labels, Labels]]
NONE = "(none)"


def _norm(labels: Labels) -> List[str]:
    return [NONE if x is None else str(x) for x in labels]


def accuracy(ref: Labels, hyp: Labels) -> float:
    if len(ref) != len(hyp):
        raise ValueError(f"{len(ref)} reference labels but {len(hyp)} hypothesis labels")
    return sum(a == b for a, b in zip(_norm(ref), _norm(hyp))) / len(ref) if ref else float("nan")


def kappa(ref: Labels, hyp: Labels) -> float:
    """Cohen's kappa; 1.0 when both labellings use one and the same label throughout."""
    if len(ref) != len(hyp):
        raise ValueError(f"{len(ref)} reference labels but {len(hyp)} hypothesis labels")
    n = len(ref)
    if not n:
        return float("nan")
    r, h = _norm(ref), _norm(hyp)
    observed = sum(a == b for a, b in zip(r, h)) / n
    cr, ch = collections.Counter(r), collections.Counter(h)
    expected = sum(cr[k] * ch[k] for k in cr) / (n * n)
    return 1.0 if expected >= 1 else (observed - expected) / (1 - expected)


def boundaries(labels: Labels) -> List[int]:
    labels = _norm(labels)
    return [k for k in range(1, len(labels)) if labels[k] != labels[k - 1]]


def match_boundaries(ref: Labels, hyp: Labels, tol: int = 0) -> Tuple[int, int, int]:
    """(matched, reference boundaries, hypothesis boundaries); each boundary is matched at
    most once, to the closest one within ``tol`` actions (ties: the earlier one)."""
    rb, hb = boundaries(ref), boundaries(hyp)
    pairs = sorted((abs(a - b), a, b) for a in rb for b in hb if abs(a - b) <= tol)
    used_r, used_h, matched = set(), set(), 0
    for _d, a, b in pairs:
        if a not in used_r and b not in used_h:
            used_r.add(a)
            used_h.add(b)
            matched += 1
    return matched, len(rb), len(hb)


def prf(matched: int, n_ref: int, n_hyp: int) -> Dict[str, float]:
    """Precision, recall, F1; 1.0 when neither side has a boundary."""
    p = matched / n_hyp if n_hyp else 1.0
    r = matched / n_ref if n_ref else 1.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


def window_diff(ref: Labels, hyp: Labels, k: Optional[int] = None) -> float:
    if len(ref) != len(hyp):
        raise ValueError(f"{len(ref)} reference labels but {len(hyp)} hypothesis labels")
    n = len(ref)
    if n < 2:
        return 0.0
    if k is None:
        k = max(1, round(n / (2 * (len(boundaries(ref)) + 1))))
    rb, hb = set(boundaries(ref)), set(boundaries(hyp))
    if k >= n:
        return float(len(rb) != len(hb))
    windows = n - k
    wrong = sum(sum(1 for b in rb if i < b <= i + k) != sum(1 for b in hb if i < b <= i + k)
                for i in range(windows))
    return wrong / windows


def stretch_sequence(labels: Labels) -> List[str]:
    """The labels of the stretches in order: [A, A, B, A] -> [A, B, A]."""
    out: List[str] = []
    for x in _norm(labels):
        if not out or out[-1] != x:
            out.append(x)
    return out


def levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    """Insertions, deletions and substitutions that turn ``a`` into ``b``."""
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def sequence_distance(ref: Labels, hyp: Labels) -> Tuple[int, float]:
    """(Levenshtein distance between the stretch sequences, the same divided by the length of
    the longer sequence)."""
    a, b = stretch_sequence(ref), stretch_sequence(hyp)
    d = levenshtein(a, b)
    return d, d / max(len(a), len(b), 1)


def confusion(pairs: Pairs) -> Dict[Tuple[str, str], int]:
    """{(reference label, hypothesis label): actions}, pooled."""
    out: collections.Counter = collections.Counter()
    for ref, hyp in pairs:
        out.update(zip(_norm(ref), _norm(hyp)))
    return dict(out)


def per_label(pairs: Pairs, labels: Sequence[str]) -> Dict[str, Dict[str, float]]:
    """Precision, recall, F1 and reference support of each label, pooled."""
    conf = confusion(pairs)
    out: Dict[str, Dict[str, float]] = {}
    for lab in labels:
        tp = conf.get((lab, lab), 0)
        n_hyp = sum(v for (r, h), v in conf.items() if h == lab)
        n_ref = sum(v for (r, h), v in conf.items() if r == lab)
        p = tp / n_hyp if n_hyp else float("nan")
        r = tp / n_ref if n_ref else float("nan")
        f = 2 * p * r / (p + r) if n_hyp and n_ref and p + r else (0.0 if n_ref or n_hyp else float("nan"))
        out[lab] = {"precision": p, "recall": r, "f1": f, "support": n_ref}
    return out


def compare(pairs: Pairs) -> Dict[str, Any]:
    """All the measures of the module for one comparison, pooled over its trajectories."""
    ref = [x for r, _ in pairs for x in r]
    hyp = [x for _, h in pairs for x in h]
    out: Dict[str, Any] = {"trajectories": len(pairs), "actions": len(ref),
                           "coverage": (sum(x is not None for x in hyp) / len(hyp)) if hyp else float("nan"),
                           "accuracy": accuracy(ref, hyp) if ref else float("nan"),
                           "kappa": kappa(ref, hyp) if ref else float("nan")}
    for tol in (0, 1):
        counts = [match_boundaries(r, h, tol) for r, h in pairs]
        out[f"boundary_tol{tol}"] = prf(*(sum(c[i] for c in counts) for i in range(3)))
    out["window_diff"] = (sum(window_diff(r, h) for r, h in pairs) / len(pairs)) if pairs else float("nan")
    seq = [sequence_distance(r, h) for r, h in pairs]
    out["sequence"] = {
        "edit_distance": sum(d for d, _ in seq) / len(seq) if seq else float("nan"),
        "normalized": sum(x for _, x in seq) / len(seq) if seq else float("nan"),
        "identical": sum(1 for d, _ in seq if d == 0) / len(seq) if seq else float("nan")}
    return out


def bootstrap(pairs: Pairs, stat: Callable[[Pairs], float], reps: int = 2000,
              seed: int = 20261010, level: float = 0.95) -> Tuple[float, float]:
    """Percentile confidence interval of ``stat`` over trajectories resampled with
    replacement; (nan, nan) for fewer than two trajectories."""
    if len(pairs) < 2:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    values = sorted(stat([pairs[rng.randrange(len(pairs))] for _ in pairs]) for _ in range(reps))
    lo = values[int((1 - level) / 2 * reps)]
    hi = values[min(reps - 1, int((1 + level) / 2 * reps))]
    return lo, hi


def pooled_kappa(pairs: Pairs) -> float:
    return kappa([x for r, _ in pairs for x in r], [x for _, h in pairs for x in h])


def pooled_boundary_f1(tol: int) -> Callable[[Pairs], float]:
    def stat(pairs: Pairs) -> float:
        counts = [match_boundaries(r, h, tol) for r, h in pairs]
        return prf(*(sum(c[i] for c in counts) for i in range(3)))["f1"]
    return stat
