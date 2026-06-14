# Published baseline

Two tiers, because two very different things are being baselined. Don't conflate them.

| Tier | What it baselines | Determinism | Cost | Where it's published |
|------|-------------------|-------------|------|----------------------|
| **1 — Router** | Does the heuristic fire on hard prompts, stay quiet on easy ones? | Deterministic (fixed labels + no-model-call heuristic) | Free | CI gate (`.github/workflows/eval.yml`) + the numbers below |
| **2 — Quality** | Does fusion beat the *honest* (equal-budget self-consistency) baseline? | Noisy (real model sampling) | Real budget | Committed snapshot, human-generated |

---

## Tier 1 — Router baseline (the published, gated one)

Deterministic, so this is the number we publish and gate on. Regenerate any time with:

```bash
python3 eval/router/run_router_eval.py
```

**Baseline — `selective` mode, n=36 labelled prompts** (CLI 2.1.177, 2026-06-15):

```
confusion: TP=16 FP=1 FN=2 TN=17
precision=0.941  recall=0.889  f1=0.914  accuracy=0.917
```

Known misclassifications carried in this baseline (the heuristic is intentionally
cheap — no model call):

- `h09` — *"We have a memory leak in production. Walk through how you would isolate…"* → **miss** (hard, no analytical keyword / under length).
- `h13` — *"Walk me through the security implications of allowing user-supplied te…"* → **miss**.
- `e11` — *"Compare these two strings for equality in Python."* → **false fire** (the keyword `compare` trips it on a trivial ask).

**CI gate:** `eval/router/run_router_eval.py --min-f1 0.90`. The floor sits below the
current 0.914 so expanding `labels.jsonl` doesn't flake the build, while a real
routing regression (a keyword/length-rule change that drops F1) fails it. Bump the
floor if you tighten the heuristic and want to lock the gain in.

---

## Tier 2 — Quality baseline (the committed snapshot)

This is the repo's actual thesis — **personas + synthesis beat spending the same
tokens on more samples of one model** — so it's the baseline worth publishing for
quality. It cannot be a CI gate:

- it makes **real model calls** (cost, and non-deterministic run-to-run), and
- driving `fusion:N` headless requires a **permission-bypassed agent** (the panel's
  subagent spawns are auto-declined in `claude -p` with no human approver), which is
  not something to run unattended in CI.

So it's published as a **frozen snapshot**, generated once by a human, not as a live
check.

### Do NOT baseline on `datasets/sample.jsonl`

The bundled sample is **plumbing-only** — 10 easy numeric/MCQ items, there to prove
the harness runs. Publishing quality numbers off it would be misleading. Swap in a
genuinely hard, **objective** set first: GPQA-diamond, MMLU-Pro (hard subset),
MATH/AIME, or executable pass/fail tasks. Format each line as:

```json
{"id": "...", "type": "numeric|mcq|exact", "task": "...", "answer": "..."}
```

### Procedure (run in a trusted local terminal, not CI)

1. Put a real objective dataset at `eval/quality/datasets/<name>.jsonl`.
2. Make the headless panel actually fan out. The harness shells out to `claude -p`
   (`run_quality_eval.py`, `invoke_claude`); for `fusion:N` to spawn its panel you
   must authorise the subagent spawns — add `--dangerously-skip-permissions` to that
   command **in your own terminal, where you own the authorisation**. Verify one call
   fans out (the result contains a `## Synthesis notes` block) before the full sweep.
3. Run the sweep with repeats for statistical stability — note `fusion:3` ≈ 4× tokens,
   so the budget-matched baseline is `selfconsist:4`, not `selfconsist:3`:

   ```bash
   python3 eval/quality/run_quality_eval.py \
     --dataset eval/quality/datasets/<name>.jsonl \
     --conditions single,selfconsist:3,selfconsist:4,fusion:3 \
     --repeats 5 --out eval/quality/baseline-<name>.jsonl --model opus
   ```

4. Summarise and **commit the snapshot** as the published baseline:

   ```bash
   python3 eval/quality/metrics.py eval/quality/baseline-<name>.jsonl
   ```

   Commit `baseline-<name>.jsonl` plus the summary, and record the metadata next to
   it: model, CLI version, dataset + size, `--repeats`, and date. That tuple is what
   makes the number reproducible.

### The headline number to publish

The only comparison that defends the plugin:

```
fusion:N  vs  budget-matched selfconsist:M   (McNemar exact p, paired)
```

plus per-condition **accuracy with 95% bootstrap CIs** and the **mean-token ratio**.
Fusion only earns its cost if it beats the budget-matched self-consistency run with a
real (significant, non-overlapping-CI) margin. Report the interval, not a point
estimate — single-run point deltas on small datasets are mostly sampling noise.
