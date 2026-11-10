"""Timing validation and interval-based analytics. All durations are milliseconds."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math


TOOL_KINDS = {"test", "build", "lint", "web", "version_control", "wait", "search_read",
              "user_input", "subagent", "mcp", "edit", "shell", "other", "orchestration"}
MODEL_KINDS = {"thinking", "text", "tool_writing", "response_wait", "compaction"}
BUCKETS = (1000, 5000, 15000, 30000, 60000, 300000, 900000)


def parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def normalize(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    row = {}
    version = payload.get("parser_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 1000:
        raise ValueError("parser_version must be a positive integer")
    row["parser_version"] = version
    for field, limit in (("session_id", 255), ("turn_id", 255), ("project_name", 255),
                         ("agent_type", 64), ("agent_version", 128), ("model_name", 128)):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f"{field} must be a nonempty string of at most {limit} characters")
        row[field] = value.strip()
    try:
        row["started_at"] = parse_time(payload.get("started_at"))
        row["finished_at"] = parse_time(payload.get("finished_at"))
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Valid started_at and finished_at timestamps are required") from None
    if row["finished_at"] < row["started_at"]:
        raise ValueError("finished_at must not precede started_at")
    duration = round((row["finished_at"] - row["started_at"]).total_seconds() * 1000)
    for field in ("duration_ms", "time_to_first_token_ms"):
        value = payload.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 10**12):
            raise ValueError(f"{field} must be a nonnegative integer or null")
        row[field] = value
    if row["duration_ms"] is not None and abs(row["duration_ms"] - duration) > 1:
        raise ValueError("duration_ms must match the recorded interval")
    row["duration_ms"] = duration
    if row["time_to_first_token_ms"] is not None and row["time_to_first_token_ms"] > duration:
        raise ValueError("time_to_first_token_ms must not exceed duration_ms")
    for field, choices in (("timing_source", {"recorded", "timestamps"}),
                           ("tool_status", {"measured", "unavailable", "incomplete"})):
        if payload.get(field) not in choices:
            raise ValueError(f"Invalid {field}")
        row[field] = payload[field]
    for field, kinds in (("tools", TOOL_KINDS), ("model_blocks", MODEL_KINDS)):
        values = payload.get(field, [])
        if not isinstance(values, list) or len(values) > 20000:
            raise ValueError(f"{field} must be an array of at most 20000 intervals")
        clean = []
        for item in values:
            if not isinstance(item, dict) or item.get("kind") not in kinds:
                raise ValueError(f"Invalid {field} interval")
            try:
                start, end = parse_time(item.get("started_at")), parse_time(item.get("finished_at"))
            except (ValueError, TypeError, OverflowError):
                raise ValueError(f"Invalid {field} timestamp") from None
            if end < start or start < row["started_at"] or end > row["finished_at"]:
                raise ValueError(f"{field} interval is outside the turn")
            span = {"kind": item["kind"], "started_at": start.isoformat(), "finished_at": end.isoformat()}
            if "source" in item:
                if item["source"] not in {"recorded", "paired", "estimated"}:
                    raise ValueError(f"Invalid {field} timing source")
                span["source"] = item["source"]
            if field == "tools":
                if not isinstance(item.get("tool"), str) or not 0 < len(item["tool"]) <= 160:
                    raise ValueError("Invalid tool name")
                span["tool"] = item["tool"]
            clean.append(span)
        row[field] = clean
    return row


def window_bounds(window: str, now: datetime, start=None, end=None):
    if start is not None or end is not None:
        if start is None or end is None or end <= start:
            raise ValueError("from and to must specify an increasing time range")
        effective_end = min(end, now)
        if effective_end <= start:
            raise ValueError("Time range must start before the current time")
        return start, effective_end
    days = {"week": 7, "month": 30, "quarter": 90}
    lower = now.replace(hour=0, minute=0, second=0, microsecond=0) if window == "today" else (
        now - timedelta(days=days[window]) if window in days else None)
    return lower, now


def union_ms(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum((end - start).total_seconds() * 1000 for start, end in merged)


def statistics(values):
    ordered = sorted(values)
    count = len(ordered)
    return {
        "samples": count,
        "average_ms": sum(ordered) / count if count else None,
        "p50_ms": ordered[max(0, math.ceil(count * .5) - 1)] if count else None,
        "p95_ms": ordered[max(0, math.ceil(count * .95) - 1)] if count else None,
        "max_ms": ordered[-1] if count else None,
    }


def _exclusive_breakdown(row, lower, upper):
    """Measured activity precedes model-gap estimates and wrapper fallbacks.

    A sweep makes the exclusive slices add up exactly to agent time, even when
    tool intervals overlap. Tool call latency is kept separately in tool rows.
    """
    start, end = max(row["started_at"], lower) if lower else row["started_at"], min(row["finished_at"], upper)
    events = defaultdict(list)
    events[start]
    events[end]
    for family, spans in (("tool", row.get("tools", [])), ("model", row.get("model_blocks", []))):
        for index, span in enumerate(spans):
            a, b = max(start, parse_time(span["started_at"])), min(end, parse_time(span["finished_at"]))
            if b > a:
                identity = (family, index)
                value = (family, span["kind"], span.get("tool", ""), span.get("source", "legacy"))
                events[a].append((True, identity, value))
                events[b].append((False, identity, value))
    active = {}
    slices = defaultdict(float)
    previous = start
    for at in sorted(events):
        duration = (at - previous).total_seconds() * 1000
        model = [v for v in active.values() if v[0] == "model" and v[3] != "estimated"]
        measured_tools = [v for v in active.values() if v[0] == "tool" and v[3] != "paired"]
        paired_tools = [v for v in active.values() if v[0] == "tool" and v[3] == "paired"]
        estimated_models = [v for v in active.values() if v[0] == "model" and v[3] == "estimated"]
        selected = model[-1:] or measured_tools or paired_tools or estimated_models[-1:]
        if selected and duration > 0:
            for key in selected:
                slices[key[:3]] += duration / len(selected)
        elif duration > 0:
            slices[("other", "unobserved", "")] += duration
        # Removals must win over additions for zero-width boundaries.
        for adding, identity, value in events[at]:
            if adding:
                active[identity] = value
            else:
                active.pop(identity, None)
        previous = at
    return slices


def summarize(rows, lower, upper):
    intervals = [(max(row["started_at"], lower) if lower else row["started_at"], min(row["finished_at"], upper)) for row in rows]
    agent_ms = sum(max(0, (b - a).total_seconds() * 1000) for a, b in intervals)
    active_ms = union_ms(intervals)
    # Percentiles use completed, un-clipped turns, while activity is clipped.
    complete = [r for r in rows if (lower is None or r["started_at"] >= lower) and r["finished_at"] <= upper]
    result = {
        "turn_count": len(rows), "duration": statistics([r["duration_ms"] for r in complete]),
        "ttft": statistics([r["time_to_first_token_ms"] for r in complete if r["time_to_first_token_ms"] is not None]),
        "agent_ms": agent_ms, "active_wall_ms": active_ms,
        "parallelism": agent_ms / active_ms if active_ms else None,
        "recorded_turns": sum(r["timing_source"] == "recorded" for r in rows),
        "tool_measured_turns": sum(r["tool_status"] == "measured" for r in rows),
        "tool_incomplete_turns": sum(r["tool_status"] == "incomplete" for r in rows),
        "tool_observed_turns": sum(r["tool_status"] != "unavailable" for r in rows),
        "legacy_codex_turns": sum(r["agent_type"] == "codex" and r.get("parser_version", 1) < 2 for r in rows),
    }
    slices = defaultdict(float)
    tools = {}
    for row in rows:
        for key, value in _exclusive_breakdown(row, lower, upper).items():
            slices[key] += value
        for span in row.get("tools", []):
            key = (span["kind"], span["tool"])
            group = tools.setdefault(key, {"kind": key[0], "tool": key[1], "values": [], "call_count": 0})
            a, b = parse_time(span["started_at"]), parse_time(span["finished_at"])
            if (lower is None or a >= lower) and a < upper:
                group["call_count"] += 1
                if b <= upper:
                    group["values"].append((b - a).total_seconds() * 1000)
    result["breakdown"] = [{"family": family, "kind": kind, "tool": tool, "duration_ms": duration,
                              "share": duration / agent_ms if agent_ms else 0}
                             for (family, kind, tool), duration in sorted(slices.items())]
    result["tools"] = []
    for key in set(tools) | {(kind, tool) for family, kind, tool in slices if family == "tool"}:
        group = tools.get(key, {"kind": key[0], "tool": key[1], "values": [], "call_count": 0})
        group["exclusive_ms"] = slices.get(("tool", *key), 0)
        group["share"] = group["exclusive_ms"] / agent_ms if agent_ms else 0
        group["duration"] = statistics(group.pop("values"))
        result["tools"].append(group)
    return result


def build_report(rows, *, lower=None, upper=None, known_sessions=None):
    upper = upper or datetime.now(timezone.utc)
    groups = {"projects": defaultdict(list), "sessions": defaultdict(list)}
    for row in rows:
        groups["projects"][row["project_name"]].append(row)
        groups["sessions"][(row["user_id"], row["agent_type"], row["session_id"], row["project_name"])].append(row)
    summary = summarize(rows, lower, upper)
    tools = summary.pop("tools")
    projects, sessions = [], []
    for project_name, items in groups["projects"].items():
        stats = summarize(items, lower, upper)
        stats.pop("tools")
        projects.append({"project_name": project_name, "session_count": len({(r["user_id"], r["agent_type"], r["session_id"]) for r in items}), **stats})
    for (user_id, agent_type, session_id, project_name), items in groups["sessions"].items():
        stats = summarize(items, lower, upper)
        stats.pop("tools")
        start = max(min(r["started_at"] for r in items), lower) if lower else min(r["started_at"] for r in items)
        end = min(max(r["finished_at"] for r in items), upper)
        span_ms = (end - start).total_seconds() * 1000
        sessions.append({"user_id": user_id, "agent_type": agent_type, "session_id": session_id,
                         "project_name": project_name, "started_at": start.isoformat(), "finished_at": end.isoformat(),
                         "span_ms": span_ms, "gap_ms": max(0, span_ms - stats["active_wall_ms"]), **stats})
    summary["project_count"] = len(groups["projects"])
    measured = {(r["user_id"], r["agent_type"], r["session_id"]) for r in rows}
    summary["session_count"] = len(measured)
    summary["observed_session_count"] = len(measured | set(known_sessions or []))
    summary["unmeasured_session_count"] = len(set(known_sessions or []) - measured)
    histogram = [{"lower_ms": a, "upper_ms": b, "count": 0} for a, b in zip((0, *BUCKETS), (*BUCKETS, None))]
    for row in rows:
        if lower is not None and row["started_at"] < lower or row["finished_at"] > upper:
            continue
        next(bucket for bucket in histogram if bucket["upper_ms"] is None or row["duration_ms"] < bucket["upper_ms"])["count"] += 1
    turns = []
    for row in rows:
        stats = summarize([row], lower, upper)
        turns.append({**{k: row[k] for k in ("user_id", "session_id", "turn_id", "project_name", "agent_type", "model_name", "duration_ms", "time_to_first_token_ms", "timing_source", "tool_status")},
                      "started_at": row["started_at"].isoformat(), "finished_at": row["finished_at"].isoformat(),
                      "in_window_ms": stats["agent_ms"], "breakdown": stats["breakdown"]})
    return {"summary": summary, "histogram": histogram, "projects": projects, "sessions": sessions, "tools": tools, "turns": turns}


SORT_FIELDS = {
    "projects": {"project_name", "session_count", "turn_count", "agent_ms", "active_wall_ms", "parallelism", "duration.p50_ms", "duration.p95_ms"},
    "sessions": {"session_id", "project_name", "agent_type", "turn_count", "agent_ms", "gap_ms", "duration.p50_ms", "duration.p95_ms", "finished_at"},
    "tools": {"tool", "kind", "call_count", "exclusive_ms", "share", "duration.average_ms", "duration.p95_ms"},
    "turns": {"turn_id", "project_name", "session_id", "agent_type", "model_name", "duration_ms", "time_to_first_token_ms", "timing_source", "finished_at"},
}


def paginate(rows, view, *, sort=None, order="desc", page=1, page_size=15):
    default = "duration_ms" if view == "turns" else "exclusive_ms" if view == "tools" else "agent_ms"
    sort = sort if sort in SORT_FIELDS[view] else default
    def value(row):
        result = row
        for part in sort.split("."):
            result = result.get(part) if isinstance(result, dict) else None
        return result
    present = [r for r in rows if value(r) is not None]
    absent = [r for r in rows if value(r) is None]
    ordered = sorted(present, key=value, reverse=order == "desc") + absent
    page_size = max(1, min(100, page_size))
    pages = max(1, math.ceil(len(rows) / page_size))
    page = max(1, min(pages, page))
    return {"rows": ordered[(page - 1) * page_size:page * page_size], "total": len(rows), "page": page,
            "pages": pages, "page_size": page_size, "sort": sort, "order": order}
