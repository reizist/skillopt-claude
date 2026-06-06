#!/usr/bin/env python3
"""SkillOpt-Claude: a self-evolving CLAUDE.md.

Adapts the SkillOpt training loop (arXiv:2605.23904) to Claude Code. The mapping:

    paper                         this script
    -----                         -----------
    skill document s              the LEARNED_RULES region of CLAUDE.md
    protected slow-update field   the SLOW_UPDATE region of CLAUDE.md
    forward pass (rollouts)       one finished Claude Code session (the transcript)
    rollout score r(s)            heuristic_score() over transcript signals
    backward pass (reflection)    run_optimizer(): staged analyst -> merge -> ranking
    edit merge + LR budget        ranking() + merge_and_rank() clamp, clipped to L_t
    validation gate (strict >)    gate(): judge-predicted delta, strict improvement only
    rejected-edit buffer B        .claude/skillopt/rejected.jsonl (epoch-local)
    score cache C                 .claude/skillopt/scores.json
    meta skill (teacher-only)     .claude/skillopt/meta.md
    D_test generalization         your next sessions (online setting)

Online adaptation notes (where the paper and reality diverge):
- The paper trains over a fixed dataset with a held-out selection set. Claude Code gives
  you a *stream* of sessions instead, so this is the online/streaming variant: each
  session is one rollout, evidence accumulates in a sliding window, and one "epoch" is
  EPOCH_SIZE sessions.
- There is no cheap way to re-execute a past session under a candidate CLAUDE.md, so the
  validation gate is a judge model that *predicts* whether the candidate rules would have
  prevented the observed failures without harming the successes. Swap in a replay/canary
  scorer via SKILLOPT_SCORE_CMD if you have one.
- Default is propose-only and conservative: edits are written to proposal.md and applied
  only on `apply` (or set SKILLOPT_AUTOAPPLY=1).

Subcommands: reflect | apply | status
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ----------------------------------------------------------------------------- config
ROOT = Path(os.environ.get("SKILLOPT_ROOT", Path.cwd()))
CLAUDE_MD = ROOT / "CLAUDE.md"
STATE = ROOT / ".claude" / "skillopt"
OPTIMIZER_MODEL = os.environ.get("SKILLOPT_OPTIMIZER_MODEL", "claude-sonnet-4-6")
LR_BUDGET = int(os.environ.get("SKILLOPT_LR_BUDGET", "3"))   # L_t: max edits per reflection
EPOCH_SIZE = int(os.environ.get("SKILLOPT_EPOCH_SIZE", "8"))  # sessions per epoch
WINDOW = int(os.environ.get("SKILLOPT_WINDOW", "6"))          # reflection minibatch size
AUTOAPPLY = os.environ.get("SKILLOPT_AUTOAPPLY") == "1"
SCORE_CMD = os.environ.get("SKILLOPT_SCORE_CMD")              # optional external scorer

LEARN_A, LEARN_B = "<!-- LEARNED_RULES_START -->", "<!-- LEARNED_RULES_END -->"
SLOW_A, SLOW_B = "<!-- SLOW_UPDATE_START -->", "<!-- SLOW_UPDATE_END -->"

# correction / failure signals in the user's turns (EN + JA)
CORRECTION = re.compile(
    r"\b(no|nope|wrong|don'?t|stop|undo|revert|instead|actually|that'?s not|"
    r"not what|again|redo|broke|broken|error|fail)\b|"
    r"(違う|ダメ|だめ|やめて|戻して|間違|そうじゃない|やり直|直して|壊れ)",
    re.I,
)


# ----------------------------------------------------------------------------- helpers
def log(msg: str) -> None:
    print(f"[skillopt] {msg}", file=sys.stderr)


def read_state(name: str, default: str = "") -> str:
    p = STATE / name
    return p.read_text() if p.exists() else default


def write_state(name: str, content: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / name).write_text(content)


def append_jsonl(name: str, obj: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / name).open("a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(name: str) -> list[dict]:
    p = STATE / name
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def region(text: str, a: str, b: str) -> str:
    """Return the inner content between markers a and b (exclusive)."""
    i, j = text.find(a), text.find(b)
    if i == -1 or j == -1:
        return ""
    return text[i + len(a):j]


def set_region(text: str, a: str, b: str, inner: str) -> str:
    i, j = text.find(a), text.find(b)
    if i == -1 or j == -1:
        raise SystemExit(f"markers {a}/{b} missing from CLAUDE.md")
    return text[: i + len(a)] + "\n" + inner.strip("\n") + "\n" + text[j:]


# ------------------------------------------------------------------- forward pass
def collect_evidence(transcript_path: str | None) -> dict:
    """Turn one finished session (transcript JSONL) into a rollout evidence unit."""
    user_turns, tool_errors, assistant_chars = [], 0, 0
    if transcript_path and Path(transcript_path).exists():
        for line in Path(transcript_path).read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = ev.get("message", {})
            role = ev.get("type") or msg.get("role")
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        if role == "user":
                            user_turns.append(block["text"])
                        else:
                            assistant_chars += len(block.get("text", ""))
                    if block.get("type") == "tool_result" and block.get("is_error"):
                        tool_errors += 1
            elif isinstance(content, str) and role == "user":
                user_turns.append(content)

    corrections = sum(1 for t in user_turns if CORRECTION.search(t))
    evidence = {
        "ts": int(time.time()),
        "n_user_turns": len(user_turns),
        "corrections": corrections,
        "tool_errors": tool_errors,
        "assistant_chars": assistant_chars,
        # keep a compact, truncated transcript-of-friction for the optimizer
        "friction": [t[:400] for t in user_turns if CORRECTION.search(t)][:8],
        "outcome": "fail" if (corrections or tool_errors) else "success",
    }
    evidence["score"] = heuristic_score(evidence)
    return evidence


def heuristic_score(ev: dict) -> float:
    """Rollout score r(s): higher is better. Penalize friction; 1.0 == clean session."""
    if SCORE_CMD:
        try:
            out = subprocess.run(
                SCORE_CMD, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=300
            )
            return float(out.stdout.strip())
        except Exception as e:  # noqa: BLE001
            log(f"SCORE_CMD failed ({e}); falling back to heuristic")
    turns = max(1, ev["n_user_turns"])
    penalty = (ev["corrections"] * 1.0 + ev["tool_errors"] * 0.5) / turns
    return round(max(0.0, 1.0 - penalty), 4)


# ------------------------------------------------------------------- backward pass
def _client():
    try:
        from anthropic import Anthropic
    except ImportError:
        raise SystemExit("anthropic SDK missing — run via `uv run scripts/evolve.py` "
                         "(or `uv sync` first)")
    return Anthropic()


def _ask_json(system: str, user: str) -> dict | list:
    client = _client()
    resp = client.messages.create(
        model=OPTIMIZER_MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return []
    return json.loads(m.group(1))


# The backward pass mirrors SkillOpt's staged optimizer (paper Appendix C.2): the failure
# and success minibatches are analyzed by separate analysts, each stream is merged on its
# own, the two are merged with failure priority, and the result is ranked under the LR
# budget. (The public mastercodeai/skillopt-methodology-skill repo, MIT, extracts these
# same prompt stages — analyst_error / analyst_success / merge_* / ranking — from the paper.)

_EDIT_SHAPE = """Each edit is:
  {"op":"add|replace|delete","target":"<existing rule text, for replace/delete>",
   "content":"<new rule, for add/replace>","rationale":"<why, 1 line>"}
