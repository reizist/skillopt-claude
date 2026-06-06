#!/usr/bin/env python3
"""SkillOpt-Claude: a self-evolving CLAUDE.md.

Adapts the SkillOpt training loop (arXiv:2605.23904) to Claude Code. The mapping:

    paper                         this script
    -----                         -----------
    skill document s              the LEARNED_RULES region of CLAUDE.md
    protected slow-update field   the SLOW_UPDATE region of CLAUDE.md
    forward pass (rollouts)       one finished Claude Code session (the transcript)
    rollout score r(s)            heuristic_score() over transcript signals
    backward pass (reflection)    optimizer model proposes bounded add/replace/delete
    edit merge + LR budget        merge_and_rank(), clipped to L_t
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


PROPOSE_SYS = """You are the SkillOpt optimizer. You improve a project's CLAUDE.md by
proposing BOUNDED edits to its LEARNED_RULES region only. Rules must be generalizable
procedural knowledge that would prevent the observed failures or amplify observed
successes — never task-specific hacks, never restatements of existing rules.

Return ONLY a JSON array of edits, each:
  {"op":"add|replace|delete","target":"<existing rule text, for replace/delete>",
   "content":"<new rule, for add/replace>","rationale":"<why, 1 line>"}
Propose at most %d edits. Prefer the smallest change that addresses a systematic pattern.
Do NOT repeat anything in the rejected-edit buffer.""" % LR_BUDGET


def propose_edits(window: list[dict], rules: str, rejected: list[dict], meta: str) -> list[dict]:
    fails = [e for e in window if e["outcome"] == "fail"]
    succ = [e for e in window if e["outcome"] == "success"]
    user = json.dumps(
        {
            "current_learned_rules": rules.strip() or "(empty)",
            "meta_skill_guidance": meta.strip() or "(none)",
            "failure_minibatch": fails,
            "success_minibatch": succ,
            "rejected_edit_buffer": [r.get("edit") for r in rejected][-12:],
        },
        ensure_ascii=False,
    )
    edits = _ask_json(PROPOSE_SYS, user)
    return edits if isinstance(edits, list) else []


def merge_and_rank(edits: list[dict]) -> list[dict]:
    """Consolidate duplicates, drop empties, clip to the LR budget L_t."""
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

    edits = merge_and_rank(propose_edits(window, rules, rejected, meta))
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
