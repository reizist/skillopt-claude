# Canary replay gate (sample)

By default the validation gate in `scripts/evolve.py` is **predictive**: a judge model guesses
whether a candidate `CLAUDE.md` would help. The paper's gate is **empirical** — it re-executes
held-out tasks under each candidate and keeps the edit only if the measured score strictly
improves. This directory is a working sample of that empirical gate.

## How it works

```
evolve.py  ──SKILLOPT_SKILL_MD=<candidate CLAUDE.md>──▶  canary/run.sh  ──pass-rate float──▶  evolve.py
```

`run.sh` copies the skill under test into a scratch workspace as `CLAUDE.md`, runs each
`tasks/*.task` prompt through the real `claude` CLI there, checks the output against the
matching `tasks/*.expect` (an `grep -E` pattern), and prints a single pass-rate float on
stdout. `evolve.py` scores the current and the candidate skill this way and accepts only on a
strictly higher score (`replay_gate()`).

## Enable it

```bash
export SKILLOPT_REPLAY_CMD="bash canary/run.sh"   # replaces the judge gate
export SKILLOPT_REPLAY_TIMEOUT=1800               # optional, seconds (default 1800)
uv run scripts/evolve.py reflect
```

Requires the `claude` CLI on `PATH`. If it's missing, `run.sh` exits non-zero and the gate
reports "replay produced no score" and rejects (fail-safe — nothing is applied).

## Make it meaningful

The two shipped tasks (`json-only`, `exact-word`) only check instruction-following, so they
demonstrate the harness rather than your project's real behavior. Replace them:

- `tasks/<name>.task`   — the prompt to send to `claude -p`.
- `tasks/<name>.expect` — `grep -E -i` pattern(s) the output must contain to count as a pass.

Add tasks whose success actually depends on the rules your `CLAUDE.md` is learning (build
steps, output formats, project conventions). The more your canaries reflect real failure
modes, the more trustworthy the gate. Note the cost: every reflection runs all canaries twice
(current + candidate), so keep the set small and fast.