Rules must be generalizable procedural knowledge — never task-specific hacks, never a
restatement of an existing rule. Return ONLY a JSON array of edits."""

ANALYST_ERROR_SYS = (
    "You are the SkillOpt FAILURE analyst. Examine a minibatch of failed sessions "
    "(corrections, tool errors) against the current LEARNED_RULES. Identify the common, "
    "SYSTEMATIC error patterns — not one-off mistakes — and propose bounded edits that "
    "would prevent them. Do NOT repeat anything in the rejected-edit buffer.\n" + _EDIT_SHAPE
)
ANALYST_SUCCESS_SYS = (
    "You are the SkillOpt SUCCESS analyst. Examine a minibatch of successful sessions "
    "against the current LEARNED_RULES. Identify behaviors worth preserving or amplifying "
    "and propose at most a few bounded edits that reinforce them. Be conservative — "
    "successes usually need few or no edits.\n" + _EDIT_SHAPE
)
MERGE_FAILURE_SYS = (
    "You are the SkillOpt merge stage for FAILURE edits. Consolidate the proposed "
    "failure-correction edits: drop duplicates and near-duplicates, resolve contradictions, "
    "prefer the more general phrasing.\n" + _EDIT_SHAPE
)
MERGE_SUCCESS_SYS = (
    "You are the SkillOpt merge stage for SUCCESS edits. Consolidate the proposed "
    "success-reinforcing edits: drop duplicates, resolve contradictions, prefer the more "
    "general phrasing.\n" + _EDIT_SHAPE
)
MERGE_FINAL_SYS = (
    "You are the SkillOpt FINAL merge. Combine the consolidated failure edits and success "
    "edits into one coherent set. On any conflict, FAILURE corrections take priority. Drop "
    "redundancies.\n" + _EDIT_SHAPE
)
RANKING_SYS = (
    "You are the SkillOpt ranking stage. Rank the merged edits by expected utility "
    "(impact on preventing failures x generalizability) and return ONLY the top %d, "
    "highest utility first.\n" % LR_BUDGET + _EDIT_SHAPE
)


def _ask_edits(system: str, payload: dict) -> list[dict]:
    res = _ask_json(system, json.dumps(payload, ensure_ascii=False))
    return res if isinstance(res, list) else []


def analyst(kind: str, minibatch: list[dict], rules: str, rejected: list[dict], meta: str) -> list[dict]:
    sys_prompt = ANALYST_ERROR_SYS if kind == "fail" else ANALYST_SUCCESS_SYS
    key = "failure_minibatch" if kind == "fail" else "success_minibatch"
    payload = {
        "current_learned_rules": rules.strip() or "(empty)",
        "meta_skill_guidance": meta.strip() or "(none)",
        key: minibatch,
    }
    if kind == "fail":
        payload["rejected_edit_buffer"] = [r.get("edit") for r in rejected][-12:]
    return _ask_edits(sys_prompt, payload)


def merge(edits: list[dict], kind: str) -> list[dict]:
    if len(edits) <= 1:
        return edits
    sys_prompt = MERGE_FAILURE_SYS if kind == "fail" else MERGE_SUCCESS_SYS
    return _ask_edits(sys_prompt, {"edits": edits}) or edits


def merge_final(failure_edits: list[dict], success_edits: list[dict]) -> list[dict]:
    # nothing to reconcile unless both streams produced edits
    if not failure_edits or not success_edits:
        return failure_edits + success_edits
    return _ask_edits(MERGE_FINAL_SYS,
                      {"failure_edits": failure_edits, "success_edits": success_edits}) \
        or (failure_edits + success_edits)


def ranking(edits: list[dict]) -> list[dict]:
    if len(edits) <= LR_BUDGET:
        return edits
    return _ask_edits(RANKING_SYS, {"edits": edits}) or edits


def run_optimizer(window: list[dict], rules: str, rejected: list[dict], meta: str) -> list[dict]:
    """Staged backward pass: analyst -> per-stream merge -> final merge -> ranking.

    Empty streams are skipped, so a clean window costs few or no optimizer calls.
    """
    fails = [e for e in window if e["outcome"] == "fail"]
    succ = [e for e in window if e["outcome"] == "success"]
    fail_edits = merge(analyst("fail", fails, rules, rejected, meta), "fail") if fails else []
    succ_edits = merge(analyst("success", succ, rules, rejected, meta), "success") if succ else []
    return ranking(merge_final(fail_edits, succ_edits))


def merge_and_rank(edits: list[dict]) -> list[dict]:
    """Local safety clamp after the staged optimizer: dedup, drop empties, hard-clip to L_t.

    The LLM ranking stage already orders and trims, but this guarantees the budget and
    removes exact duplicates deterministically even if a stage misbehaves.
    """
    seen, merged = set(), []
    for e in edits:
        key = (e.get("op"), (e.get("content") or e.get("target") or "").strip()[:80])
        if not key[1] or key in seen:
            continue
        seen.add(key)
        merged.append(e)
    # failure-driven edits (replace/delete) ranked above pure additions, paper-style
    merged.sort(key=lambda e: 0 if e.get("op") in ("replace", "delete") else 1)
    return merged[:LR_BUDGET]


def apply_edits(rules: str, edits: list[dict]) -> str:
    lines = [ln for ln in rules.splitlines() if ln.strip() and not ln.strip().startswith("<!--")]
    for e in edits:
        op, target, content = e.get("op"), e.get("target", ""), e.get("content", "")
        if op == "add" and content:
            lines.append(f"- {content.lstrip('- ').strip()}")
        elif op in ("replace", "delete"):
            lines = [ln for ln in lines if target.strip() not in ln] if target else lines
            if op == "replace" and content:
                lines.append(f"- {content.lstrip('- ').strip()}")
    return "\n".join(lines)


# ------------------------------------------------------------------- validation gate
GATE_SYS = """You are the SkillOpt validation gate. Given the failure/success evidence and
a CANDIDATE set of learned rules vs the CURRENT set, predict whether the candidate would
STRICTLY improve outcomes (fewer corrections / errors) without harming successes.
Be conservative: ties and uncertainty mean reject. Return ONLY:
  {"accept": true|false, "predicted_delta": <float -1..1>, "reason": "<1 line>"}"""


def gate(window: list[dict], current: str, candidate: str) -> dict:
    if candidate.strip() == current.strip():
        return {"accept": False, "predicted_delta": 0.0, "reason": "no change"}
    user = json.dumps(
        {"current_rules": current, "candidate_rules": candidate,
         "evidence": window}, ensure_ascii=False)
    verdict = _ask_json(GATE_SYS, user)
    if not isinstance(verdict, dict):
        return {"accept": False, "predicted_delta": 0.0, "reason": "no verdict"}
    # strict improvement only (paper: ties rejected)
    verdict["accept"] = bool(verdict.get("accept")) and float(verdict.get("predicted_delta", 0)) > 0
    return verdict


# ------------------------------------------------------------------- meta / epoch update
META_SYS = """You are the SkillOpt meta-updater (teacher). Summarize, in <=5 terse bullets,
the durable lessons from this epoch's accepted and rejected edits: which edit patterns
helped, which were rejected and why, and persistent failure categories. This guidance is
prepended to future optimizer prompts. Return plain markdown bullets only."""


def maybe_meta_update(history: list[dict]) -> None:
    epoch = history[-EPOCH_SIZE:]
    if len(epoch) < EPOCH_SIZE:
        return
    user = json.dumps(epoch, ensure_ascii=False)
    client = _client()
    resp = client.messages.create(
        model=OPTIMIZER_MODEL, max_tokens=600,
        system=[{"type": "text", "text": META_SYS}],
        messages=[{"role": "user", "content": user}],
    )
    meta = "".join(b.text for b in resp.content if b.type == "text").strip()
    write_state("meta.md", meta)
    # protected slow-update block in CLAUDE.md gets the deployable distillation
    md = CLAUDE_MD.read_text()
    md = set_region(md, SLOW_A, SLOW_B, meta)
    CLAUDE_MD.write_text(md)
    write_state("rejected.jsonl", "")  # reset epoch-local buffer B
    log("epoch meta update written; rejected buffer reset")


# ----------------------------------------------------------------------------- commands
def cmd_reflect() -> None:
    # Stop hook passes JSON on stdin incl. transcript_path
    transcript = None
    if not sys.stdin.isatty():
        try:
            transcript = json.loads(sys.stdin.read() or "{}").get("transcript_path")
        except json.JSONDecodeError:
            pass

    ev = collect_evidence(transcript)
    append_jsonl("evidence.jsonl", ev)
    window = read_jsonl("evidence.jsonl")[-WINDOW:]
    log(f"evidence: score={ev['score']} outcome={ev['outcome']} window={len(window)}")

    md = CLAUDE_MD.read_text()
    rules = region(md, LEARN_A, LEARN_B)
    rejected = read_jsonl("rejected.jsonl")
    meta = read_state("meta.md")

    edits = merge_and_rank(run_optimizer(window, rules, rejected, meta))
    if not edits:
        log("no edits proposed")
        return

    new_rules = apply_edits(rules, edits)
    verdict = gate(window, rules, new_rules)
    candidate_md = set_region(md, LEARN_A, LEARN_B, new_rules)

    decision = {"ts": ev["ts"], "edits": edits, "verdict": verdict}
    append_jsonl("history.jsonl", decision)

    if not verdict["accept"]:
        for e in edits:
            append_jsonl("rejected.jsonl", {"edit": e, "reason": verdict["reason"]})
        log(f"REJECTED: {verdict['reason']}")
        return

    # accepted by the gate
    h = hashlib.sha256(candidate_md.encode()).hexdigest()[:12]
    scores = json.loads(read_state("scores.json", "{}"))
    scores[h] = verdict["predicted_delta"]
    write_state("scores.json", json.dumps(scores, indent=2))
    write_state("proposal.md", candidate_md)

    if AUTOAPPLY:
        CLAUDE_MD.write_text(candidate_md)
        log(f"ACCEPTED & APPLIED (Δ~{verdict['predicted_delta']}): {len(edits)} edit(s)")
    else:
        log(f"ACCEPTED (Δ~{verdict['predicted_delta']}) — proposal.md written; run "
            f"`python3 scripts/evolve.py apply` to write CLAUDE.md")

    maybe_meta_update(read_jsonl("history.jsonl"))


def cmd_apply() -> None:
    prop = STATE / "proposal.md"
    if not prop.exists():
        raise SystemExit("no proposal.md — run `reflect` first")
    CLAUDE_MD.write_text(prop.read_text())
    prop.unlink()
    log("proposal applied to CLAUDE.md")


def cmd_status() -> None:
    hist = read_jsonl("history.jsonl")
    acc = sum(1 for h in hist if h["verdict"].get("accept"))
    print(f"sessions reflected : {len(read_jsonl('evidence.jsonl'))}")
    print(f"decisions          : {len(hist)} ({acc} accepted, {len(hist)-acc} rejected)")
    print(f"rejected buffer (B) : {len(read_jsonl('rejected.jsonl'))} entries")
    print(f"optimizer model     : {OPTIMIZER_MODEL}  (LR budget L_t={LR_BUDGET})")
    print("\n--- meta skill ---\n" + (read_state("meta.md") or "(none yet)"))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "reflect"
    {"reflect": cmd_reflect, "apply": cmd_apply, "status": cmd_status}.get(
        cmd, cmd_reflect
    )()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — a hook must never block the session
        log(f"non-fatal: {e}")
        sys.exit(0)
