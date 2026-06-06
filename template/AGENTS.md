# AGENTS.md — operating guide for AI agents

This file tells an AI coding agent (Claude Code or similar) how to **operate and extend**
the self-evolving `CLAUDE.md` system in this repo. It is normative: follow the invariants.

For the underlying theory see [docs/DESIGN.md](docs/DESIGN.md); for knobs and state see
[docs/CONFIGURATION.md](docs/CONFIGURATION.md); for the source paper see
[docs/REFERENCES.md](docs/REFERENCES.md).

## What this system is

`CLAUDE.md` is a **trainable artifact**, not just static instructions. A loop in
`scripts/evolve.py` reads finished-session evidence, proposes bounded edits to two marked
regions of `CLAUDE.md`, gates them on predicted improvement, and (when applied) grows the
file's learned rules over time. This implements the SkillOpt training loop
([arXiv:2605.23904](https://arxiv.org/abs/2605.23904)) in an online setting.

## How to run it

All entry points go through `uv` (resolves the env from `pyproject.toml`):

| Intent | Command |
| --- | --- |
| Inspect state / history / meta skill | `uv run scripts/evolve.py status` |
| One reflection step (evidence → propose → gate → stage) | `uv run scripts/evolve.py reflect` |
| Apply the staged proposal to `CLAUDE.md` | `uv run scripts/evolve.py apply` |

`reflect` also runs automatically via the `Stop` hook in `.claude/settings.json` after
every session. The `/evolve` slash command wraps these.

## Invariants — never violate these

1. **Never hand-edit `CLAUDE.md`'s managed regions.** The `LEARNED_RULES` and
   `SLOW_UPDATE` blocks (between their `<!-- ... -->` markers) are owned by the loop.
   Edit only the **Core (human-authored)** section, and never delete the markers — the
   loop raises if a marker is missing.
2. **Respect region ownership in code.** `LEARNED_RULES` is for fast per-reflection edits;
   `SLOW_UPDATE` is protected and written only by the epoch meta update. Do not let
   step-level edits write into `SLOW_UPDATE`.
3. **Keep the gate strict.** A candidate is accepted only on a strictly positive predicted
   delta (`> 0`); ties and uncertainty reject. Loosening this reintroduces silent drift —
   the failure mode the paper's validation gate exists to prevent.
4. **Bounded edits only.** Honor the learning-rate budget (`SKILLOPT_LR_BUDGET`, default 3)
   and `merge_and_rank()`'s dedup/clip. Do not bulk-rewrite the rules.
5. **The hook must never block a session.** `evolve.py` catches all errors and exits 0.
   Preserve that — any new code path must stay non-fatal.
6. **Propose-only is the default.** Do not enable `SKILLOPT_AUTOAPPLY=1` on a user's behalf
   without explicit instruction; staging to `proposal.md` keeps a human in the loop.
7. **Don't fabricate scores.** If you add a real scorer, wire it through
   `SKILLOPT_SCORE_CMD` (must print a float); otherwise leave the heuristic.

## Where to make common changes

| Task | Edit |
| --- | --- |
| Add detected failure signals (e.g. new languages) | `CORRECTION` regex in `scripts/evolve.py` |
| Change how rollout score is computed | `heuristic_score()` or set `SKILLOPT_SCORE_CMD` |
| Change the optimizer/judge prompts | staged `ANALYST_*_SYS` / `MERGE_*_SYS` / `RANKING_SYS` / `GATE_SYS` / `META_SYS` |
| Change the optimizer stage wiring | `run_optimizer()` (analyst → merge → final → ranking) |
| Change edit budget / window / epoch size | env vars in [docs/CONFIGURATION.md](docs/CONFIGURATION.md) |
| Use the empirical (replay) gate | add canary tasks under `canary/tasks/`, set `SKILLOPT_REPLAY_CMD="bash canary/run.sh"` |
| Change what counts as evidence | `collect_evidence()` (reads the transcript JSONL) |

## After changing `scripts/evolve.py`

Run the no-network smoke checks before claiming it works (these exercise everything except
the optimizer/judge API calls):

```bash
uv run python -m py_compile scripts/evolve.py
uv run scripts/evolve.py status
```

To exercise evidence collection, craft a small transcript JSONL and call
`collect_evidence()` directly (see the smoke test pattern in the project history). Do not
claim the API path works without a real `ANTHROPIC_API_KEY` run.

## Glossary (paper term → here)

forward pass = one session's evidence · backward pass = optimizer proposing edits ·
validation gate = `gate()` · rejected-edit buffer = `.claude/skillopt/rejected.jsonl` ·
meta skill = `.claude/skillopt/meta.md` + `SLOW_UPDATE` block · score cache =
`.claude/skillopt/scores.json`. Full table in [docs/DESIGN.md](docs/DESIGN.md).
