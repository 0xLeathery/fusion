#!/usr/bin/env python3
"""Router benchmark for model-fusion.

Runs the real hooks/fusion-router.sh over a labelled prompt set and scores how
well its no-model-call heuristic separates hard prompts (should fire) from easy
ones (should stay silent). Deterministic, no API, no budget.

Usage:
  python3 eval/router/run_router_eval.py [--labels FILE] [--mode selective|always|off]
                                         [--min-f1 X] [--quiet]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "hooks" / "fusion-router.sh"


def fired(prompt: str, mode: str) -> bool:
    """True if the router injects context (non-empty stdout) for this prompt."""
    env = dict(os.environ, FUSION_MODE=mode)
    proc = subprocess.run(
        ["bash", str(ROUTER)],
        input=json.dumps({"prompt": prompt}),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"router exited {proc.returncode}: {proc.stderr.strip()}")
    return bool(proc.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(Path(__file__).with_name("labels.jsonl")))
    ap.add_argument("--mode", default="selective", choices=["selective", "always", "off"])
    ap.add_argument("--min-f1", type=float, default=None,
                    help="exit non-zero if F1 falls below this (for CI)")
    ap.add_argument("--quiet", action="store_true", help="suppress per-item misses")
    args = ap.parse_args()

    if not ROUTER.exists():
        print(f"router not found: {ROUTER}", file=sys.stderr)
        return 2

    items = [json.loads(l) for l in Path(args.labels).read_text().splitlines() if l.strip()]

    tp = fp = tn = fn = 0
    misses = []
    for it in items:
        is_hard = it["label"] == "hard"
        did_fire = fired(it["prompt"], args.mode)
        if is_hard and did_fire:
            tp += 1
        elif is_hard and not did_fire:
            fn += 1
            misses.append((it["id"], "MISS (hard, stayed silent)", it["prompt"]))
        elif not is_hard and did_fire:
            fp += 1
            misses.append((it["id"], "FALSE FIRE (easy, fired)", it["prompt"]))
        else:
            tn += 1

    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else float("nan")
    acc = (tp + tn) / len(items) if items else float("nan")

    print(f"Router benchmark — mode={args.mode}, n={len(items)}")
    print(f"  confusion: TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  precision={prec:.3f}  recall={rec:.3f}  f1={f1:.3f}  accuracy={acc:.3f}")
    if misses and not args.quiet:
        print("  misclassified:")
        for mid, kind, prompt in misses:
            snippet = (prompt[:70] + "…") if len(prompt) > 70 else prompt
            print(f"    [{mid}] {kind}: {snippet}")

    if args.min_f1 is not None and (f1 != f1 or f1 < args.min_f1):
        print(f"FAIL: f1 {f1:.3f} < --min-f1 {args.min_f1}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
