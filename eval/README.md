# Evaluating `model-fusion`

This directory benchmarks the plugin. It is **not part of the shipped plugin
runtime** — it lives alongside it so the claims in the top-level `README.md` are
falsifiable. `claude plugin validate` ignores this directory.

## What we're actually testing

"Does fusion work?" splits into three separable claims, each with a very different
cost to measure:

| # | Claim | How we test it | Cost |
|---|-------|----------------|------|
| **R** | The router fires on hard prompts and stays quiet on easy ones | `router/` — run the deterministic hook over a labelled set | trivial, no API |
| **Q** | The fused answer beats the honest baseline on quality | `quality/` — headless runs over a dataset, objective grading | high (burns budget) |
| **C** | The panel costs ≈ (N+1)× tokens | `quality/` — token capture per condition | folded into Q |

## The one benchmark that matters: the *honest* baseline

The tempting comparison is **fused vs. single-pass**, but that is rigged — of course
spending (N+1)× more compute helps. The claim worth defending is that the *personas
+ synthesis* beat **spending the same tokens on more samples of the same model**.

So the baseline is not one answer; it is **equal-budget self-consistency**: draw N
independent samples and majority-vote (or judge-pick) them, at the *same total token
budget* as the panel. If fusion does not beat equal-budget self-consistency, the
personas and the synthesis rubric are not earning their cost — they are an expensive
way to sample more.

The harness therefore defines three condition families:

- `single` — one pass, `FUSION_MODE=off`. The naive reference.
- `selfconsist:N` — **the honest baseline.** N independent single passes, aggregated.
- `fusion:N` — the plugin: `/fuse` with an N-panellist panel.

### Ablations (test the README's ¾-synthesis / ¼-diversity split)

- **synthesis off vs on** (concatenate / pick-first vs. the rubric) → isolates the
  synthesis three-quarters.
- **distinct personas vs. 3× identical persona** → isolates the diversity quarter.
- **panel N = 2 / 3 / 5** → tests "the 1→2 jump captures most of it".

These are run by swapping conditions and (for the persona ablation) temporarily
pointing the panel at one repeated persona.

## Quality: use objective ground truth

LLM-judging self-fusion output with a model from the same family is circular, so
prefer tasks with **objective** answers: GPQA / MMLU-Pro (hard subset), MATH / AIME
(numeric), and executable tasks (LiveCodeBench / SWE-bench style, pass/fail by test
run). The bundled `quality/datasets/sample.jsonl` is **plumbing-only** — the items are
easy, there to prove the pipeline runs. Swap in a genuinely hard dataset for real
signal. Open-ended win-rate via a *separate, blinded* judge is the documented
extension (see "Not yet automated").

## Statistics hygiene (easy to skip, shouldn't be)

- This is a **paired** design (same tasks across conditions). Use **McNemar's test**
  for accuracy deltas and **bootstrap CIs** for the rates — both implemented in
  `quality/metrics.py`.
- Sampling variance is large. Run **multiple repeats/seeds** per task (`--repeats`)
  and report intervals, or you will "see" a few-point lift that is noise.
- Self-consistency needs **temperature > 0** for sample diversity. If your CLI build
  doesn't expose temperature, independent sessions still vary, but the baseline is
  weaker than it should be — note it.

## The self-fusion–specific number: correlated error

The structural weakness of one base model is **correlated error** — all panellists
confidently converging on the *same wrong* answer. Track the **agreement-but-wrong
rate**; it tells you whether the synthesis "anti-majority / correlated-error" guards
are doing anything. Measuring it needs the *individual* panellist answers, which
`/fuse` folds into synthesis — see "Not yet automated".

---

## Running it

### R — router benchmark (runnable now, no API)

```bash
python3 eval/router/run_router_eval.py
```

Pipes each labelled prompt through the real `hooks/fusion-router.sh` in `selective`
mode, treats non-empty output as "fired", and reports a confusion matrix,
precision/recall/F1, and every misclassification. Add `--min-f1 0.8` to make it exit
non-zero below a threshold (for CI). `--mode always|off` sanity-checks the other modes.

### Q / C — quality + cost harness

Validate the plumbing without spending a cent first — `--dry-run` simulates answers
and synthetic (N+1)× token counts so grading, stats, and cost math all execute.

Note the conditions: `fusion:3` costs ≈4× tokens, so the *budget-matched* baseline is
`selfconsist:4` (also 4×), **not** `selfconsist:3`. Include both — the harness pairs
`fusion:N` against whichever self-consistency run is closest in *measured* token spend
and flags the match if it's off.

```bash
python3 eval/quality/run_quality_eval.py \
  --dataset eval/quality/datasets/sample.jsonl \
  --conditions single,selfconsist:3,selfconsist:4,fusion:3 \
  --repeats 3 --dry-run --out /tmp/fusion_eval.jsonl
```

Then a real run (burns budget — small dataset first):

```bash
python3 eval/quality/run_quality_eval.py \
  --dataset eval/quality/datasets/sample.jsonl \
  --conditions single,selfconsist:3,selfconsist:4,fusion:3 \
  --repeats 3 --out results.jsonl --model opus
```

Re-summarise a saved results file at any time:

```bash
python3 eval/quality/metrics.py results.jsonl
```

## Caveats — verify against *your* installed Claude Code

The real-run path depends on Claude Code internals that you should confirm before
trusting the numbers:

1. **Headless slash commands.** The harness runs the panel via `claude -p "/fuse …"`.
   Confirm `/fuse` triggers in print mode in your build; otherwise set
   `FUSION_MODE=always` and pass the bare task.
2. **Token/cost fields.** It reads `--output-format json` and looks for `usage`
   (`input_tokens`/`output_tokens`) and `total_cost_usd`. Field names vary by version —
   the parser is defensive and logs `null` when it can't find them.
3. **Panel size.** `fusion:N` requests an N-panel via `/fuse`, but the `fusion` skill
   ultimately decides size. Pin it by editing the skill, or read the actual size back
   from the transcript.

## Not yet automated (documented next steps)

- **Open-ended win-rate** via an *independent, blinded, order-randomised* judge (use a
  different model family; never the synthesiser).
- **Correlated-error rate** — requires capturing per-panellist drafts (parse the
  session transcript, or add a panel-only mode that skips synthesis).
