---
name: fusion
description: >-
  Self-fusion (Mixture-of-Agents) orchestration and synthesis. Use for hard,
  high-stakes, or ambiguous tasks where one pass is risky: fan the task out to a
  parallel panel of persona subagents on the same base model, then synthesise their
  drafts into one audited answer. Triggers include analysis, comparison, design,
  architecture, trade-off and root-cause work. Invoked explicitly via /fuse, or by
  the model when a prompt looks high-difficulty.
---

# Fusion: self-fusion (Mixture-of-Agents) over native subagents

You are the **orchestrator/synthesiser**. You fan one task out to a small panel of
persona subagents running in parallel on the same base model, then fuse their drafts
into a single answer. Diversity comes from **personas + sampling**, not from other
providers — this is *self*-fusion. Most of the quality lift lives in **synthesis**,
not in the panel; spend your effort on the rubric below, not on growing the panel.

## Procedure

### 1. Decide panel size
- Default **3** panellists. Allowed range **2–5**.
- Bigger panels cost more and add less each time (the 1→2 jump captures most of the
  lift). Only go above 3 for genuinely hard, multi-faceted tasks; prefer 2 for
  narrow ones.
- **Never exceed the harness's concurrent-subagent cap.** A panel of 2–5 stays well
  within it.
- **Subagents cannot recurse** — a panellist cannot spawn its own sub-panel. All
  fan-out happens here, in the main agent.

### 2. Spawn the panel in parallel
- Use the three persona subagents — `fusion-skeptic`, `fusion-builder`,
  `fusion-analyst` — as your default 3-panel. For panel size 2 drop `fusion-analyst`;
  for 4–5 spawn an extra instance of a persona (e.g. a second `fusion-skeptic` or
  `fusion-builder`) to add an independent draw.
- Give **every** panellist the **same, complete user task** verbatim, plus the
  instruction to do an independent, tool-augmented pass (web/bash enabled) and to
  return the panellist output contract below.
- **Spawn them in a single batch so they run concurrently** — issue all the subagent
  calls in one step, then wait for all of them. Do not run them one at a time.

### 3. Wait for all, then synthesise
Collect every panellist's draft, then run the synthesis rubric. Do not start
synthesising before all panellists have returned.

## Panellist output contract (each subagent returns exactly this)

```
## Answer
<their best answer>

## Key claims
| claim | evidence / source | confidence (0–1) |

## Where I might be wrong
<assumptions, edge cases, failure modes>
```

If a panellist returns something malformed, use what you can and note the gap in
Synthesis notes — do not discard the run silently.

## Synthesis rubric (you run this)

1. **Claim ledger.** Extract every *distinct* claim across all drafts. For each, tag
   which panellists asserted it and the evidence each gave. Work from this ledger,
   not from whichever draft reads best.
2. **Consensus ≠ correctness.** Agreement raises confidence, but check for
   **correlated error**: identical base models share failure modes, so three drafts
   agreeing can be three copies of one mistake. Agreement across *different personas*
   is stronger than agreement across identical draws — weight it accordingly.
3. **Contradictions — never average.** When drafts conflict, do not split the
   difference. Resolve by **evidence quality**: which draft cited the stronger /
   verifiable source, showed its working, made a falsifiable claim? If it is
   genuinely unresolvable, **surface the disagreement to the user** rather than
   silently picking one.
4. **Coverage union.** The fused answer takes the **union of each panellist's
   correct, unique contributions**, not just the intersection. This is where the
   diversity quarter of the lift is paid out — don't collapse to the lowest common
   denominator.
5. **Calibration.** Down-weight confident-but-unsupported assertions. A panellist
   *sounding* certain is not evidence; verifiable working is.
6. **Anti-majority guard.** Do **not** select an answer because most panellists gave
   it. Weight by evidence, not vote count. A lone well-evidenced draft beats a
   confident majority.

## Output contract (what you return to the user)

Return both parts:

1. **The single fused answer.**
2. A short **Synthesis notes** block, so the result is auditable:
   - contradictions found and how each was resolved (by what evidence);
   - any **unresolved** disagreements, surfaced explicitly for the user to decide;
   - any claim in the fused answer that rests on weak or unverifiable evidence.

```
## Synthesis notes
- Contradictions resolved: ...
- Unresolved disagreements: ...
- Weak-evidence claims carried: ...
```
