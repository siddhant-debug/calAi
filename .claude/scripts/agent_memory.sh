#!/bin/bash
# SubagentStop hook — appends a record of every subagent's finished work to
# artefacts/agent-memory.md, so each task leaves a durable trace without the agent
# having to remember to write one.
#
# Deliberately does NOT spawn another Claude (unlike memory_save_gate.sh): it only
# reads the subagent's own transcript, so it costs nothing and cannot loop.
# Always exits 0 — a logging hook must never block or fail an agent's work.

set -uo pipefail

REPO="/Users/siddhanttomar/Claude/Projects/calAi"
OUT="$REPO/artefacts/agent-memory.md"
RAW="$REPO/.claude/scripts/.agent_memory_payload.log"
MAX_BODY_LINES=120

payload=$(cat 2>/dev/null || true)
mkdir -p "$(dirname "$OUT")" 2>/dev/null || true

# Keep the last few raw payloads so the hook's own input schema can be verified/refined.
{ printf -- '--- %s\n%s\n' "$(date -u +%FT%TZ)" "$payload"; } >> "$RAW" 2>/dev/null || true
if [ -f "$RAW" ]; then
  tail -n 300 "$RAW" > "$RAW.tmp" 2>/dev/null && mv "$RAW.tmp" "$RAW" 2>/dev/null || true
fi

jqr() { printf '%s' "$payload" | jq -r "$1" 2>/dev/null || true; }

session=$(jqr '.session_id // empty')
agent=$(jqr '.agent_type // .subagent_type // .agent // empty')
[ -n "$agent" ] || agent="subagent"

# The subagent's final report. `last_assistant_message` is exactly that, so prefer it.
# NOTE: `transcript_path` is the PARENT session's transcript — using it captures the main
# thread's last message instead of the subagent's. The subagent's own transcript is
# `agent_transcript_path`; it's the fallback here only if last_assistant_message is absent.
last=$(jqr '.last_assistant_message // empty')

if [ -z "${last//[[:space:]]/}" ]; then
  transcript=$(jqr '.agent_transcript_path // empty')
  if [ -n "$transcript" ] && [ -f "$transcript" ]; then
    last=$(jq -rs '
      [ .[]
        | select(.type == "assistant")
        | (.message.content // empty)
        | if type == "array"
          then (map(select(.type == "text") | .text) | join("\n"))
          else (. | tostring)
          end
      ]
      | map(select(. != null and (. | length) > 0))
      | (last // "")
    ' "$transcript" 2>/dev/null || true)
  fi
fi

# Prefer the structured YAML report block the agent files mandate; fall back to prose.
yaml=$(printf '%s' "$last" | awk '/^[[:space:]]*```yaml/{f=1;next} /^[[:space:]]*```/{if(f) exit} f' 2>/dev/null || true)

# Only CalAI's pipeline agents are required to emit a YAML report block; a missing block
# from one of those is a real DoD miss worth flagging, from Explore/general-purpose it isn't.
case "$agent" in
  backend-engineer|ai-engineer|flutter-engineer|ui-engineer|tester) yaml_required=1 ;;
  *) yaml_required=0 ;;
esac

body=""
if [ -n "${yaml//[[:space:]]/}" ]; then
  body=$(printf '%s' "$yaml" | head -n "$MAX_BODY_LINES")
  kind="structured report"
elif [ -n "${last//[[:space:]]/}" ]; then
  body=$(printf '%s' "$last" | head -n "$MAX_BODY_LINES")
  if [ "$yaml_required" -eq 1 ]; then
    kind="prose only — **DoD miss: this agent must emit a yaml report block**"
  else
    kind="prose (no yaml block expected from this agent type)"
  fi
else
  body="(no report text could be read)"
  kind="unreadable"
fi

branch=$(cd "$REPO" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
dirty=$(cd "$REPO" && git status --porcelain 2>/dev/null | head -25 || true)
[ -n "${dirty//[[:space:]]/}" ] || dirty="(working tree clean)"

{
  printf '\n---\n\n## %s — %s\n\n' "$(date -u '+%Y-%m-%d %H:%M:%SZ')" "$agent"
  printf -- '- session: `%s`\n' "${session:-unknown}"
  printf -- '- branch: `%s`\n' "$branch"
  printf -- '- report: %s\n\n' "$kind"
  printf '### Report\n\n```\n%s\n```\n\n' "$body"
  printf '### Working tree at completion\n\n```\n%s\n```\n' "$dirty"
} >> "$OUT" 2>/dev/null || true

exit 0
