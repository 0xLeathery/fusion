#!/usr/bin/env python3
"""Build a HumanEval code dataset in the run_quality_eval.py JSONL shape.

HumanEval (openai/human-eval, MIT) is 164 self-contained Python problems, each
graded by executing the candidate against a hidden `check`. This converts it to:

  {"id": "...", "type": "code", "task": "<prompt>",
   "answer": {"entry_point": ..., "tests": ..., "examples": ..., "canonical": ...}}

  - tests     : the hidden `check` (used to grade).
  - examples  : VISIBLE doctest asserts only, best-effort (used by self-consistency
                selection so the baseline never peeks at hidden tests). May be null.
  - canonical : a full reference solution (prompt + canonical body) so --dry-run can
                exercise the executable grader without an API call.

Fetching needs the `datasets` package:  pip install datasets
Output is gitignored (redistribution + size) -- commit the metrics snapshot from a
run, not the raw dataset.

  python3 eval/quality/datasets/build_humaneval.py            # all 164
  python3 eval/quality/datasets/build_humaneval.py --n 40     # seeded sample
  python3 eval/quality/datasets/build_humaneval.py --selftest # no network
"""
import argparse
import ast
import doctest
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

TASK_TMPL = (
    "Solve this Python problem. Provide a complete, self-contained function named "
    "`{ep}` (include any imports it needs). Return only the code in a single "
    "```python block.\n\n{prompt}"
)


def _valid_expr(s):
    try:
        ast.parse(s, mode="eval")
        return True
    except (SyntaxError, ValueError):
        return False


def _example_pairs(prompt, entry_point):
    """Extract (call, expected) example pairs from a docstring. Handles `>>>`
    doctests and HumanEval's inline `f(x) ==> y` / `=> ` / `-> ` / `→` style. Each
    side must parse as a Python expression (a malformed one would break the check)."""
    m = re.search(r'(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', prompt, re.DOTALL)
    doc = textwrap.dedent(m.group(1)) if m else prompt
    pairs = []

    try:  # 1) `>>>` doctests.
        for ex in doctest.DocTestParser().get_examples(doc):
            src, want = ex.source.strip(), ex.want.strip()
            if want and "\n" not in want and "Traceback" not in want:
                call = re.sub(rf"\b{re.escape(entry_point)}\s*\(", "candidate(", src)
                pairs.append((call, want))
    except Exception:
        pass

    for line in doc.splitlines():  # 2) inline arrows (check ==> before =>).
        s = line.strip()
        for sep in ("==>", "=>", "->", "→"):
            if sep in s:
                lhs, _, rhs = s.partition(sep)
                cm = re.search(rf"\b{re.escape(entry_point)}\s*\((.*)\)\s*$", lhs.strip())
                rhs = rhs.strip().rstrip(".")
                if cm and rhs:
                    pairs.append((f"candidate({cm.group(1)})", rhs))
                break

    seen, out = set(), []
    for call, want in pairs:
        if ("candidate(" in call and _valid_expr(call) and _valid_expr(want)
                and (call, want) not in seen):
            seen.add((call, want))
            out.append((call, want))
    return out


def _canonical_satisfies(canonical, entry_point, call, want):
    """Run the reference solution against one example assert. Drops loose/rounded
    docstring examples (e.g. truncated floats) that a CORRECT solution fails, so
    self-consistency selection never rejects a right answer on a bad example."""
    prog = f"{canonical}\ncandidate = {entry_point}\nassert ({call}) == ({want})\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(prog)
        path = f.name
    try:
        return subprocess.run([sys.executable, path], capture_output=True,
                              timeout=8).returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def visible_examples(prompt, entry_point, canonical):
    """A `check(candidate)` of VISIBLE example asserts the reference solution
    satisfies. Returns the check string, or None if nothing usable survives."""
    kept = [(c, w) for c, w in _example_pairs(prompt, entry_point)
            if _canonical_satisfies(canonical, entry_point, c, w)]
    if not kept:
        return None
    return "def check(candidate):\n" + "\n".join(
        f"    assert ({c}) == ({w})" for c, w in kept)


def to_record(row):
    ep = row["entry_point"]
    canonical = row["prompt"] + row["canonical_solution"]
    return {
        "id": row["task_id"],
        "type": "code",
        "task": TASK_TMPL.format(ep=ep, prompt=row["prompt"].rstrip()),
        "answer": {
            "entry_point": ep,
            "tests": row["test"],
            "examples": visible_examples(row["prompt"], ep, canonical),
            "canonical": canonical,
        },
    }


def _selftest():
    row = {
        "task_id": "HumanEval/test",
        "entry_point": "add",
        "prompt": 'def add(a, b):\n    """Return a + b.\n    >>> add(2, 3)\n    5\n    """\n',
        "canonical_solution": "    return a + b\n",
        "test": "def check(candidate):\n    assert candidate(2, 3) == 5\n",
    }
    rec = to_record(row)
    print(json.dumps(rec, indent=2))
    assert rec["type"] == "code" and rec["answer"]["entry_point"] == "add"
    assert rec["answer"]["examples"] and "candidate(2, 3)" in rec["answer"]["examples"]
    assert rec["answer"]["canonical"].rstrip().endswith("return a + b")
    print("selftest OK", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval/quality/datasets/humaneval.jsonl")
    ap.add_argument("--n", type=int, default=None, help="sample N problems (seeded)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--selftest", action="store_true",
                    help="run the converter on a synthetic row; no network")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return 0

    try:
        from datasets import load_dataset  # type: ignore[import-not-found]
    except ImportError:
        sys.exit("need `datasets`: pip install datasets")
    rows = list(load_dataset("openai_humaneval")["test"])
    if args.n:
        rows = random.Random(args.seed).sample(rows, min(args.n, len(rows)))
    recs = [to_record(r) for r in rows]
    Path(args.out).write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    n_ex = sum(1 for r in recs if r["answer"]["examples"])
    print(f"wrote {len(recs)} problems to {args.out} "
          f"({n_ex} with visible examples for self-consistency selection; "
          f"{len(recs) - n_ex} fall back to first-sample)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
