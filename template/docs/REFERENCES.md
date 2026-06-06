# References

## Source paper

**SkillOpt: Executive Strategy for Self-Evolving Agent Skills**

- Abstract / PDF: <https://arxiv.org/abs/2605.23904>
- HTML (v2): <https://arxiv.org/html/2605.23904v2>
- arXiv ID: `2605.23904`
- Title (canonical, verbatim from the arXiv abstract page): **"SkillOpt: Executive Strategy
  for Self-Evolving Agent Skills"**.
- Authors (full list from the arXiv page): Yifan Yang, Ziyang Gong, Weiquan Huang, Qihao
  Yang, Ziwei Zhou, Zisu Huang, Yan Li, Xuemei Gao, Qi Dai, Bei Liu, Kai Qiu, Yuqing Yang,
  Dongdong Chen, Xue Yang, Chong Luo.

> **Title note.** Some third-party write-ups cite this paper under a different title (e.g.
> *"Controllable Text-Space Optimization for Agent Skills"*). The canonical title on the
> arXiv abstract page is the one above; prefer it when citing.

### What the paper contributes

SkillOpt optimizes a compact natural-language **skill document** through a deep-learning-style
training loop (forward pass → backward pass → validation gate → epoch meta update) while the
target model stays **frozen**. Reported results: best-or-tied on all 52 (model, benchmark,
harness) combinations evaluated, with large average gains from only 1–4 accepted edits, and
skills that transfer across model scales and harnesses. It outperforms human-written skills,
one-shot LLM generation, and prior systems (Trace2Skill, TextGrad, GEPA, EvoSkill).

### BibTeX

> Author list and title verified against the arXiv abstract page. Affiliations are not shown
> on that page, so they are omitted here; confirm them in the PDF before formal citation.

```bibtex
@misc{skillopt2026,
  title         = {SkillOpt: Executive Strategy for Self-Evolving Agent Skills},
  author        = {Yang, Yifan and Gong, Ziyang and Huang, Weiquan and Yang, Qihao and
                   Zhou, Ziwei and Huang, Zisu and Li, Yan and Gao, Xuemei and Dai, Qi and
                   Liu, Bei and Qiu, Kai and Yang, Yuqing and Chen, Dongdong and Yang, Xue and
                   Luo, Chong},
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

## Related implementations

- **[mastercodeai/skillopt-methodology-skill](https://github.com/mastercodeai/skillopt-methodology-skill)**
  (MIT) — a prompt-only Claude *Skill* that faithfully extracts the paper's optimizer prompt
  stages (`analyst_error`, `analyst_success`, `merge_failure`, `merge_success`, `merge_final`,
  `ranking`, `slow_update`, `meta_skill`). It is a methodology reference, not an executable
  loop. Our staged backward pass (`run_optimizer()` in `scripts/evolve.py`, see
  [DESIGN.md](DESIGN.md)) follows the same paper-derived stage structure. *(Note: that repo's
  README cites the paper under a non-canonical title — see the title note above.)*

## This template

An independent adaptation of the SkillOpt method to Claude Code's `CLAUDE.md`, not affiliated
with or endorsed by the SkillOpt authors. Unlike a prompt-only methodology reference, this is
an **executable, automated** loop wired into Claude Code via a hook and distributed as an
`npx` scaffolder. See [DESIGN.md](DESIGN.md) for the mapping and the intentional divergences
(online/streaming setting, predictive validation gate).
