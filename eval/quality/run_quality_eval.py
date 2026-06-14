#!/usr/bin/env python3
"""Quality + cost harness for model-fusion.

Drives Claude Code in headless mode across three condition families and grades
the answers with objective graders:

  single          one pass (FUSION_MODE=off)              -- naive reference
  selfconsist:N   N independent passes, aggregated        -- the HONEST baseline
  fusion:N        /fuse with an N-panellist panel         -- the plugin

The point of the harness is the fusion:N vs selfconsist:N comparison at equal
token budget. See eval/README.md for the methodology and the caveats about
Claude Code internals (slash commands / token fields) you should verify.

Start with --dry-run: it simulates answers and synthetic (N+1)x token counts so
the grading, stats, and cost math run end-to-end without spending budget.
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402

# Repo root == the plugin dir (it holds .claude-plugin/). Forward it to every
# headless `claude -p` so `fusion:N` can load /fuse without a separate install.
# Derived from __file__ so the harness stays portable across checkouts.
PLUGIN_DIR = str(Path(__file__).resolve().parents[2])


# ---- grading ---------------------------------------------------------------

def grade(gtype, gold, text):
    """Return True/False, or None if no answer could be extracted."""
    if text is None:
        return None
    if gtype == "numeric":
        nums = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
        if not nums:
            return None
        return abs(float(nums[-1]) - float(gold)) < 1e-6
    if gtype == "mcq":
        m = re.search(r"\b([A-D])\b", text.upper())
        if not m:
            return None
        return m.group(1) == str(gold).upper()
    if gtype == "exact":
        return text.strip().lower() == str(gold).strip().lower()
    if gtype == "code":
        # gold is a spec dict: {entry_point, tests, [examples], [canonical]}.
        return run_code_tests(extract_code(text), gold)
    raise ValueError(f"unknown grader type: {gtype}")


def extract_answer(gtype, text):
    """Normalised answer token, for self-consistency voting."""
    if text is None:
        return None
    if gtype == "numeric":
        nums = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
        return nums[-1] if nums else None
    if gtype == "mcq":
        m = re.search(r"\b([A-D])\b", text.upper())
        return m.group(1) if m else None
    return text.strip().lower()


# ---- code execution (for type: "code") -------------------------------------
#
# SECURITY: grading code tasks EXECUTES model-generated Python in a subprocess.
# Run only datasets and model outputs you trust. Execution is isolated to a
# subprocess with a wall-clock timeout, but this is NOT a security sandbox (no
# syscall / network / filesystem confinement). HumanEval-style harnesses carry
# the same caveat.

_CODE_EXEC_WARNED = False


def _warn_code_exec():
    global _CODE_EXEC_WARNED
    if not _CODE_EXEC_WARNED:
        print("  ! code grading executes model-generated Python in a subprocess "
              "(timeout-guarded, NOT sandboxed)", file=sys.stderr)
        _CODE_EXEC_WARNED = True


def extract_code(text):
    """Pull a Python solution from a model reply: prefer the largest fenced
    block, else the raw text."""
    if not text:
        return None
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()
    return text.strip() or None


def _exec_program(program, timeout):
    """Run a self-contained Python program in a subprocess. True iff it exits 0."""
    _warn_code_exec()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(program)
        path = f.name
    try:
        proc = subprocess.run([sys.executable, path], capture_output=True,
                              text=True, timeout=timeout,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _check_program(solution, check_src, entry_point):
    """A solution + a `def check(candidate)` block + the call that runs it."""
    return f"{solution}\n\n{check_src}\n\ncheck({entry_point})\n"


def run_code_tests(solution, spec, timeout=15):
    """Grade a code solution against its HIDDEN test `check`. None if no code."""
    if not solution:
        return None
    return _exec_program(
        _check_program(solution, spec.get("tests", ""), spec.get("entry_point", "")),
        timeout)


def select_best_code(candidates, spec):
    """Honest self-consistency for code: return the first candidate that passes
    the VISIBLE example tests (never the hidden ones). No examples, or none pass
    -> first candidate. With no visible oracle you genuinely can't do better, so
    this neither cheats toward nor against fusion."""
    cands = [c for c in candidates if c]
    if not cands:
        return None
    examples = spec.get("examples")
    if not examples:
        return cands[0]
    ep = spec.get("entry_point", "")
    for c in cands:
        if _exec_program(_check_program(c, examples, ep), timeout=10):
            return c
    return cands[0]


# ---- invocation ------------------------------------------------------------

def invoke_claude(prompt, model, fusion_mode, dry_run, sim):
    """Run one Claude Code pass. Returns (text, total_tokens, cost)."""
    if dry_run:
        # Simulate: emit the gold answer with a per-condition success rate, and
        # synthetic token counts so the cost math is exercised. Plumbing only.
        gtype, gold, p_correct, tokens = sim
        rng = random.Random(hash((prompt, fusion_mode, random.random())) & 0xFFFFFFFF)
        correct = rng.random() < p_correct
        if gtype == "code":
            # Emit the reference solution (passes) or a stub (fails) and let the
            # real executable grader run it -- so --dry-run actually exercises the
            # code grader end-to-end, at zero API cost.
            ep = gold.get("entry_point", "f")
            sol = gold.get("canonical", "") if correct else (
                f"def {ep}(*args, **kwargs):\n    raise Exception('stub')")
            return f"```python\n{sol}\n```", tokens, None
        if correct:
            ans = str(gold)
        elif gtype == "mcq":
            ans = rng.choice([c for c in "ABCD" if c != str(gold)])
        elif gtype == "numeric":
            ans = str(int(gold) + rng.choice([-2, -1, 1, 2]))
        else:
            ans = "wrong"
        return f"The answer is {ans}.", tokens, None

    env = dict(os.environ, FUSION_MODE=fusion_mode)
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--plugin-dir", PLUGIN_DIR]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        print(f"  ! claude exited {proc.returncode}: {proc.stderr.strip()[:200]}",
              file=sys.stderr)
        return None, None, None
    text, tokens, cost = _parse_output(proc.stdout)
    return text, tokens, cost


def _parse_output(stdout):
    """Defensive parse of `claude -p --output-format json`. Field names vary by
    version, so try several and fall back to None (logged, not crashed)."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return (stdout.strip() or None), None, None
    text = data.get("result") or data.get("text") or data.get("response")
    usage = data.get("usage") or {}
    inp = usage.get("input_tokens") or usage.get("inputTokens") or 0
    out = usage.get("output_tokens") or usage.get("outputTokens") or 0
    tokens = (inp + out) or None
    cost = data.get("total_cost_usd") or data.get("cost_usd")
    return text, tokens, cost


