"""Content-free, completed-turn timing extraction shared by hooks and backfill.

Claude timestamps describe completed transcript blocks, not first tokens. Codex
tool execution timestamps are not available; do not infer them from tool output.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any


def timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def milliseconds(value: Any) -> int | None:
    # Missing and invalid measurements must stay missing, including bools.
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 10**12:
        return int(value)
    return None


def tool_kind(name: str, arguments: Any) -> str:
    """Inspect commands locally, upload only a fixed category and tool name."""
    text = str(arguments.get("command") or arguments.get("cmd") or "") if isinstance(arguments, dict) else ""
    patterns = (
        ("test", r"\b(pytest|unittest|vitest|jest|test)\b"),
        ("build", r"\b(build|compile|make|cmake)\b"),
        ("lint", r"\b(lint|eslint|ruff|clippy|fmt|prettier)\b"),
        ("web", r"\b(curl|wget)\b"),
        ("version_control", r"\bgit\b"),
        ("wait", r"\b(sleep|wait)\b"),
        ("search_read", r"\b(rg|grep|find|cat|sed|head|tail|ls)\b"),
    )
    for kind, pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return kind
    lower = name.lower()
    if any(word in lower for word in ("askuser", "user_input", "exitplan")):
        return "user_input"
    if any(word in lower for word in ("agent", "task")):
        return "subagent"
    if lower.startswith("mcp__"):
        return "mcp"
    if any(word in lower for word in ("web", "fetch", "browse")):
        return "web"
    if any(word in lower for word in ("read", "search", "glob", "grep", "list")):
        return "search_read"
    if any(word in lower for word in ("write", "edit", "patch")):
        return "edit"
    if any(word in lower for word in ("bash", "shell", "exec")):
        return "shell"
    return "other"


def _base(context: dict, turn_id: str, start: datetime, end: datetime) -> dict:
    return {
        **context,
        "turn_id": turn_id,
        "started_at": start.isoformat(),
        "finished_at": end.isoformat(),
        "duration_ms": round((end - start).total_seconds() * 1000),
        "time_to_first_token_ms": None,
        "timing_source": "timestamps",
        "tool_status": "unavailable",
        "tools": [],
        "model_blocks": [],
    }


def codex_turns(entries: list[dict], context: dict) -> list[dict]:
    turns: dict[str, dict] = {}
    completed: dict[str, dict] = {}
    model = context.get("model_name") or "unknown"
    for entry in entries:
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if entry.get("type") == "turn_context":
            model = str(payload.get("model") or model)
        if entry.get("type") != "event_msg":
            continue
        kind = payload.get("type")
        turn_id = str(payload.get("turn_id") or "")
        at = timestamp(entry.get("timestamp"))
        if not turn_id or at is None:
            continue
        if kind == "task_started":
            turns[turn_id] = {"start": at, "model": model}
        elif kind == "task_complete":
            recorded = milliseconds(payload.get("duration_ms"))
            start = at - timedelta(milliseconds=recorded) if recorded is not None else turns.get(turn_id, {}).get("start")
            if start is None or start > at:
                continue
            row = _base(context, turn_id, start, at)
            row["model_name"] = model
            row["timing_source"] = "recorded" if recorded is not None else "timestamps"
            ttft = milliseconds(payload.get("time_to_first_token_ms"))
            row["time_to_first_token_ms"] = ttft if ttft is not None and ttft <= row["duration_ms"] else None
            completed[turn_id] = row
            turns.pop(turn_id, None)
    return list(completed.values())


def claude_turns(entries: list[dict], context: dict, *, include_sidechain=False) -> list[dict]:
    """One user prompt through its final assistant block; tool results aren't prompts."""
    rows: dict[str, dict] = {}
    turn: dict | None = None

    def finish():
        if not turn or not turn.get("end") or turn["pending"] or not turn.get("final"):
            return
        row = _base(context, turn["id"], turn["start"], turn["end"])
        row.update(
            model_name=turn["model"], tool_status="measured" if not turn["unmatched"] else "incomplete",
            tools=turn["tools"], model_blocks=turn["blocks"],
        )
        rows[row["turn_id"]] = row

    for index, entry in enumerate(entries):
        if entry.get("isSidechain") and not include_sidechain:
            continue
        at = timestamp(entry.get("timestamp"))
        if at is None:
            continue
        message = entry.get("message") or {}
        if not isinstance(message, dict):
            continue
        content = message.get("content") or []
        blocks = content if isinstance(content, list) else []
        result_blocks = [block for block in blocks if isinstance(block, dict) and block.get("type") == "tool_result"]
        is_prompt = (entry.get("type") == "user" and not result_blocks
                     and not entry.get("isMeta") and not entry.get("isCompactSummary")
                     and not entry.get("toolUseResult"))
        if is_prompt:
            finish()
            turn = {"id": str(entry.get("uuid") or f"prompt-{index}"), "start": at, "last": at,
                    "model": context.get("model_name") or "unknown", "end": None, "final": False,
                    "pending": {}, "tools": [], "blocks": [], "seen": set(), "unmatched": False}
            continue
        if turn is None or at < turn["start"]:
            continue
        for block in result_blocks:
            call = turn["pending"].pop(str(block.get("tool_use_id") or ""), None)
            if call and at >= call["start"]:
                turn["tools"].append({"tool": call["tool"], "kind": call["kind"],
                                      "started_at": call["start"].isoformat(), "finished_at": at.isoformat()})
            else:
                turn["unmatched"] = True
        if entry.get("type") == "assistant" and message.get("model") != "<synthetic>":
            turn["model"] = str(message.get("model") or turn["model"])
            turn["end"] = at
            valid_blocks = [b for b in blocks if isinstance(b, dict)]
            block = next((b for b in valid_blocks if b.get("type") in {"thinking", "redacted_thinking", "text", "tool_use"}), None)
            if block and at >= turn["last"]:
                kind = {"thinking": "thinking", "redacted_thinking": "thinking", "text": "text", "tool_use": "tool_writing"}[block["type"]]
                turn["blocks"].append({"kind": kind, "started_at": turn["last"].isoformat(), "finished_at": at.isoformat()})
            for block in valid_blocks:
                call_id = str(block.get("id") or "")
                if block.get("type") == "tool_use" and call_id and call_id not in turn["seen"]:
                    name = str(block.get("name") or "unknown")[:160]
                    turn["pending"][call_id] = {"start": at, "tool": name, "kind": tool_kind(name, block.get("input"))}
                    turn["seen"].add(call_id)
            turn["final"] = bool(any(b.get("type") == "text" for b in valid_blocks)
                                 and message.get("stop_reason") in {None, "end_turn", "stop_sequence"}
                                 and not any(b.get("type") == "tool_use" for b in valid_blocks))
        turn["last"] = max(turn["last"], at)
    finish()
    return list(rows.values())


def build_turn_timings(entries: list[dict], *, source: str, session_id: str,
                       project_name: str, agent_version: str = "unknown", model_name: str = "unknown",
                       include_sidechain=False) -> list[dict]:
    context = {"session_id": session_id, "project_name": project_name,
               "agent_type": "codex" if source == "codex" else "claude-code",
               "agent_version": agent_version, "model_name": model_name}
    if not session_id:
        return []
    return codex_turns(entries, context) if source == "codex" else claude_turns(entries, context, include_sidechain=include_sidechain)
