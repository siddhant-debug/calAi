#!/bin/bash
# Gate script — only triggers memory save if 30+ minutes have passed since last save.
# Prevents the Stop hook from spawning Claude after every single response.

LOCKFILE="/tmp/calai_memory_save.lock"
NOW=$(date +%s)
LAST=$(cat "$LOCKFILE" 2>/dev/null || echo 0)
DIFF=$((NOW - LAST))

# 1800 seconds = 30 minutes
if [ "$DIFF" -gt 1800 ]; then
  echo "$NOW" > "$LOCKFILE"
  cd /Users/siddhanttomar/Claude/Projects/calAi || exit 0
  # Only bother if there are uncommitted changes (something actually happened)
  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    claude --dangerously-skip-permissions -p "run /save-session-memory" > /tmp/calai_memory_save.log 2>&1 &
  fi
fi
