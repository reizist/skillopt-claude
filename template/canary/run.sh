#!/usr/bin/env bash
# Canary replay scorer for SkillOpt's empirical validation gate.
#
# evolve.py calls this once per candidate CLAUDE.md, passing the file to test as
# $SKILLOPT_SKILL_MD. We run each canary task through the real Claude Code CLI with that
# skill in place, check the output against the task's expectation, and print a single
# pass-rate float (0.0–1.0) on stdout. Everything else goes to stderr.
#
# Wire it up:   export SKILLOPT_REPLAY_CMD="bash canary/run.sh"
#
# This is a SAMPLE. Replace tasks/*.task and tasks/*.expect with canaries that actually
# exercise your project's rules, and adapt the invocation to your harness.
set -euo pipefail

SKILL="${SKILLOPT_SKILL_MD:?set SKILLOPT_SKILL_MD to the CLAUDE.md under test}"
DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v claude >/dev/null 2>&1; then
  echo "canary: 'claude' CLI not found on PATH — cannot run the replay gate" >&2
  exit 2
fi

# Scratch workspace whose CLAUDE.md is the candidate skill under test.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp "$SKILL" "$work/CLAUDE.md"

pass=0
total=0
for task in "$DIR"/tasks/*.task; do
  [ -e "$task" ] || continue
  name="$(basename "$task" .task)"
  expect="$DIR/tasks/$name.expect"
  total=$((total + 1))

  # Headless, non-interactive run with the candidate skill as the project's CLAUDE.md.
  out="$(cd "$work" && claude -p "$(cat "$task")" 2>/dev/null || true)"

  if [ -f "$expect" ] && grep -qiE -f "$expect" <<<"$out"; then
    pass=$((pass + 1))
    echo "canary PASS  $name" >&2
  else
    echo "canary FAIL  $name" >&2
  fi
done

# Single float on stdout: the pass rate that evolve.py compares across candidates.
awk -v p="$pass" -v t="$total" 'BEGIN { if (t == 0) print "0"; else printf "%.4f\n", p / t }'
