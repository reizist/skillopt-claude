# skillopt-claude

Scaffold a **self-evolving `CLAUDE.md`** into any project with one command. The scaffolded
files implement the training loop from **SkillOpt: Executive Strategy for Self-Evolving Agent
Skills** ([arXiv:2605.23904](https://arxiv.org/abs/2605.23904)): your `CLAUDE.md` becomes a
trainable artifact that improves from your own Claude Code session history.

## Use it in a project

```bash
# in the project you want to add it to:
npx skillopt-claude            # scaffold into the current directory
npx skillopt-claude ./my-app   # ...or into a target directory
npx skillopt-claude --force    # overwrite existing files
```

Existing files are skipped (not clobbered) unless you pass `--force`. After scaffolding:

```bash
uv sync
export ANTHROPIC_API_KEY=...
uv run scripts/evolve.py status
```

Then edit the **Core** section of the generated `CLAUDE.md` with your real instructions. The
`Stop` hook in `.claude/settings.json` evolves the file after every session.

## Running before it's published to npm

`npx` can run this package straight from a path or git, no publish required:

```bash
npx /Users/reizist/go/src/github.com/reizist/skillopt-claude   ./target   # from local path
# or, once pushed to GitHub:
npx github:reizist/skillopt-claude   ./target
```

Or link it globally for repeated use:

```bash
cd skillopt-claude && npm link        # exposes the `skillopt-claude` command
skillopt-claude ./some-project
```

To publish later: `npm publish` (then `npx skillopt-claude` works anywhere).

## What gets scaffolded

```
CLAUDE.md                     skill doc with LEARNED_RULES + SLOW_UPDATE regions
pyproject.toml                uv-managed project + the anthropic dependency
scripts/evolve.py             the SkillOpt loop (reflect / apply / status)
.claude/settings.json         Stop hook → reflect after every session
.claude/commands/evolve.md    /evolve slash command
.claude/skillopt/             runtime state dir
canary/                       optional empirical-gate harness (SKILLOPT_REPLAY_CMD)
docs/                         DESIGN, CONFIGURATION, REFERENCES
AGENTS.md                     agent-facing operating guide
README.md                     the scaffolded project's own README
.gitignore                    (shipped as `gitignore`, restored on scaffold)
```

See **[template/docs/DESIGN.md](template/docs/DESIGN.md)** for how the paper maps onto the
template, and **[template/AGENTS.md](template/AGENTS.md)** for the agent operating guide.

## How this package is laid out

```
bin/cli.mjs     the npx entry point (zero runtime deps; Node ≥16)
template/       the payload copied into a target project
package.json    bin + files manifest
```

## References

SkillOpt: Executive Strategy for Self-Evolving Agent Skills —
[arXiv:2605.23904](https://arxiv.org/abs/2605.23904)
([HTML](https://arxiv.org/html/2605.23904v2)). Full citation in
[template/docs/REFERENCES.md](template/docs/REFERENCES.md).

> Independent adaptation of the published method; not affiliated with the SkillOpt authors.
