"""Bars by Learn-then-Test, certification on the owner's gold labels, SPRT for monitoring.

Learn-then-Test (Angelopoulos et al.; MAPIE's BinaryClassificationController is the reference
implementation) with fixed-sequence testing: candidate bars are tested strictest first with an exact
binomial p-value for H0 "error rate >= delta", and testing stops at the first bar that is not
rejected, which is what makes the family-wise guarantee hold without a correction. Jev and the
second reader are one joint score (their minimum), so the guarantee is on the rule that ships.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from .questions import BOUNDS, TIERS

GRID: tuple[float, ...] = (
    0.999, 0.995, 0.99, 0.98, 0.97, 0.95, 0.93, 0.9, 0.85, 0.8, 0.7, 0.6, 0.5,
)


ALPHA = 0.05


def zero_error_rows_needed(delta: float, alpha: float = ALPHA) -> int:
    """Smallest n with (1 - delta)**n <= alpha: fewer clean rows can never reject H0."""
    return math.ceil(math.log(alpha) / math.log(1 - delta))


def binom_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    # log space: math.comb(n, j) * p**j overflows floats long before the probability is small
    log_p, log_q, base = math.log(p), math.log1p(-p), math.lgamma(n + 1)
    total = sum(
        math.exp(base - math.lgamma(j + 1) - math.lgamma(n - j + 1) + j * log_p + (n - j) * log_q)
        for j in range(k + 1)
    )
    return min(1.0, total)


def ltt_bar(
    scores_truth: list[tuple[float, bool]],
    delta: float,
    alpha: float = ALPHA,
    grid: Sequence[float] = GRID,
) -> float | None:
    passed: float | None = None
    for bar in sorted(grid, reverse=True):
        accepted = [truth for score, truth in scores_truth if score >= bar]
        errors = sum(1 for truth in accepted if not truth)
        if not accepted:
            continue  # accepting nothing carries no risk; the sequence goes on to a looser bar
        if binom_cdf(errors, len(accepted), delta) > alpha:
            break
        passed = bar
    return passed


def joint(jev_p: float | None, second_p: float | None) -> float | None:
    if jev_p is None or second_p is None:
        return None
    return min(jev_p, second_p)


def _score(row: dict[str, Any], policy: str) -> float | None:
    if policy == "jev":
        return row["jev"]  # type: ignore[no-any-return]
    return joint(row["jev"], row["second"])


def _accepted(row: dict[str, Any], policy: str, bar: float | None) -> bool:
    s = _score(row, policy)
    if s is not None and bar is not None and s >= bar:
        return True
    return (
        policy == "both_or_third"
        and row.get("third") is not None
        and row["jev"] is not None
        and row["second"] is not None
        and min(row["jev"], row["second"], row["third"]) >= 0.5
    )


def learn_bars(rows: list[dict[str, Any]], policy: str) -> dict[tuple[str, bool], float | None]:
    tune = [r for r in rows if r["half"] == "tune" and r["truth"] is not None]
    strata: dict[tuple[str, bool], list[tuple[float, bool]]] = defaultdict(list)
    for r in tune:
        s = _score(r, policy)
        if s is not None and s >= 0.5:
            strata[(TIERS[r["question"]], r["evidence"])].append((s, r["truth"]))
    return {key: ltt_bar(pairs, BOUNDS[key[0]]) for key, pairs in strata.items()}


def score_rows(
    rows: list[dict[str, Any]], policy: str, bars: dict[tuple[str, bool], float | None]
) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"accepted": 0, "wrong": 0, "true_yes": 0, "kept": 0, "missing": 0}
    )
    for r in rows:
        if r["half"] != "score" or r["truth"] is None:
            continue
        kind = TIERS[r["question"]]
        for group in (kind, f"{kind}/{r['language']}"):
            m = out[group]
            m["true_yes"] += int(r["truth"])
            if _score(r, policy) is None:
                m["missing"] += 1
            if _accepted(r, policy, bars.get((kind, r["evidence"]))):
                m["accepted"] += 1
                m["wrong"] += int(not r["truth"])
                m["kept"] += int(r["truth"])
    for group, m in out.items():
        right = m["accepted"] - m["wrong"]
        m["precision"] = right / m["accepted"] if m["accepted"] else float("nan")
        m["recall"] = m["kept"] / m["true_yes"] if m["true_yes"] else float("nan")
        m["upper_error_95"] = upper_error(m["wrong"], m["accepted"])
        if "/" in group:  # the per-language check: each language must meet the kind's bound alone
            m["passes"] = m["upper_error_95"] <= BOUNDS[group.split("/")[0]]
    return dict(out)


def upper_error(errors: int, n: int) -> float:
    """Exact one-sided 95% upper bound on the error rate; 1.0 when nothing was observed."""
    if n == 0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if binom_cdf(errors, n, mid) > 0.05:
            lo = mid
        else:
            hi = mid
    return hi


def sweep_lines(
    name: str, rows: list[dict[str, Any]], policy: str,
    bars: Any,
) -> list[str]:
    """Per kind, every GRID bar on the tune half: what a bar would accept and how sure that is."""
    lines = [f"### {name}: every bar on the tune half", "",
             "| kind | bar | accepted | errors | precision | 95% upper error |",
             "|---|---|---|---|---|---|"]
    notes: list[str] = []
    for kind in sorted(set(TIERS.values())):
        pairs = [(s, r["truth"]) for r in rows
                 if r["half"] == "tune" and r["truth"] is not None and TIERS[r["question"]] == kind
                 for s in [_score(r, policy)] if s is not None and s >= 0.5]
        for bar in GRID:
            hit = [truth for s, truth in pairs if s >= bar]
            errors = sum(1 for truth in hit if not truth)
            precision = f"{(len(hit) - errors) / len(hit):.4f}" if hit else "nan"
            lines.append(f"| {kind} | {bar} | {len(hit)} | {errors} | {precision} | "
                         f"{upper_error(errors, len(hit)):.4f} |")
        for (k, evidence), learned in sorted(bars.items(), key=str):
            if k == kind and learned is None:
                n = sum(1 for r in rows if r["half"] == "tune" and r["truth"] is not None
                        and TIERS[r["question"]] == kind and r["evidence"] == evidence
                        and (_score(r, policy) or 0) >= 0.5)
                needed = zero_error_rows_needed(BOUNDS[kind])
                why = (f"needs ≥{needed} zero-error rows" if n < needed
                       else "errors at every bar blocked it")
                notes.append(f"- {name} {kind} evidence={evidence}: no LTT bar at n={n} ({why})")
    return lines + [""] + notes + [""]


def certify(gold: list[tuple[str, bool]], kind: str) -> dict[str, Any]:
    n = len(gold)
    errors = sum(1 for _, ok in gold if not ok)
    needed = zero_error_rows_needed(BOUNDS[kind])
    return {
        "n": n,
        "errors": errors,
        "upper_error_95": upper_error(errors, n),
        "certified": errors == 0 and n >= needed,
        "needed": needed,
    }


def sprt(
    outcomes: Iterable[bool], p0: float, p1: float, alpha: float = 0.05, beta: float = 0.2
) -> str:
    upper, lower = math.log((1 - beta) / alpha), math.log(beta / (1 - alpha))
    llr = 0.0
    for error in outcomes:
        llr += math.log(p1 / p0) if error else math.log((1 - p1) / (1 - p0))
        if llr >= upper:
            return "alarm"
        if llr <= lower:
            return "ok"
    return "continue"


def report(
    results: dict[str, dict[str, Any]],
    bars: dict[str, dict[str, Any]],
    certification: dict[str, dict[str, Any]],
    costs: dict[str, float],
    sweeps: dict[str, list[dict[str, Any]]] | None = None,
    votes: dict[str, int] | None = None,
) -> str:
    lines = [
        "# Engine evaluation report",
        "",
        "Model-key results are TUNING results; only the certification table (owner's gold labels) "
        "certifies.",
        "",
        "| policy/reader | group | accepted | wrong | precision | recall | missing |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, groups in results.items():
        for group, m in sorted(groups.items()):
            lines.append(
                f"| {name} | {group} | {m['accepted']} | {m['wrong']} | {m['precision']:.4f} | "
                f"{m['recall']:.3f} | {m['missing']} |"
            )
    lines += ["", "| policy/reader | (kind, evidence) | bar |", "|---|---|---|"]
    for name, b in bars.items():
        lines += [f"| {name} | {k} | {v} |" for k, v in sorted(b.items(), key=str)]
    lines += [""]
    for name, rows in (sweeps or {}).items():
        lines += sweep_lines(name, rows, name.split("/")[0], bars[name])
    lines += [
        "Round-1 deadline and eligibility bars are uncalibrated: Learn-then-Test cannot certify "
        "them at this size, so any bar chosen from the tables above is a judgement, not a "
        "guarantee.",
        "",
        "| reader | vote rows (no probabilities; counted as no answer by `both`) |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in (votes or {}).items()]
    lines += [
        "",
        "| kind | gold n | errors | 95% upper error | needed | certified |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {k} | {c['n']} | {c['errors']} | {c['upper_error_95']:.4f} | {c['needed']} | "
        f"{c['certified']} |"
        for k, c in certification.items()
    ]
    lines += ["", "| cost item | USD |", "|---|---|"]
    lines += [f"| {k} | {v:.4f} |" for k, v in costs.items()]
    return "\n".join(lines) + "\n"
