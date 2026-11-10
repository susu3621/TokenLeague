"""Content-free, completed-turn timing extraction shared by hooks and backfill.

Claude timestamps describe completed transcript blocks, not first tokens. Newer
Codex logs have native item timing; older logs can pair tool calls and results.
Intervals inferred between model events are explicitly marked as estimates.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import defaultdict
import json
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
    if name.lower() in {"exec", "functions.exec", "multi_tool_use.parallel", "functions.parallel"}:
        return "orchestration"
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
    if any(word in lower for word in ("sleep", "wait")):
        return "wait"
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
        "parser_version": 2,
    }


def _epoch_ms(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _item_bounds(payload: dict, at: datetime) -> tuple[datetime, datetime] | None:
    end = _epoch_ms(payload.get("completed_at_ms")) or at
    start = _epoch_ms(payload.get("started_at_ms"))
    item = payload.get("item") or {}
    if start is None and isinstance(item, dict):
        duration = item.get("duration")
        ms = milliseconds(item.get("durationMs"))
        if isinstance(duration, dict):
            seconds, nanos = duration.get("secs", 0), duration.get("nanos", 0)
            if (isinstance(seconds, int) and not isinstance(seconds, bool) and seconds >= 0
                    and isinstance(nanos, int) and not isinstance(nanos, bool) and 0 <= nanos < 1_000_000_000):
                ms = seconds * 1000 + nanos / 1_000_000
        if ms is not None and 0 <= ms < 10**12:
            start = end - timedelta(milliseconds=ms)
    return (start, end) if start is not None and start <= end else None


def _codex_tool(item: dict) -> tuple[str, str] | None:
    kind = item.get("type")
    if kind == "CommandExecution":
        command = item.get("command") or []
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        actions = item.get("parsed_cmd") or []
        if isinstance(actions, list) and actions and all(
            isinstance(action, dict) and str(action.get("type", "")).lower() in {"read", "search", "listfiles"}
            for action in actions
        ):
            return "exec_command", "search_read"
        return "exec_command", tool_kind("exec_command", {"command": command})
    if kind == "McpToolCall":
        name = str(item.get("server") or "mcp") + "." + str(item.get("tool") or "unknown")
        return name[:160], tool_kind("mcp__" + name, item.get("arguments"))
    if kind == "FileChange":
        return "apply_patch", "edit"
    if kind == "Extension":
        name = str(item.get("kind") or "extension")[:160]
        return name, tool_kind(name, {})
    return None


def _codex_activity(row: dict, events: list[dict]) -> None:
    lower, upper = timestamp(row["started_at"]), timestamp(row["finished_at"])
    native_tools, native_models = {}, {}
    has_native = False
    pending_native = set()
    for entry in events:
        payload = entry["payload"]
        if entry.get("type") != "event_msg" or payload.get("type") != "item_completed":
            continue
        item = payload.get("item") or {}
        at = timestamp(entry.get("timestamp"))
        if not isinstance(item, dict) or at is None:
            continue
        bounds = _item_bounds(payload, at)
        label = _codex_tool(item)
        item_type = item.get("type")
        identity = str(item.get("id") or "")
        if label or item_type in {"Reasoning", "AgentMessage", "ContextCompaction"}:
            has_native = True
        if bounds is None:
            if label:
                pending_native.add(identity or "missing-item-id")
            continue
        if not identity:
            continue
        if label:
            status = str(item.get("status") or "").lower().replace("_", "")
            if status in {"inprogress", "running", "pending"}:
                pending_native.add(identity)
                continue
            native_tools[identity] = (*bounds, *label)
        elif item_type in {"Reasoning", "AgentMessage", "ContextCompaction"}:
            native_models[identity] = item_type
    incomplete = any(identity not in native_tools for identity in pending_native)

    tools, blocks = [], []

    def add_span(target, kind, start, end, *, source, tool=None):
        if start is None or end is None or end < lower or start > upper:
            return
        start, end = max(start, lower), min(end, upper)
        if end < start:
            return
        value = {"kind": kind, "started_at": start.isoformat(), "finished_at": end.isoformat(), "source": source}
        if tool is not None:
            value["tool"] = tool
        target.append(value)

    for start, end, name, kind in native_tools.values():
        add_span(tools, kind, start, end, source="recorded", tool=name)

    calls = {}
    outputs = {}
    last_boundary = lower
    seen_native = set()
    saw_user = False

    def model(kind, start, end, source):
        if end > start:
            add_span(blocks, kind, start, end, source=source)

    for entry in events:
        payload = entry["payload"]
        at = timestamp(entry.get("timestamp"))
        if at is None:
            continue
        typ = payload.get("type")
        if entry.get("type") == "event_msg" and typ == "item_completed":
            item = payload.get("item") or {}
            if not isinstance(item, dict):
                continue
            item_type, identity = item.get("type"), str(item.get("id") or "")
            if identity in seen_native:
                continue
            seen_native.add(identity)
            if item_type == "UserMessage":
                # A later human message must not turn the preceding idle gap
                # into estimated reasoning time.
                if saw_user:
                    last_boundary = max(last_boundary, at)
                saw_user = True
                continue
            bounds = _item_bounds(payload, at)
            if bounds is None:
                continue
            start, end = bounds
            if item_type in {"Reasoning", "AgentMessage"}:
                kind = "thinking" if item_type == "Reasoning" else "text"
                if end > start:
                    model("response_wait", last_boundary, start, "estimated")
                    model(kind, start, end, "recorded")
                else:
                    model(kind, last_boundary, end, "estimated")
            elif item_type == "ContextCompaction":
                model("compaction", start, end, "recorded")
            if identity in native_tools or item_type in {"Reasoning", "AgentMessage", "ContextCompaction"}:
                last_boundary = max(last_boundary, end)
            continue
        if entry.get("type") != "response_item":
            continue
        if typ in {"function_call", "custom_tool_call"}:
            call_id = str(payload.get("call_id") or "")
            if not call_id or call_id in calls:
                continue
            meta = payload.get("internal_chat_message_metadata_passthrough") or {}
            created = None
            if isinstance(meta, dict):
                value = meta.get("create_time")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    created = _epoch_ms(value * 1000)
            writing_start = max(last_boundary, created) if created is not None and created <= at else last_boundary
            model("response_wait", last_boundary, writing_start, "estimated")
            model("tool_writing", writing_start, at, "estimated")
            name = str(payload.get("name") or "unknown")
            namespace = str(payload.get("namespace") or "")
            label = (namespace + "." + name if namespace else name)[:160]
            arguments = payload.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            if typ == "custom_tool_call":
                arguments = {"command": payload.get("input") or ""}
            calls[call_id] = (at, label, tool_kind(label, arguments))
            last_boundary = max(last_boundary, at)
        elif typ in {"function_call_output", "custom_tool_call_output"}:
            call_id = str(payload.get("call_id") or "")
            if call_id:
                outputs[call_id] = max(outputs.get(call_id, at), at)
            last_boundary = max(last_boundary, at)
        elif typ == "reasoning" or typ == "message" and payload.get("role") == "assistant":
            if str(payload.get("id") or "") in native_models:
                continue
            model("thinking" if typ == "reasoning" else "text", last_boundary, at, "estimated")
            last_boundary = max(last_boundary, at)

    for identity, (start, name, kind) in calls.items():
        if identity in native_tools:
            continue
        end = outputs.get(identity)
        if end is None or end < start:
            incomplete = True
            continue
        add_span(tools, kind, start, end, source="paired", tool=name)
    if any(identity not in calls and identity not in native_tools for identity in outputs):
        incomplete = True
    row["tools"], row["model_blocks"] = tools, blocks
    if has_native or calls or tools:
        row["tool_status"] = "incomplete" if incomplete else "measured"


def codex_turns(entries: list[dict], context: dict) -> list[dict]:
    turns: dict[str, dict] = {}
    completed: dict[str, dict] = {}
    model = context.get("model_name") or "unknown"
    events = defaultdict(list)
    active_turn = None
    for entry in entries:
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if entry.get("type") == "turn_context":
            model = str(payload.get("model") or model)
        if entry.get("type") == "response_item":
            meta = payload.get("internal_chat_message_metadata_passthrough") or {}
            turn_id = (meta.get("turn_id") if isinstance(meta, dict) else None) or active_turn
            if turn_id:
                events[str(turn_id)].append(entry)
        if entry.get("type") != "event_msg":
            continue
        kind = payload.get("type")
        turn_id = str(payload.get("turn_id") or "")
        at = timestamp(entry.get("timestamp"))
        if not turn_id or at is None:
            continue
        if kind == "task_started":
            active_turn = turn_id
            turns[turn_id] = {"start": at, "model": model}
        elif kind == "item_completed":
            events[turn_id].append(entry)
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
            if active_turn == turn_id:
                active_turn = None
    for turn_id, row in completed.items():
        _codex_activity(row, events[turn_id])
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
