# Design — how SkillOpt maps onto a self-evolving `CLAUDE.md`

This document explains the method and how `scripts/evolve.py` implements it. It is written
to be read by both humans and AI agents. Source paper:
**SkillOpt: Executive Strategy for Self-Evolving Agent Skills**,
[arXiv:2605.23904](https://arxiv.org/abs/2605.23904) — see [REFERENCES.md](REFERENCES.md).

## The idea in one paragraph

SkillOpt keeps the model frozen and instead *trains a natural-language skill document* with
a loop borrowed from deep learning: run the task (forward pass), reflect on what failed and
succeeded to propose edits (backward pass), accept an edit only if held-out performance
strictly improves (validation gate), and periodically distill durable lessons into a
protected region (meta update). The result is a small artifact (hundreds to ~2k tokens)
assembled from only a handful of accepted edits. We make that artifact your `CLAUDE.md`.

## Mapping table

| Paper | This template | Code |
| --- | --- | --- |
| skill document `s` | `LEARNED_RULES` region of `CLAUDE.md` | `region()` / `set_region()` |
| protected slow-update field | `SLOW_UPDATE` region of `CLAUDE.md` | `maybe_meta_update()` |
| forward pass (rollouts) | one finished session → transcript evidence | `collect_evidence()` |
| rollout score `r(s)` | corrections + tool errors per turn (or external cmd) | `heuristic_score()` |
| backward pass (reflection) | optimizer proposes `add/replace/delete` edits | `propose_edits()` |
| failure/success minibatches | window split by `outcome` | `propose_edits()` |
| edit merge + LR budget `L_t` | dedup, failure-first rank, clip | `merge_and_rank()` |
| bounded text update | localized add/replace/delete in the region | `apply_edits()` |
| validation gate (strict `>`) | judge predicts a strictly positive delta | `gate()` |
| rejected-edit buffer `B` | `rejected.jsonl`, reset each epoch | `cmd_reflect()` |
| score cache `C` | `scores.json` keyed by `CLAUDE.md` hash | `cmd_reflect()` |
| epoch-wise meta skill | `meta.md` (teacher) + `SLOW_UPDATE` block | `maybe_meta_update()` |
| `D_test` generalization | your *next* sessions | n/a (online) |

## The loop, step by step (`cmd_reflect`)

1. **Forward pass.** Read the session `transcript_path` (provided on stdin by the `Stop`
   hook). `collect_evidence()` extracts user turns, counts correction signals (EN+JA regex
   `CORRECTION`) and `is_error` tool results, computes a `score`, and labels the session
   `success`/`fail`. The evidence unit is appended to `evidence.jsonl`.
2. **Minibatch.** Take the last `SKILLOPT_WINDOW` evidence units and split into failure and
   success minibatches — the paper analyzes the two separately.
3. **Backward pass.** `propose_edits()` sends the current rules, the meta-skill guidance,
   both minibatches, and the recent rejected buffer to the optimizer model, which returns a
   JSON array of bounded edits (each generalizable, not task-specific, not a duplicate of a
   rejected edit).
4. **Merge + clip.** `merge_and_rank()` dedups, ranks failure-corrections (replace/delete)
   above pure additions, and clips to `SKILLOPT_LR_BUDGET` (`L_t`).
5. **Apply to a candidate.** `apply_edits()` produces candidate rules; `set_region()` splices
   them into a candidate `CLAUDE.md` (Core section and `SLOW_UPDATE` untouched).
6. **Validation gate.** `gate()` asks a judge model whether the candidate would strictly
   reduce friction without harming successes. Accept only if `predicted_delta > 0`.
7. **Bookkeeping.**
   - *Rejected* → append the edits to `rejected.jsonl` (buffer `B`) with the reason; nothing
     is written to `CLAUDE.md`.
   - *Accepted* → cache the score in `scores.json`, stage the candidate to `proposal.md`;
     write `CLAUDE.md` immediately only if `SKILLOPT_AUTOAPPLY=1`, else wait for `apply`.
8. **Meta update.** Every `SKILLOPT_EPOCH_SIZE` decisions, `maybe_meta_update()` distills
   durable lessons into `meta.md` (teacher-only) and the protected `SLOW_UPDATE` block, then
   resets the rejected buffer.

## Intentional divergences from the paper

The paper trains over a fixed dataset with a held-out selection set and re-scores every
candidate by re-execution. Claude Code provides a **stream** of sessions and no cheap way to
replay one under a candidate `CLAUDE.md`. Hence:

- **Online / streaming, not batch-epoch.** One session = one rollout; a sliding window is
  the minibatch; an "epoch" is `SKILLOPT_EPOCH_SIZE` decisions. `D_test` is simply your
  future sessions.
- **Predictive gate, not replay gate.** Without re-execution we cannot measure a true
  selection-set delta, so `gate()` *predicts* it with a judge model. This is the weakest
  link versus the paper. If you have canary tasks/tests, point `SKILLOPT_SCORE_CMD` at a
  command that prints a float and you recover a genuine replay-based score.
- **Propose-only default.** The paper auto-accepts gated edits; we stage them and require
  `apply` (or opt-in `SKILLOPT_AUTOAPPLY=1`) so a human stays in the loop.
- **Bounded edit surface.** Only the two marked regions are writable; the hand-authored
  Core section is out of bounds — protecting the instructions you actually care about.

## Safety properties (and why)

- **Strict-improvement gate + rejected buffer** prevent silent drift and re-proposing dead
  ends — the core reason the paper's gate exists.
- **Region markers** bound what can change; a missing marker raises rather than guessing.
- **Non-fatal hook** (`evolve.py` swallows errors, exits 0) means evolution never blocks a
  session.
- **Propose-only default** keeps rewrites reviewable until explicitly automated.
