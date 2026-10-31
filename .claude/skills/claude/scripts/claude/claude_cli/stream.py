"""Claude Code's stream-json, both ways: the user message the supervisor writes to stdin, and everything read back from stdout — a run's summary, its log lines, and which result answers it.

Every field name of the stream lives here; the rest of the skill sees the dictionaries these functions return.
"""

from __future__ import annotations

import json
import os
import re

from claude.util import trim_bytes

EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
AGENT_TOOLS = ("Agent", "Task")
FOLLOWUP_ORIGIN = "task-notification"
EXIT_LINE = re.compile(r"^(?:Error: )?Exit code (-?\d+)\n?")
APPROVAL = "What required approval: "
FAIL_OUTPUT_BYTES = 1200


def encode_user_message(text, uuid, priority=None):
    """One stdin line for `--input-format stream-json`. `priority` is `next` (read once the running tools finish) or `now` (interrupts the turn); None leaves Claude Code's default."""
    msg = {"type": "user", "message": {"role": "user", "content": text}, "parent_tool_use_id": None, "uuid": uuid}
    if priority:
        msg["priority"] = priority
    return json.dumps(msg, ensure_ascii=False) + "\n"


def read_events(path):
    """The parsed lines of an events file and how many lines were not JSON objects. A missing file is no events."""
    events, unparsed = [], 0
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return [], 0
    with f:
        for line in f:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                unparsed += 1
                continue
            if isinstance(e, dict):
                events.append(e)
            else:
                unparsed += 1
    return events, unparsed


def _text_blocks(content):
    if isinstance(content, str):
        return [content]
    return [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]


def _result_text(content):
    if isinstance(content, str):
        return content
    return "\n".join(_text_blocks(content))


def _tool_summary(name, inp, rel_to=None):
    inp = inp if isinstance(inp, dict) else {}

    def rel(p):
        if rel_to and isinstance(p, str) and (p == rel_to or p.startswith(rel_to.rstrip("/") + "/")):
            return os.path.relpath(p, rel_to)
        return p

    if name == "Bash":
        return str(inp.get("command", "")).replace("\n", "\\n")[:300]
    if name in EDIT_TOOLS or name == "Read":
        return rel(inp.get("file_path") or inp.get("notebook_path") or "")
    if name in ("Grep", "Glob"):
        return str(inp.get("pattern", ""))
    if name == "WebFetch":
        return str(inp.get("url", ""))
    if name == "WebSearch":
        return str(inp.get("query", ""))
    if name == "Skill":
        return str(inp.get("skill") or inp.get("name") or "")
    if name in AGENT_TOOLS:
        return f"{inp.get('subagent_type', 'agent')} {inp.get('description', '')}".strip()
    return json.dumps(inp, ensure_ascii=False)[:120]


def _bash_output(tool_result, use_result):
    """(exit code or None, output text) of a Bash call. The exit code is only in the result text, as a leading `Exit code N` line."""
    is_error = bool(tool_result.get("is_error"))
    text = _result_text(tool_result.get("content"))
    if not is_error:
        if isinstance(use_result, dict) and ("stdout" in use_result or "stderr" in use_result):
            return 0, (use_result.get("stdout") or "") + (use_result.get("stderr") or "")
        return 0, "" if text.startswith("(Bash completed with no output)") else text
    m = EXIT_LINE.match(text)
    if m:
        return int(m.group(1)), text[m.end():]
    return None, text


def _result_info(e, index):
    origin = e.get("origin") if isinstance(e.get("origin"), dict) else {}
    return {
        "index": index,
        "subtype": e.get("subtype"),
        "is_error": bool(e.get("is_error")),
        "terminal_reason": e.get("terminal_reason"),
        "num_turns": e.get("num_turns"),
        # None when the field is absent, which says the result does not report which message it answered.
        "uuids": list(e["user_message_uuids"]) if isinstance(e.get("user_message_uuids"), list) else ([e["user_message_uuid"]] if e.get("user_message_uuid") else None),
        "origin": origin.get("kind"),
        "text": e.get("result") if isinstance(e.get("result"), str) else "",
        "structured_output": e.get("structured_output"),
        "local_command": e.get("local_command"),
        "cost_usd": e.get("total_cost_usd"),
        "usage": e.get("usage") if isinstance(e.get("usage"), dict) else {},
        "errors": e.get("errors") if isinstance(e.get("errors"), list) else [],
        "api_error_status": e.get("api_error_status"),
        "startup_failure_reason": e.get("startup_failure_reason"),
        "permission_denials": e.get("permission_denials") if isinstance(e.get("permission_denials"), list) else [],
        "duration_ms": e.get("duration_ms"),
        "after_init": False,
        "assistant_in_turn": False,
    }


