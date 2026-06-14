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
import doctest
import json
import random
import re
import sys
import textwrap
from pathlib import Path

TASK_TMPL = (
    "Solve this Python problem. Provide a complete, self-contained function named "
    "`{ep}` (include any imports it needs). Return only the code in a single "
    "```python block.\n\n{prompt}"
)


def visible_examples(prompt, entry_point):
    """Best-effort: turn the docstring's >>> doctests into a `check(candidate)` of
    VISIBLE asserts. Returns the check string, or None if nothing usable parsed."""
    # Parse the docstring body (dedented) rather than the whole function source --
    # feeding code at column 0 to doctest trips its inconsistent-whitespace check.
    m = re.search(r'(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', prompt, re.DOTALL)
    doc = textwrap.dedent(m.group(1)) if m else prompt
    try:
        exs = doctest.DocTestParser().get_examples(doc)
    except Exception:
        return None
    lines = []
    for ex in exs:
        src, want = ex.source.strip(), ex.want.strip()
        if not want or "\n" in want or "Traceback" in want:
            continue
        call = re.sub(rf"\b{re.escape(entry_point)}\s*\(", "candidate(", src)
        if "candidate(" not in call:
            continue
        lines.append(f"    assert ({call}) == ({want})")
    if not lines:
        return None
    return "def check(candidate):\n" + "\n".join(lines)


def to_record(row):
    ep = row["entry_point"]
    return {
        "id": row["task_id"],
        "type": "code",
        "task": TASK_TMPL.format(ep=ep, prompt=row["prompt"].rstrip()),
        "answer": {
            "entry_point": ep,
            "tests": row["test"],
            "examples": visible_examples(row["prompt"], ep),
            "canonical": row["prompt"] + row["canonical_solution"],
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
