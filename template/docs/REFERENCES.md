# References

## Source paper

**SkillOpt: Executive Strategy for Self-Evolving Agent Skills**

- Abstract / PDF: <https://arxiv.org/abs/2605.23904>
- HTML (v2): <https://arxiv.org/html/2605.23904v2>
- arXiv ID: `2605.23904`
- Authors: Yifan Yang, Ziyang Gong, Weiquan Huang, et al. (Microsoft; Shanghai Jiao Tong
  University; and collaborators). *Author list here is partial — see the arXiv page for the
  complete, authoritative list.*

### What the paper contributes

SkillOpt optimizes a compact natural-language **skill document** through a deep-learning-style
training loop (forward pass → backward pass → validation gate → epoch meta update) while the
target model stays **frozen**. Reported results: best-or-tied on all 52 (model, benchmark,
harness) combinations evaluated, with large average gains from only 1–4 accepted edits, and
skills that transfer across model scales and harnesses. It outperforms human-written skills,
one-shot LLM generation, and prior systems (Trace2Skill, TextGrad, GEPA, EvoSkill).

### BibTeX

> Approximate; verify against the arXiv page before citing in published work.

```bibtex
@misc{skillopt2026,
  title         = {SkillOpt: Executive Strategy for Self-Evolving Agent Skills},
  author        = {Yang, Yifan and Gong, Ziyang and Huang, Weiquan and others},
  year          = {2026},
  eprint        = {2605.23904},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url           = {https://arxiv.org/abs/2605.23904}
}
```

## Related work cited by the paper

Prior skill/prompt-optimization systems SkillOpt compares against — useful background if you
extend this template:

- **Trace2Skill** — deriving reusable skills from execution traces.
- **TextGrad** — "textual gradients": natural-language feedback as the optimization signal.
- **GEPA** — reflective prompt evolution.
- **EvoSkill** — evolutionary skill optimization.

(Look these up on arXiv for the authoritative references.)

## This template

An independent adaptation of the SkillOpt method to Claude Code's `CLAUDE.md`, not affiliated
with or endorsed by the SkillOpt authors. See [DESIGN.md](DESIGN.md) for the mapping and the
intentional divergences (online/streaming setting, predictive validation gate).
