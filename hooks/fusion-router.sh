#!/usr/bin/env bash
# model-fusion UserPromptSubmit router.
#
# Difficulty-gated, no-model-call heuristic. Reads the hook JSON on stdin and,
# depending on $FUSION_MODE, injects a reminder to use the `fusion` skill via the
# UserPromptSubmit additionalContext contract (exit 0 + JSON on stdout).
#
#   FUSION_MODE=off        -> no-op (never inject)
#   FUSION_MODE=always     -> always inject the reminder
#   FUSION_MODE=selective  -> inject only when the prompt scores "hard" (default)
#
# Any unset/unknown value is treated as the default, selective.

set -u

MODE="${FUSION_MODE:-selective}"

# off: do nothing, let the prompt through untouched.
if [ "$MODE" = "off" ]; then
  exit 0
fi

# Emit the additionalContext payload and exit. The text is static, so the JSON
# below needs no runtime escaping.
inject() {
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "[model-fusion] This prompt looks high-difficulty. Consider invoking the `fusion` skill (fan out to the persona panel and synthesise) or running /fuse, instead of answering single-pass. Skip fusion for simple, quick, or low-stakes prompts. Set FUSION_MODE=off to silence this."
  }
}
JSON
  exit 0
}

# always: inject unconditionally.
if [ "$MODE" = "always" ]; then
  inject
fi

# selective (and any unknown mode): score the prompt with a cheap heuristic.

# Pull the user's prompt text out of the stdin JSON. Prefer jq, fall back to
# python3, and degrade to a raw read if neither is present (over-trigger rather
# than miss).
RAW="$(cat)"
PROMPT=""
if command -v jq >/dev/null 2>&1; then
  PROMPT="$(printf '%s' "$RAW" | jq -r '.prompt // ""' 2>/dev/null)"
elif command -v python3 >/dev/null 2>&1; then
  PROMPT="$(printf '%s' "$RAW" | python3 -c 'import sys,json;
try:
    print(json.load(sys.stdin).get("prompt",""))
except Exception:
    pass' 2>/dev/null)"
else
  PROMPT="$RAW"
fi

# Lowercase copy for keyword matching.
LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"

HARD=0

# (a) Length over a threshold (~ a long, multi-part ask).
LEN="${#PROMPT}"
if [ "$LEN" -gt 320 ]; then
  HARD=1
fi

# (b) Multiple sub-questions.
QMARKS="$(printf '%s' "$PROMPT" | tr -cd '?' | wc -c | tr -d ' ')"
if [ "${QMARKS:-0}" -ge 2 ]; then
  HARD=1
fi

# (c) Analytical keywords.
case " $LOWER " in
  *analyse*|*analyze*|*compare*|*design*|*architect*|*trade-off*|*tradeoff*|*"trade off"*|*evaluate*|*"root cause"*|*prove*|*"why "*)
    HARD=1
    ;;
esac

if [ "$HARD" -eq 1 ]; then
  inject
fi

# Not hard: stay silent.
exit 0