class StreamState:
    """A run's stdout read event by event: what the supervisor decides on while the run is live and what a row shows afterwards."""

    def __init__(self):
        self.count = 0
        self.unparsed = 0
        self.init = None
        self.last_init = None
        self.inits = 0
        self.results = []
        self.blocked = []
        self.uses = {}  # tool_use_id -> (name, input, parent, index)
        self.done = set()
        self.subagent_tools = {}  # parent tool_use_id -> count
        self.files_edited = []
        self.tool_calls = {}
        self.denials = []
        self._denied_ids = set()
        self.rate_limit = None
        self.retry = None
        self.last_event_is_retry = False
        self.tasks = {}
        self.last_message = None
        self.hooks_open = set()
        self.compactions = 0
        self.assistant_in_turn = False
        self.pending_info = []  # informational events not yet tied to a uuid: (index, reason, kind)
        self.last_command_uuid = None
        self.lines = []  # (index, kind, payload) for log rendering

    def feed(self, e):
        i = self.count
        self.count += 1
        t, st = e.get("type"), e.get("subtype")
        self.last_event_is_retry = t == "system" and st == "api_retry"
        if t == "system" and st == "init":
            info = {"permission_mode": e.get("permissionMode"), "model": e.get("model"), "cwd": e.get("cwd"), "claude_code_version": e.get("claude_code_version"), "session_id": e.get("session_id")}
            if self.init is None:
                self.init = info
            prev = self.last_init
            self.last_init = info
            self.inits += 1
            if prev is None or (prev["model"], prev["permission_mode"]) != (info["model"], info["permission_mode"]):
                self.lines.append((i, "init", info))
        elif t == "system" and st == "hook_started":
            self.hooks_open.add(e.get("hook_id"))
        elif t == "system" and st == "hook_response":
            self.hooks_open.discard(e.get("hook_id"))
        elif t == "system" and st == "api_retry":
            self.retry = {k: e.get(k) for k in ("attempt", "max_retries", "retry_delay_ms", "error_status", "error")}
            self.lines.append((i, "retry", self.retry))
        elif t == "system" and st == "permission_denied":
            self._deny(e.get("tool_name"), e.get("tool_use_id"), self._denied_input(e), i)
        elif t == "system" and st == "informational" and isinstance(e.get("prompt_submit_outcome"), dict):
            outcome = e["prompt_submit_outcome"]
            self.pending_info.append({"index": i, "reason": outcome.get("reason") or e.get("content"), "kind": outcome.get("kind"), "uuid_before": self.last_command_uuid, "assistant_after": False})
        elif t == "system" and st == "compact_boundary":
            self.compactions += 1
            self.lines.append((i, "compact", None))
        elif t == "system" and st == "task_started":
            self.tasks[e.get("task_id")] = {"task_id": e.get("task_id"), "description": e.get("description"), "task_type": e.get("task_type"), "backgrounded": bool(e.get("is_backgrounded")), "open": True}
            if e.get("is_backgrounded") or e.get("task_type") not in ("local_bash", "local_agent"):
                self.lines.append((i, "task", ("started", e.get("description"))))
        elif t == "system" and st in ("task_notification", "task_updated"):
            task = self.tasks.get(e.get("task_id"))
            status = e.get("status") or (e.get("patch") or {}).get("status")
            if task and status in ("completed", "failed", "stopped", "killed"):
                if task["open"] and (task["backgrounded"] or task["task_type"] not in ("local_bash", "local_agent")):
                    self.lines.append((i, "task", (status, task["description"])))
                task["open"] = False
        elif t == "command_lifecycle":
            self.last_command_uuid = e.get("command_uuid")
        elif t == "rate_limit_event":
            info = e.get("rate_limit_info") or {}
            windows = info.get("unifiedWindows") or {}
            rl = {"status": info.get("status"), "five_hour": (windows.get("five_hour") or {}).get("utilization"), "seven_day": (windows.get("seven_day") or {}).get("utilization"), "resets_at": info.get("resetsAt"), "type": info.get("rateLimitType")}
            if self.rate_limit is None or self.rate_limit["status"] != rl["status"]:
                self.lines.append((i, "ratelimit", rl))
            self.rate_limit = rl
        elif t == "assistant":
            parent = e.get("parent_tool_use_id")
            for b in (e.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    self.uses[b.get("id")] = (b.get("name"), b.get("input"), parent, i)
                    if parent:
                        self.subagent_tools[parent] = self.subagent_tools.get(parent, 0) + 1
                    else:
                        self.tool_calls[b.get("name")] = self.tool_calls.get(b.get("name"), 0) + 1
                elif b.get("type") == "text" and not parent and b.get("text", "").strip():
                    self.last_message = b["text"]
                    self.lines.append((i, "msg", b["text"]))
            if not parent:
                self.assistant_in_turn = True
                for info in self.pending_info:
                    info["assistant_after"] = True
        elif t == "user":
            content = (e.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        self._tool_result(b, e, i)
        elif t == "result":
            r = _result_info(e, i)
            r["after_init"] = self.init is not None
            r["assistant_in_turn"] = self.assistant_in_turn
            self._tie_blocked(r)
            for d in r["permission_denials"]:
                self._deny(d.get("tool_name"), d.get("tool_use_id"), json.dumps(d.get("tool_input"), ensure_ascii=False)[:120] if d.get("tool_input") is not None else "", i)
            self.results.append(r)
            self.assistant_in_turn = False
            self.lines.append((i, "result", r))

    def _denied_input(self, e):
        use = self.uses.get(e.get("tool_use_id"))
        if use:
            return json.dumps(use[1], ensure_ascii=False)[:120]
        message = e.get("message") or ""
        return message.split(APPROVAL, 1)[1][:120] if APPROVAL in message else (e.get("decision_reason") or "")[:120]

    def _deny(self, tool, tool_use_id, inp, index):
        if tool_use_id in self._denied_ids:
            return
        self._denied_ids.add(tool_use_id)
        self.denials.append({"tool": tool, "input": inp, "tool_use_id": tool_use_id})
        self.lines.append((index, "denied", (tool, inp)))

    def _tie_blocked(self, r):
        """Tie hook-ended messages to uuids: a hook-ended message that opened its own turn gets a `num_turns: 0` result naming it; one that arrived during a turn is the command just before the notice."""
        if not self.pending_info:
            return
        hook_ended = r["num_turns"] == 0 and not r["assistant_in_turn"]
        for info in self.pending_info:
            if hook_ended and not info["assistant_after"] and r["uuids"]:
                uuids = r["uuids"]
                r["hook_ended"] = True
            else:
                uuids = [info["uuid_before"]] if info["uuid_before"] else [None]
            for u in uuids:
                self.blocked.append({"uuid": u, "reason": info["reason"], "kind": info["kind"], "index": info["index"]})
        self.pending_info = []

    def _tool_result(self, b, e, i):
        tid = b.get("tool_use_id")
        self.done.add(tid)
        name, inp, parent, _ = self.uses.get(tid, (None, None, None, None))
        if parent or name is None:
            return
        is_error = bool(b.get("is_error"))
        if tid in self._denied_ids or self._rejected(e, tid):
            return
        use_result = e.get("tool_use_result")
        if name == "Bash":
            code, out = _bash_output(b, use_result)
            self.lines.append((i, "bash", (code, out, _tool_summary(name, inp))))
            return
        if name in EDIT_TOOLS and not is_error:
            path = (inp or {}).get("file_path") or (inp or {}).get("notebook_path")
            if path and path not in self.files_edited:
                self.files_edited.append(path)
        self.lines.append((i, "tool", (name, inp, is_error, _result_text(b.get("content")), tid)))

    @staticmethod
    def _rejected(e, tid):
        for meta in e.get("tool_result_meta") or []:
            if isinstance(meta, dict) and meta.get("id") == tid and (meta.get("permission_decision") or {}).get("decision") == "reject":
                return True
        return False

    def in_progress(self):
        return [{"tool": name, "summary": _tool_summary(name, inp), "tool_use_id": tid} for tid, (name, inp, parent, _) in self.uses.items() if tid not in self.done and not parent]

    def summary(self):
        usage = {}
        for r in self.results:
            for k, v in (r["usage"] or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    usage[k] = usage.get(k, 0) + v
        costs = [r["cost_usd"] for r in self.results if isinstance(r["cost_usd"], (int, float))]
        return {
            "events": self.count,
            "init": self.init,
            "last_init": self.last_init,
            "inits": self.inits,
            "results": self.results,
            "blocked": self.blocked,
            "in_progress": self.in_progress(),
            "denials": [{"tool": d["tool"], "input": d["input"]} for d in self.denials],
            "files_edited": list(self.files_edited),
            "tool_calls": dict(self.tool_calls),
            "rate_limit": self.rate_limit,
            "retry": self.retry,
            "last_event_is_retry": self.last_event_is_retry,
            "tasks_open": [{k: t[k] for k in ("task_id", "description", "task_type")} for t in self.tasks.values() if t["open"]],
            "last_message": self.last_message,
            "open_hooks": len(self.hooks_open),
            "compactions": self.compactions,
            # total_cost_usd is cumulative within one process, so the run's cost is the last result's.
            "cost_usd": costs[-1] if costs else None,
            "usage": usage,
        }


def summarize(events):
    """What a run's events add up to: init, results, hook-ended messages, calls in progress, denials, files edited, tool counts, the latest rate limit and retry, open tasks and hooks, the last message, cost and usage."""
    state = StreamState()
    for e in events:
        state.feed(e)
    return state.summary()


def answered_uuids(events):
    """Every message uuid some result reports having answered."""
    out = set()
    for r in summarize(events)["results"]:
        out |= set(r["uuids"] or [])
    return out


def _pct(x):
    return f"{round(x * 100)}%" if isinstance(x, (int, float)) else "?"


def _cost(x):
    return f"${x:.4f}" if isinstance(x, (int, float)) else "$?"


def _indent(text):
    return ["    " + l if l.strip() else "" for l in text.splitlines()]


def _fail_excerpt(out):
    data = out.encode("utf-8", "replace")
    if len(data) <= 2 * FAIL_OUTPUT_BYTES:
        return out
    return trim_bytes(out, FAIL_OUTPUT_BYTES) + "\n…\n" + data[-FAIL_OUTPUT_BYTES:].decode("utf-8", "ignore")


def log_lines(events, rel_to=None, messages=()):
    """The run as text, one line per event that matters: init, messages whole, tool calls in one line each (a failed command's output indented beneath), denials, sent messages, tasks, retries, rate-limit changes, compactions and results, ending with calls still running."""
    state = StreamState()
    for e in events:
        state.feed(e)
    sent = sorted((m for m in messages if m.get("kind") == "send" and m.get("after_line") is not None), key=lambda m: m["after_line"])
    out = []
    si = 0

    def flush_sent(upto):
        nonlocal si
        while si < len(sent) and sent[si]["after_line"] <= upto:
            m = sent[si]
            out.append(f"sent {m.get('priority') or 'next'} {(m.get('head') or '')[:120]}")
            si += 1

    for index, kind, payload in state.lines:
        flush_sent(index)
        if kind == "init":
            out.append(f"init model={payload['model']} mode={payload['permission_mode']} cwd={payload['cwd']}")
        elif kind == "msg":
            first, *rest = payload.strip("\n").split("\n")
            out.append(f"msg {first}")
            out += ["    " + l if l.strip() else "" for l in rest]
        elif kind == "bash":
            code, text, cmd = payload
            nbytes = len(text.encode("utf-8", "replace"))
            out.append(f"bash exit={'?' if code is None else code} out={nbytes}B {cmd}")
            if code != 0 and text.strip():
                out += _indent(_fail_excerpt(text))
        elif kind == "tool":
            name, inp, is_error, text, tid = payload
            summary = _tool_summary(name, inp, rel_to)
            err = " error" if is_error else ""
            if name == "Edit" or name == "NotebookEdit":
                out.append(f"edit {summary}{err}")
            elif name == "Write":
                out.append(f"write {summary}{err}")
            elif name == "Read":
                out.append(f"read {summary}{err}")
            elif name in ("Grep", "Glob"):
                out.append(f"{name.lower()} {summary}{err}")
            elif name == "WebFetch":
                out.append(f"fetch {summary}{err}")
            elif name == "WebSearch":
                out.append(f"search {summary}{err}")
            elif name == "Skill":
                out.append(f"skill {summary}{err}")
            elif name in AGENT_TOOLS:
                out.append(f"agent {summary} tools={state.subagent_tools.get(tid, 0)} out={len(text.encode('utf-8', 'replace'))}B{err}")
            elif name and name.startswith("mcp__"):
                parts = name.split("__")
                out.append(f"mcp {parts[1] if len(parts) > 1 else '?'}/{'__'.join(parts[2:]) or '?'} {'error' if is_error else 'ok'}")
            else:
                out.append(f"tool {name} {summary}{err}")
        elif kind == "denied":
            tool, inp = payload
            out.append(f"denied {tool} {inp}".rstrip())
        elif kind == "task":
            status, desc = payload
            out.append(f"task {status} {desc or ''}".rstrip())
        elif kind == "retry":
            out.append(f"retry attempt={payload.get('attempt')}/{payload.get('max_retries')} error={payload.get('error')} status={payload.get('error_status')}")
        elif kind == "ratelimit":
            out.append(f"ratelimit {payload['status']} 5h={_pct(payload['five_hour'])} 7d={_pct(payload['seven_day'])}")
        elif kind == "compact":
            out.append("compact")
        elif kind == "result":
            line = f"result {payload['subtype']} turns={payload['num_turns']} terminal={payload['terminal_reason'] or '-'} cost={_cost(payload['cost_usd'])}"
            if payload["origin"] == FOLLOWUP_ORIGIN:
                line += f" origin={FOLLOWUP_ORIGIN}"
            out.append(line)
    flush_sent(float("inf"))
    for p in state.in_progress():
        out.append(f"running {p['tool']} {p['summary']}".rstrip())
    return out


def _head(m):
    return {"uuid": m.get("uuid"), "head": (m.get("head") or "")[:80]}


def final_result(events, messages):
    """Which result answers the run (J1b), given the messages delivered to it in order, each with the `after_line` it was written at.

    The answer is the last result after the last delivered message that is neither a background follow-up nor one a hook ended; when nothing came after it, the last such result before it. A hook that ended the last message keeps the earlier answer and says so; with no earlier answer the run failed. An error result before any init is a startup failure, not an answer."""
    s = summarize(events)
    results = s["results"]
    delivered = [m for m in messages if m.get("after_line") is not None]
    blocked_ids = {b["uuid"] for b in s["blocked"] if b["uuid"]}
    seen = set()
    for r in results:
        seen |= set(r["uuids"] or [])
    out = {
        "result": None,
        "answered": None,
        "answer_unconfirmed": False,
        "unanswered": [_head(m) for m in delivered if m.get("uuid") and m["uuid"] not in seen and m["uuid"] not in blocked_ids],
        "last_message_unanswered": False,
        "blocked_by_hook": [{"uuid": b["uuid"], "reason": b["reason"]} for b in s["blocked"]],
        "last_message_blocked": False,
        "possibly_blocked": [],
        "followups": sum(1 for r in results if r["origin"] == FOLLOWUP_ORIGIN),
        "error": None,
    }
    startup = [r for r in results if not r["after_init"] and (r["is_error"] or r["subtype"] != "success")]
    if startup and not any(r["after_init"] for r in results):
        r = startup[-1]
        reason = r["startup_failure_reason"]
        detail = "; ".join(str(x) for x in r["errors"]) or r["text"] or r["subtype"]
        out["error"] = f"{reason}: {detail}" if reason else detail
        return out
    real = [r for r in results if r["origin"] != FOLLOWUP_ORIGIN and not r.get("hook_ended")]
    for r in real:
        if r["num_turns"] == 0 and r["subtype"] == "success" and not r["local_command"] and not r["assistant_in_turn"]:
            out["possibly_blocked"] += [u for u in (r["uuids"] or []) if u]
    last = delivered[-1] if delivered else None
    if last and last.get("uuid") and last["uuid"] in blocked_ids:
        out["last_message_blocked"] = True
        if not real:
            out["error"] = "blocked_by_hook"
            return out
        chosen = real[-1]
    else:
        after = [r for r in real if last is None or r["index"] >= last["after_line"]]
        chosen = after[-1] if after else (real[-1] if real else None)
        if last and last.get("uuid") and last["uuid"] not in seen:
            out["last_message_unanswered"] = True
    if chosen is None:
        return out
    out["result"] = chosen
    if chosen["uuids"] is None:
        out["answer_unconfirmed"] = True
    else:
        ids = set(chosen["uuids"])
        out["answered"] = [_head(m) for m in delivered if m.get("uuid") in ids]
    return out
