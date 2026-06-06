# Configuration

## Requirements

- [uv](https://docs.astral.sh/uv/) — manages the Python environment from `pyproject.toml`.
  `uv run scripts/evolve.py ...` resolves and installs deps on first use; `uv sync` does it
  ahead of time.
- `ANTHROPIC_API_KEY` in the environment — used only by the optimizer and judge model calls
  (`reflect`). `status`/`apply` and all evidence collection work without it.

## Environment variables

| Var | Default | Meaning |
| --- | --- | --- |
| `SKILLOPT_OPTIMIZER_MODEL` | `claude-sonnet-4-6` | model used for both the optimizer (propose/meta) and the judge (gate) |
| `SKILLOPT_LR_BUDGET` | `3` | learning-rate budget `L_t`: max edits accepted per reflection |
| `SKILLOPT_WINDOW` | `6` | reflection minibatch size, in sessions |
| `SKILLOPT_EPOCH_SIZE` | `8` | decisions per epoch; triggers the meta update + rejected-buffer reset |
| `SKILLOPT_AUTOAPPLY` | unset | `1` = write `CLAUDE.md` directly instead of staging to `proposal.md` |
| `SKILLOPT_SCORE_CMD` | unset | shell command printing a float — replaces the heuristic **rollout** score (forward pass) |
| `SKILLOPT_REPLAY_CMD` | unset | shell command printing a float — switches the **gate** from the predictive judge to an empirical canary replay (see [canary/](../canary/README.md)) |
| `SKILLOPT_REPLAY_TIMEOUT` | `1800` | per-invocation timeout (seconds) for `SKILLOPT_REPLAY_CMD` |
| `SKILLOPT_ROOT` | cwd | project root containing `CLAUDE.md` (set if the hook runs elsewhere) |

> `SKILLOPT_SCORE_CMD` and `SKILLOPT_REPLAY_CMD` are different knobs: the former scores a
> *past session* (forward pass), the latter scores a *candidate skill* by re-execution (the
> validation gate). The replay command receives the candidate `CLAUDE.md` path as
> `$SKILLOPT_SKILL_MD`.

## File layout

```
CLAUDE.md                     skill doc; only LEARNED_RULES + SLOW_UPDATE regions are managed
pyproject.toml                uv project + anthropic dependency
scripts/evolve.py             the loop: reflect / apply / status
.claude/settings.json         Stop hook → `uv run scripts/evolve.py reflect`
.claude/commands/evolve.md    /evolve slash command
.claude/skillopt/             runtime state (below)
canary/                       sample empirical-gate harness (opt-in via SKILLOPT_REPLAY_CMD)
docs/                         DESIGN, CONFIGURATION, REFERENCES
AGENTS.md                     agent operating guide
```

## Runtime state (`.claude/skillopt/`)

All generated at runtime. Safe to delete to reset learning (you lose history, not `CLAUDE.md`).

| File | Paper analog | Contents |
| --- | --- | --- |
| `evidence.jsonl` | rollouts | one line per reflected session: turns, corrections, tool errors, score, outcome, friction excerpts |
| `rejected.jsonl` | rejected-edit buffer `B` | edits the gate rejected, with reasons; fed back to the optimizer; reset each epoch |
| `scores.json` | score cache `C` | `hash(CLAUDE.md) → predicted delta` for accepted candidates |
| `meta.md` | meta skill (teacher) | distilled cross-epoch lessons, prepended to optimizer prompts; never deployed verbatim |
| `proposal.md` | — | last gated candidate `CLAUDE.md`, awaiting `apply` (propose-only mode) |
| `history.jsonl` | — | full decision log: edits + gate verdict per reflection |

## `CLAUDE.md` regions

```
## Core (human-authored — never auto-edited)
   ...your real project instructions...

<!-- LEARNED_RULES_START -->   ← fast per-reflection edits land here
<!-- LEARNED_RULES_END -->

<!-- SLOW_UPDATE_START -->      ← protected; only the epoch meta update writes here
<!-- SLOW_UPDATE_END -->
```

Markers are required — `set_region()` raises if either pair is missing. Keep the Core
section above the markers; it is never auto-edited.

## Common configurations

- **Fully autonomous:** `SKILLOPT_AUTOAPPLY=1` — edits apply on every gated acceptance.
- **Stronger optimizer:** `SKILLOPT_OPTIMIZER_MODEL=claude-opus-4-8`.
- **Real replay gate:** `SKILLOPT_REPLAY_CMD="bash canary/run.sh"` — swaps the predictive
  judge for the empirical canary harness in [canary/](../canary/README.md). See
  [DESIGN.md](DESIGN.md) on the predictive-vs-replay gate.
- **Faster/slower adaptation:** raise `SKILLOPT_LR_BUDGET` and shrink `SKILLOPT_EPOCH_SIZE`
  to adapt aggressively; lower them for conservative, slow evolution.
