# model-fusion

[![eval](https://github.com/0xLeathery/fusion/actions/workflows/eval.yml/badge.svg)](https://github.com/0xLeathery/fusion/actions/workflows/eval.yml)

A Claude Code **plugin** that implements **self-fusion (Mixture-of-Agents)** using
native subagents, so it runs against your **subscription** instead of per-token API
billing.

On a hard task it fans your prompt out to a small panel of **persona subagents**
running in parallel — same base model, different lenses — and then **synthesises**
their drafts into one audited answer. Because every panellist runs on your Claude
Code session, the cost is paid in **usage-limit headroom, not dollars**.

## Why self-fusion (single provider)

Published Mixture-of-Agents results and OpenRouter's own Fusion data put roughly
**three quarters of the lift in *synthesis*** and about **one quarter in
*diversity***. Single-provider self-fusion deliberately keeps the same base model and
gets its diversity from **distinct personas + sampling** rather than from other
providers — so it captures most of the benefit while staying on one subscription.

The price is throughput: an **N-panel plus synthesis burns roughly (N+1)× tokens per
query**, so you reach your weekly subscription ceiling about that much faster. That
trade — and the fact that a throttled session produces *zero* output, not lower
quality — is exactly why the router defaults to **selective**.

## How it works

1. A `UserPromptSubmit` **router hook** (or the `/fuse` command) decides a prompt is
   worth fusing.
2. The **`fusion` skill** spawns the persona panel **in parallel**, each on the same
   task, each doing an independent tool-augmented pass.
3. The skill **synthesises** the drafts with a rubric (claim ledger, correlated-error
   check, evidence-based contradiction resolution, coverage union, calibration,
   anti-majority guard) and returns one fused answer **plus** an auditable
   `Synthesis notes` block.

## Components

| Path | What it is |
|------|------------|
| `.claude-plugin/plugin.json` | Plugin manifest (`model-fusion` v0.1.0). |
| `skills/fusion/SKILL.md` | Core: orchestration + synthesis rubric. |
| `agents/fusion-skeptic.md` | Persona — assumes the obvious answer is wrong; hunts counterexamples. |
| `agents/fusion-builder.md` | Persona — most complete, concrete, actionable answer. |
| `agents/fusion-analyst.md` | Persona — depth on the single most load-bearing aspect. |
| `hooks/hooks.json` + `hooks/fusion-router.sh` | Difficulty-gated `UserPromptSubmit` router. |
| `commands/fuse.md` | `/fuse` — explicit entry point that overrides the hook. |
| `settings.json` | Recommended config (sets `FUSION_MODE`). |

## Install

```bash
# From the directory containing this plugin folder:
claude plugin validate ./model-fusion      # optional: confirm it's well-formed
claude plugin install ./model-fusion        # install from a local path
```

(If you keep the plugin under another folder name, point the commands at that path.)

Once installed, the `fusion` skill, the `/fuse` command, the three persona agents,
and the router hook are all available in your sessions.

## Usage

- **Explicit:** `/fuse <hard task>` always runs the panel and synthesis, regardless
  of `FUSION_MODE`.
- **Automatic:** with the router on, a high-difficulty prompt gets a nudge to invoke
  the `fusion` skill.

### Modes — the `FUSION_MODE` toggle

The router reads the `FUSION_MODE` environment variable:

| `FUSION_MODE` | Behaviour |
|---------------|-----------|
| `off` | No-op. The router never injects anything. |
| `always` | Injects a reminder to fuse on **every** prompt. |
| `selective` | **(default)** Runs a cheap, no-model-call heuristic and injects only when the prompt scores "hard". |

The heuristic (in `hooks/fusion-router.sh`) flags a prompt as hard when **any** of:
prompt length over ~320 chars, two or more question marks, or an analytical keyword
(`analyse`/`analyze`, `compare`, `design`, `architecture`, `trade-off`, `evaluate`,
`root cause`, `prove`, `why`). It makes **no model call**.

**Default:** `selective` is enforced in the router script itself, so fusion stays
off the cheap stuff even with no configuration. To change it, set the env var:

```bash
export FUSION_MODE=off        # silence the router
export FUSION_MODE=always     # nudge on everything
```

…or copy the bundled `settings.json` `env` block into your own
`.claude/settings.json`. `/fuse` ignores `FUSION_MODE` entirely — it always fuses.

## Tuning the cost / quality trade-off

- **Panel size.** Default **3**, range **2–5**. The **1→2-draft jump captures most of
  the synthesis lift**; a wide panel on every task is mostly waste. Use 2 for narrow
  asks, reserve 4–5 for genuinely multi-faceted ones.
- **Budget lever — model.** The personas default to **Opus**. Swap them to **Sonnet**
  (edit `model: opus` → `model: sonnet` in the three files under `agents/`) to cut
  burn substantially at some quality cost.
- **Mode.** Keep `selective` (or `off`) for routine work; `always` will chew through
  your weekly ceiling fast.

## Benchmarking

Don't take the quality claim on faith — `eval/` benchmarks it. The key idea: the
honest baseline isn't single-pass, it's **equal-budget self-consistency** (spend the
same (N+1)× tokens drawing more samples of the same model and voting). Fusion has to
beat *that* to justify itself.

- `eval/router/` — scores the routing heuristic (precision/recall/F1) against a
  labelled prompt set. Deterministic, no API, runnable now:
  `python3 eval/router/run_router_eval.py`
- `eval/quality/` — drives headless runs across `single` / `selfconsist:N` /
  `fusion:N`, grades objectively, and reports accuracy CIs, McNemar significance, and
  token ratios. Start with `--dry-run` to exercise the pipeline without spending
  budget.

See `eval/README.md` for the full methodology, ablations, and caveats.

### Published baseline

The baseline is published in two tiers — see **`eval/BASELINE.md`**:

- **Router (deterministic, gated).** Frozen numbers (currently **F1 0.914**, n=36) with
  a CI gate (`--min-f1 0.90`) that fails the build on a routing regression. This is the
  green check above.
- **Quality (committed snapshot).** Real model calls are too costly/noisy for CI and the
  fusion panel needs a permission-bypassed headless agent, so the quality claim is
  published as a human-generated snapshot on a real objective dataset (not the
  plumbing-only `sample.jsonl`), with the McNemar / CI / token-ratio summary committed
  alongside it.

## Limits

- **Token burn.** ≈ (N+1)× tokens per fused query. Plan around your weekly
  subscription ceiling.
- **Concurrency cap.** Claude Code limits how many subagents run in parallel; panel
  sizes of 2–5 stay within it.
- **No recursion.** Subagents cannot spawn their own subagents, so all fan-out
  happens in the main agent — panellists run their pass and return.
