---
name: fuse
description: Run model-fusion on a task — fan out to a parallel persona panel and synthesise one audited answer. Overrides FUSION_MODE.
argument-hint: "[hard task to fuse]"
---

Run the **model-fusion** protocol on the following task, regardless of the current
`FUSION_MODE` setting:

> $ARGUMENTS

Follow the orchestration and synthesis rubric in
`${CLAUDE_PLUGIN_ROOT}/skills/fusion/SKILL.md` (invoke the `fusion` skill). Concretely:

1. Pick a panel size (default 3; 2–5 allowed) appropriate to the task.
2. Spawn the persona subagents (`fusion-skeptic`, `fusion-builder`, `fusion-analyst`)
   **in parallel, in a single batch**, each on the task above, each returning the
   panellist output contract.
3. Wait for all panellists, then apply the synthesis rubric.
4. Return the single fused answer **plus** the `## Synthesis notes` block.

If `$ARGUMENTS` is empty, ask the user what task to fuse before spawning anything.
