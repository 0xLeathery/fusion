#!/usr/bin/env python3
"""Statistics for the model-fusion quality harness.

Importable (used by run_quality_eval.py) and runnable on a saved results file:

  python3 eval/quality/metrics.py results.jsonl
"""
import argparse
import json
import math
import random
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


def bootstrap_paired_diff_ci(a, b, iters=10000, alpha=0.05, seed=0):
    """Percentile bootstrap CI for the mean paired difference mean(a_i - b_i)
    over paired 0/1 lists. This is the correct interval for a '+X points'
    accuracy-delta claim: it resamples *tasks*, preserving the pairing."""
    diffs = [ai - bi for ai, bi in zip(a, b)]
    if not diffs:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(iters):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
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


def headline(records, label=None):
    """Print the one-line, publishable claim for each fusion:N vs its
    budget-matched self-consistency baseline. Code-generated so the number
    committed to the repo can't drift from the data, and honest by
    construction: it states the *signed* delta, the 95% paired-bootstrap CI,
    the McNemar p, and an explicit verdict on whether the CI excludes zero.

    Pass --label to embed the dataset/model/date metadata that makes the claim
    reproducible (the records themselves don't carry it)."""
    tok = defaultdict(list)
    for r in records:
        t = r.get("total_tokens")
        if t is not None:
            tok[r["condition"]].append(t)
    mean_tok = {c: sum(v) / len(v) for c, v in tok.items() if v}
    per_task = _per_task_correct(records)
    conds = sorted({r["condition"] for r in records})
    sc = [c for c in conds if c.startswith("selfconsist")]
    fusions = [c for c in conds if c.startswith("fusion:")]
    meta = f" [{label}]" if label else " [add: dataset, model, repeats, date, cli]"

    if not fusions:
        print("no fusion:N condition in results — nothing to claim")
        return
    for c in fusions:
        budget = None
        cands = [s for s in sc if s in mean_tok and c in mean_tok]
        if cands:
            base = min(cands, key=lambda s: abs(mean_tok[s] - mean_tok[c]))
            budget = mean_tok[base] / mean_tok[c]
        else:
            cands = [s for s in sc
                     if set(per_task.get(s, {})) & set(per_task.get(c, {}))]
            if not cands:
                print(f"{c}: no self-consistency baseline to compare — no claim")
                continue
            base = cands[0]  # no token data to budget-match; flagged below

        tasks = sorted(set(per_task.get(c, {})) & set(per_task.get(base, {})))
        if not tasks:
            print(f"{c}: no shared tasks with {base} — no claim")
            continue
        a = [1 if per_task[c][t] else 0 for t in tasks]
        b = [1 if per_task[base][t] else 0 for t in tasks]
        fa, fb, delta = sum(a) / len(a), sum(b) / len(b), (sum(a) - sum(b)) / len(a)
        lo, hi = bootstrap_paired_diff_ci(a, b)
        _, _, p = mcnemar_exact([bool(x) for x in a], [bool(x) for x in b])

        if lo > 0:
            verdict = "fusion beats the budget-matched baseline (95% CI excludes 0)"
        elif hi < 0:
            verdict = "fusion is WORSE than the baseline (95% CI excludes 0)"
        else:
            verdict = "no significant difference (95% CI includes 0)"
        if budget is None:
            budget_str = ", budget UNMATCHED (no token data)"
        elif 0.85 <= budget <= 1.15:
            budget_str = f", budget {budget:.2f}x"
        else:
            budget_str = f", budget {budget:.2f}x [NOT well-matched]"

        print(
            f"CLAIM ({c} vs {base}): {fa*100:.1f}% vs {fb*100:.1f}% = "
            f"{delta*100:+.1f} pts (95% CI [{lo*100:+.1f}, {hi*100:+.1f}]), "
            f"McNemar p={p:.3f}, n={len(tasks)} tasks{budget_str} — {verdict}.{meta}"
        )


def main():
    ap = argparse.ArgumentParser(
        description="Summarise model-fusion quality results.")
    ap.add_argument("results", help="path to a results.jsonl from run_quality_eval.py")
    ap.add_argument("--headline", action="store_true",
                    help="print the one-line publishable claim (paired-diff CI + McNemar)")
    ap.add_argument("--label", default=None,
                    help="metadata embedded in the claim, e.g. "
                         "'dataset=GPQA-diamond model=opus repeats=5 date=2026-06-15 cli=2.1.177'")
    args = ap.parse_args()
    records = [json.loads(l) for l in open(args.results) if l.strip()]
    if args.headline:
        headline(records, args.label)
    else:
        summarise(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
