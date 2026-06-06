# SkillOpt-Claude — a self-evolving `CLAUDE.md` boilerplate

A project template that treats `CLAUDE.md` as a **trainable artifact** and improves it from
your own session history — applying the training loop from
**SkillOpt: Executive Strategy for Self-Evolving Agent Skills**
([arXiv:2605.23904](https://arxiv.org/abs/2605.23904)).

The paper optimizes a natural-language *skill document* with a deep-learning-style loop
(forward pass → backward pass → validation gate → meta update) while keeping the model
frozen. Here the skill document is your `CLAUDE.md`, the rollouts are your finished Claude
Code sessions, and the optimizer is a Claude model invoked from a hook.

```
finished session ──▶ collect evidence ──▶ optimizer proposes bounded edits
                                                      │
   CLAUDE.md ◀── apply (gated) ◀── validation gate ◀──┘
```

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). `uv run` resolves the environment from
`pyproject.toml` automatically on first use — no manual venv needed.

```bash
uv sync                               # optional; uv run does this on demand
export ANTHROPIC_API_KEY=...          # used only by the optimizer/judge calls

# fill in the "Core" section of CLAUDE.md with your real project instructions, then:
uv run scripts/evolve.py status       # inspect state
uv run scripts/evolve.py reflect      # run one forward+backward+gate step
uv run scripts/evolve.py apply        # write the staged proposal into CLAUDE.md
```

The `Stop` hook in `.claude/settings.json` runs one reflection step automatically at the
end of every Claude Code session. In Claude Code, drive it with `/evolve`.

By default the loop is **propose-only** (edits are staged to `.claude/skillopt/proposal.md`,
applied on `apply`) and never touches your hand-authored Core section. Opt into autonomous
rewrites with `SKILLOPT_AUTOAPPLY=1`.

## Documentation

| Doc | For | Contents |
| --- | --- | --- |
| **[docs/DESIGN.md](docs/DESIGN.md)** | humans & AI | how the paper maps to this template, the algorithm, intentional divergences |
| **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)** | humans & AI | env vars, file layout, runtime state schema |
| **[AGENTS.md](AGENTS.md)** | **AI agents** | operating guide + invariants an agent must respect when running/extending this |
| **[docs/REFERENCES.md](docs/REFERENCES.md)** | everyone | paper citation (BibTeX), links, related work |

## File layout

```
CLAUDE.md                     skill doc with LEARNED_RULES + SLOW_UPDATE regions
pyproject.toml                uv-managed project + the anthropic dependency
scripts/evolve.py             the SkillOpt loop (reflect / apply / status)
.claude/settings.json         Stop hook → reflect after every session
.claude/commands/evolve.md    /evolve slash command
.claude/skillopt/             runtime state (scores, rejected buffer, meta, evidence)
canary/                       optional empirical-gate harness (SKILLOPT_REPLAY_CMD)
docs/                         design, configuration, references
AGENTS.md                     agent-facing operating guide
```

## References

- SkillOpt: Executive Strategy for Self-Evolving Agent Skills — [arXiv:2605.23904](https://arxiv.org/abs/2605.23904) ([HTML](https://arxiv.org/html/2605.23904v2)). Full citation and related work in [docs/REFERENCES.md](docs/REFERENCES.md).

> Independent adaptation of the published method; not affiliated with the SkillOpt authors.
