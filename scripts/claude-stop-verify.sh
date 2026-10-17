#!/usr/bin/env bash
# Claude Code Stop hook (configured in .claude/settings.json).
#
# Before Claude finishes a turn, run full verification if the working tree has
# changed since the last run. On failure, exit 2: Claude Code then blocks the
# stop and shows Claude the failure output.
#
# Loop guard: if Claude is already continuing because of this hook
# (stop_hook_active) and has changed nothing since the failed run, allow the
# stop. Claude can then report the failure, but cannot end a turn with a
# failing tree it has modified without verification running again.
#
# Markdown-only changes (planning documents) do not trigger verification.
set -uo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

input="$(cat)"
stop_hook_active=false
if printf '%s' "$input" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  stop_hook_active=true
fi

state_dir="$(git rev-parse --git-path claude-verify)"
mkdir -p "$state_dir"

# Hash the working tree (tracked and untracked, honouring .gitignore), minus
# Markdown files, without touching the real index.
tree_hash() {
  local index
  index="$(mktemp)"
  cp "$(git rev-parse --git-path index)" "$index" 2>/dev/null || true
  GIT_INDEX_FILE="$index" git add -A >/dev/null 2>&1
  GIT_INDEX_FILE="$index" git rm -r -q --cached --ignore-unmatch -- '*.md' >/dev/null 2>&1
  GIT_INDEX_FILE="$index" git write-tree
  rm -f "$index"
}

current="$(tree_hash)"

if [ "$current" = "$(cat "$state_dir/last-pass" 2>/dev/null)" ]; then
  exit 0
fi

if $stop_hook_active && [ "$current" = "$(cat "$state_dir/last-fail" 2>/dev/null)" ]; then
  exit 0
fi

log="$state_dir/verify.log"
if scripts/verify.sh >"$log" 2>&1; then
  printf '%s\n' "$current" >"$state_dir/last-pass"
  exit 0
fi

printf '%s\n' "$current" >"$state_dir/last-fail"
{
  echo "scripts/verify.sh failed; the task is not complete. Last 60 lines:"
  tail -n 60 "$log"
  echo "Full log: $log"
} >&2
exit 2
