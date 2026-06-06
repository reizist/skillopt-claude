---
description: Run / inspect / apply the SkillOpt self-evolving CLAUDE.md loop
---

Run the SkillOpt loop against recent session evidence.

Usage:
- `/evolve` or `/evolve reflect` — collect evidence, propose bounded edits, run the
  validation gate, and (in propose mode) write the patch to `.claude/skillopt/proposal.md`.
- `/evolve apply` — apply the last gated proposal to `CLAUDE.md`.
- `/evolve status` — show current score, accepted/rejected history, and meta skill.

These run `uv run scripts/evolve.py` — uv resolves the environment on first use.

Execute the appropriate command and summarize the proposed diff for me before applying:

```
uv run scripts/evolve.py $ARGUMENTS
```
