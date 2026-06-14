# Results — measured quality lift

> **STATUS: PENDING MEASUREMENT.** No quality lift has been measured yet. The
> headline below is a placeholder. Do **not** cite a number until it is generated
> from a real run by `metrics.py --headline` and the backing snapshot is committed
> (see "How this is generated"). The repo's only *measured* number today is the
> deterministic router baseline (F1 0.914) in [`eval/BASELINE.md`](eval/BASELINE.md) —
> that measures **routing**, not answer quality.

## Headline claim

```
PENDING — fill from:  python3 eval/quality/metrics.py <snapshot>.jsonl --headline --label "..."

CLAIM (fusion:N vs selfconsist:M): <fa>% vs <fb>% = <±Δ> pts
  (95% CI [<lo>, <hi>]), McNemar p=<p>, n=<tasks> tasks, budget <r>x — <verdict>.
  [dataset=<...> model=<...> repeats=<...> date=<...> cli=<...>]
```

The claim is **honest by construction**: it is stated as absolute accuracy points
against the **budget-matched self-consistency** baseline (not single-pass), carries a
95% paired-bootstrap CI and a McNemar p, and the verdict says outright whether the CI
excludes zero. If fusion does not beat the baseline, that is the published result —
report it anyway.

## Summary table

| Condition | Accuracy (95% CI) | Mean tokens | Ratio vs single |
|-----------|-------------------|-------------|-----------------|
| `single` | _pending_ | _pending_ | 1.00x |
| `selfconsist:3` | _pending_ | _pending_ | _pending_ |
| `selfconsist:4` (budget-matched to `fusion:3`) | _pending_ | _pending_ | _pending_ |
| `fusion:3` | _pending_ | _pending_ | _pending_ |

Fill from `python3 eval/quality/metrics.py <snapshot>.jsonl` (full summariser).

## What "+X%" means here

- **Absolute accuracy points**, with the baseline shown — `82% vs 71% (+11 pts)`, not a
  bare `+15%`. "Improve by X%" is ambiguous (absolute vs relative vs win-rate); we
  report points and name the baseline.
- **Baseline = budget-matched self-consistency.** `fusion:3` ≈ 4× tokens, so it is
  compared against `selfconsist:4` (≈4×), the equal-budget honest baseline — *not*
  single-pass, which is a rigged comparison.
- **Significance, not vibes.** A few-point delta on a small dataset is usually noise;
  the claim only stands if the 95% CI excludes zero.

## Code track (HumanEval) — the least-circular signal

The first measured dataset is **HumanEval** (164 self-contained Python problems,
MIT). Each solution is graded by *executing* it against hidden unit tests —
pass/fail, no model judging itself, which is why it's the least circular signal
available.

Build it (needs `pip install datasets`; the output is gitignored):

```bash
python3 eval/quality/datasets/build_humaneval.py --out eval/quality/datasets/humaneval.jsonl
# or a seeded sample:  --n 40
```

Then run the sweep with `--dataset eval/quality/datasets/humaneval.jsonl`; the
`type:"code"` records grade by execution.

- **Self-consistency stays honest for code.** Source strings can't be
  majority-voted (every sample differs in whitespace), so `selfconsist:N` selects
  the first candidate that passes the **visible** docstring examples — never the
  hidden tests. Problems with no parseable examples fall back to first-sample (the
  builder reports how many).
- **⚠ Security.** Grading `type:"code"` **executes model-generated Python** in a
  timeout-guarded subprocess — isolated, but not a security sandbox. Run only
  datasets and outputs you trust. The committed
  `eval/quality/datasets/code_sample.jsonl` is a tiny self-authored fixture CI uses
  to smoke-test the grader safely.

## How this is generated (reproducible)

1. **Dataset** — a real, objective set at `eval/quality/datasets/<name>.jsonl`
   (GPQA-diamond, MMLU-Pro hard, MATH/AIME — dozens to hundreds of items). **Not**
   `sample.jsonl` (plumbing-only; easy items, no real signal).
2. **Run the sweep** in a trusted terminal (real budget; you authorise the headless
   panel's subagent spawns there). See [`eval/BASELINE.md`](eval/BASELINE.md) for the
   permission detail.

   ```bash
   python3 eval/quality/run_quality_eval.py \
     --dataset eval/quality/datasets/<name>.jsonl \
     --conditions single,selfconsist:3,selfconsist:4,fusion:3 \
     --repeats 5 --out eval/quality/baseline-<name>.jsonl --model opus
   ```

3. **Generate the claim** (code-generated, so it can't drift from the data):

   ```bash
   python3 eval/quality/metrics.py eval/quality/baseline-<name>.jsonl \
     --headline --label "dataset=<name> model=opus repeats=5 date=<YYYY-MM-DD> cli=<ver>"
   ```

4. **Commit** `eval/quality/baseline-<name>.jsonl` (the snapshot) and paste the
   generated `CLAIM` line and table into this file. The number is now reproducible:
   anyone can rerun step 3 against the committed snapshot and get the same line.
