#!/usr/bin/env python3
"""Statistics for the model-fusion quality harness.

Importable (used by run_quality_eval.py) and runnable on a saved results file:

  python3 eval/quality/metrics.py results.jsonl
"""
import json
import math
import random
import sys
from collections import defaultdict


def bootstrap_ci(values, iters=10000, alpha=0.05, seed=0):
    """Percentile bootstrap CI for the mean of a list of 0/1 (or float) values."""
    vals = list(values)
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(vals)
    means = []
    for _ in range(iters):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((alpha / 2) * iters)]
    hi = means[int((1 - alpha / 2) * iters) - 1]
    return (lo, hi)


def mcnemar_exact(a_correct, b_correct):
    """Two-sided exact McNemar test over paired boolean lists.

    Returns (b, c, p) where b = a-right/b-wrong, c = a-wrong/b-right discordant
    pairs, and p is the exact binomial two-sided p-value on the discordants.
    """
    b = sum(1 for a, bb in zip(a_correct, b_correct) if a and not bb)
    c = sum(1 for a, bb in zip(a_correct, b_correct) if (not a) and bb)
    n = b + c
    if n == 0:
        return (b, c, 1.0)
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return (b, c, min(1.0, 2 * tail))


def _per_task_correct(records):
    """Collapse repeats: task -> majority-correct boolean, per condition."""
    by = defaultdict(lambda: defaultdict(list))  # cond -> task -> [bool]
    for r in records:
        if r.get("correct") is not None:
            by[r["condition"]][r["task_id"]].append(bool(r["correct"]))
    out = {}
    for cond, tasks in by.items():
        out[cond] = {t: (sum(v) > len(v) / 2) for t, v in tasks.items()}
    return out


def summarise(records):
    conds = sorted({r["condition"] for r in records})

    print("Accuracy (per-sample, with 95% bootstrap CI):")
    flat = defaultdict(list)
    for r in records:
        if r.get("correct") is not None:
            flat[r["condition"]].append(1 if r["correct"] else 0)
    for c in conds:
        v = flat.get(c, [])
        if not v:
            print(f"  {c:<16} n=0  (no graded samples)")
            continue
        lo, hi = bootstrap_ci(v)
        print(f"  {c:<16} acc={sum(v)/len(v):.3f}  [{lo:.3f},{hi:.3f}]  n={len(v)}")

    print("\nCost (mean tokens/query, ratio vs single):")
    tok = defaultdict(list)
    for r in records:
        t = r.get("total_tokens")
        if t is not None:
            tok[r["condition"]].append(t)
    base = (sum(tok["single"]) / len(tok["single"])) if tok.get("single") else None
    for c in conds:
        v = tok.get(c, [])
        if not v:
            print(f"  {c:<16} (no token data)")
            continue
        mean = sum(v) / len(v)
        ratio = f"{mean/base:.2f}x" if base else "n/a"
        print(f"  {c:<16} mean={mean:,.0f}  ratio={ratio}")

    # The headline test: each fusion:N vs the SELF-CONSISTENCY condition closest
    # to it in measured token budget. Pairing on N would be dishonest -- fusion:N
    # costs (N+1)x but selfconsist:N only costs Nx -- so we match on actual spend.
    mean_tok = {c: (sum(v) / len(v)) for c, v in tok.items() if v}
    per_task = _per_task_correct(records)
    sc_conds = [c for c in conds if c.startswith("selfconsist")]
    print("\nHonest-baseline comparison (fusion vs budget-matched self-consistency):")
    printed = False
    for c in conds:
        if not c.startswith("fusion:"):
            continue
        cands = [s for s in sc_conds if s in mean_tok and c in mean_tok]
        if not cands:
            print(f"  {c}: no self-consistency baseline with token data to match")
            continue
        base_cond = min(cands, key=lambda s: abs(mean_tok[s] - mean_tok[c]))
        budget_note = ""
        if mean_tok.get(c):
            r = mean_tok[base_cond] / mean_tok[c]
            budget_note = f", budget {r:.2f}x of fusion" + (
                "" if 0.85 <= r <= 1.15 else "  [NOT well budget-matched]")
        tasks = sorted(set(per_task.get(c, {})) & set(per_task.get(base_cond, {})))
        a = [per_task[c][t] for t in tasks]
        b = [per_task[base_cond][t] for t in tasks]
        bb, cc, p = mcnemar_exact(a, b)
        fa = sum(a) / len(a) if a else 0
        fb = sum(b) / len(b) if b else 0
        print(f"  {c} ({fa:.3f}) vs {base_cond} ({fb:.3f}): "
              f"discordant fusion+/-={bb}/{cc}, p={p:.3f} "
              f"(n_tasks={len(tasks)}{budget_note})")
        printed = True
    if not printed:
        print("  (need a fusion:N condition and at least one selfconsist:N)")


def main():
    if len(sys.argv) != 2:
        print("usage: python3 metrics.py results.jsonl", file=sys.stderr)
        return 2
    records = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
    summarise(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