# ---- conditions ------------------------------------------------------------

def run_condition(cond, task, model, dry_run, sim):
    """Run one (condition, task) and return (text_for_grading, total_tokens)."""
    name, _, n = cond.partition(":")
    n = int(n) if n else 1

    if name == "single":
        text, tok, _ = invoke_claude(task["task"], model, "off", dry_run, sim)
        return text, tok

    if name == "selfconsist":
        # The honest baseline: N independent samples, aggregated, summed cost.
        if task["type"] == "code":
            # Can't majority-vote source strings (every sample differs). Select
            # by visible example tests only -- the honest, deployable aggregator.
            cands, total = [], 0
            for _ in range(n):
                text, tok, _ = invoke_claude(task["task"], model, "off", dry_run, sim)
                total += tok or 0
                code = extract_code(text)
                if code:
                    cands.append(code)
            if not cands:
                return None, total or None
            return select_best_code(cands, task["answer"]), (total or None)
        answers, total = [], 0
        for _ in range(n):
            text, tok, _ = invoke_claude(task["task"], model, "off", dry_run, sim)
            total += tok or 0
            a = extract_answer(task["type"], text)
            if a is not None:
                answers.append(a)
        if not answers:
            return None, total or None
        winner = Counter(answers).most_common(1)[0][0]
        return f"voted answer: {winner}", (total or None)

    if name == "fusion":
        # Panel via /fuse. The skill decides panel size; we request N. See caveats.
        prompt = f"/fuse {task['task']}"
        text, tok, _ = invoke_claude(prompt, model, "always", dry_run, sim)
        return text, tok

    raise ValueError(f"unknown condition: {cond}")


# ---- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--conditions", default="single,selfconsist:3,fusion:3")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--dry-run", action="store_true",
                    help="simulate answers + synthetic (N+1)x tokens; no API")
    args = ap.parse_args()

    tasks = [json.loads(l) for l in Path(args.dataset).read_text().splitlines() if l.strip()]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]

    # Per-condition simulation knobs for --dry-run (illustrative only).
    base_tokens = 900  # ~ one pass
    sim_p = {"single": 0.55, "selfconsist": 0.68, "fusion": 0.80}

    records = []
    for cond in conditions:
        name, _, n = cond.partition(":")
        n = int(n) if n else 1
        # Synthetic per-invocation cost. selfconsist makes N calls that get summed
        # downstream, so each is 1x; fusion is one call returning the panel's
        # (N+1)x. Net budget: single=1x, selfconsist:N=Nx, fusion:N=(N+1)x.
        mult = {"single": 1, "selfconsist": 1, "fusion": n + 1}[name]
        for rep in range(args.repeats):
            for task in tasks:
                sim = (task["type"], task["answer"], sim_p[name], base_tokens * mult)
                text, tokens = run_condition(cond, task, args.model, args.dry_run, sim)
                correct = grade(task["type"], task["answer"], text)
                records.append({
                    "condition": cond, "task_id": task["id"], "repeat": rep,
                    "type": task["type"], "correct": correct,
                    "total_tokens": tokens, "answer_text": text,
                })
                mark = {True: "ok", False: "X", None: "?"}[correct]
                print(f"[{cond:<14}] {task['id']:<4} rep{rep} -> {mark} "
                      f"({tokens or '?'} tok)")

    Path(args.out).write_text("\n".join(json.dumps(r) for r in records) + "\n")
    print(f"\nwrote {len(records)} records to {args.out}")
    if args.dry_run:
        print("(--dry-run: answers and token counts are SIMULATED, not real)")
    print()
    metrics.summarise(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
