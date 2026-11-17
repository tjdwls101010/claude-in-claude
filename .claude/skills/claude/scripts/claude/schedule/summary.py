"""The summary a scheduled run leaves on its GitHub Actions run page and beside the run (K17): a title with the outcome, a table of the run, the trigger and the tree it saw, alerts, the prompt, the worker's answer, then the changes, the activity and how to continue on this Mac (the plan's sample B). Missing parts are left out whole. Pure: everything it shows comes from the run's snapshot and the context the Finish step gathered.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from claude.util import trim_bytes

ANSWER_BYTES = 400_000
PROMPT_BYTES = 50_000
ACTIVITY_ROWS = 300
CHANGE_ROWS = 500
CHANGE_BYTES = 100_000
# Tighter limits, tried in turn when every section at its limit still would not fit the step summary.
FALLBACKS = ({}, {"activity": False}, {"activity": False, "change_rows": 50, "answer": 200_000, "prompt": 20_000}, {"activity": False, "change_rows": 0, "answer": 100_000, "prompt": 10_000})


def _limit(context, key, default):
    return (context.get("_limits") or {}).get(key, default)
EXCERPTS_BYTES = 100_000
TOTAL_BYTES = 900_000
DETAIL_CHARS = 100
EXCERPT_BYTES = 1_200

RED = ("failed", "timed_out", "orphaned")
TOOL_ROWS = ("bash", "read", "edit", "write", "grep", "glob", "fetch", "search", "skill", "agent", "mcp", "tool", "denied", "retry", "compact", "task", "result", "running")
EXPECTED_MODE = {"read-only": "dontAsk", "write": "acceptEdits", "auto": "auto"}


def _local(ts, tz, fmt):
    return datetime.fromtimestamp(ts, ZoneInfo(tz)).strftime(fmt)


def _zone(ts, tz):
    return datetime.fromtimestamp(ts, ZoneInfo(tz)).tzname()


def _epoch(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _duration(seconds):
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {s % 3600 // 60}m"


def _clock(seconds):
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _code(text, table=False):
    """Inline code that survives backticks, and in a table cell its pipes (GitHub drops the backslash there, and shows it anywhere else)."""
    if table:
        text = text.replace("|", "\\|")
    if "`" not in text:
        return f"`{text}`"
    return f"`` {text} ``"


def _cell(text):
    return str(text).replace("|", "\\|")


def _one_line(text, limit=DETAIL_CHARS):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _target(tool, raw):
    """What a call aimed at, from its input as the stream recorded it (JSON, possibly cut short)."""
    try:
        inp = json.loads(raw)
    except (TypeError, ValueError):
        inp = None
    if isinstance(inp, dict):
        for key in ("file_path", "notebook_path", "command", "url", "pattern", "query", "path"):
            if inp.get(key):
                return str(inp[key])
    m = re.search(r'"(?:file_path|command|url|path)":\s*"((?:[^"\\]|\\.)*)', raw or "")
    return m.group(1) if m else (raw or "")


def _fence(text, lang="text", minimum=3):
    longest = max((len(m) for m in re.findall(r"`{3,}", text)), default=0)
    ticks = "`" * max(minimum, longest + 1)
    return f"{ticks}{lang}\n{text.rstrip(chr(10))}\n{ticks}"


def _quote(lines):
    return "\n".join("> " + l if l else ">" for l in lines)


def _cut(text, limit, what, how):
    if len(text.encode("utf-8")) <= limit:
        return text, None
    return trim_bytes(text, limit), f"{what} cut at {_size(limit)} of {_size(len(text.encode('utf-8')))}; {how}"


def _title(snapshot, context):
    outcome = context.get("outcome") or {}
    name = context["name"]
    if snapshot is None:
        kind = outcome.get("kind")
        if kind == "skipped":
            return f"# ⏭ {name} · skipped"
        if kind == "check":
            return f"# 🔎 {name} · check {'passed' if outcome.get('ok') else 'failed'}"
        return f"# ❌ {name} · {outcome.get('title') or 'not started'}"
    state = snapshot["meta"].get("state")
    if state == "completed" and snapshot["schema"] and snapshot["json"] is None:
        return f"# ❌ {name} · completed without structured output"
    icon = {"completed": "✅", "interrupted": "⏹"}.get(state, "❌")
    return f"# {icon} {name} · {state}"


def _trigger_text(context, started, verb="started"):
    trig = context.get("trigger") or {}
    kind = trig.get("kind")
    text = {"dispatcher": "dispatcher", "schedule": "schedule (backup)", "manual": "manual", "re-run": f"re-run (attempt {trig.get('attempt')})"}.get(kind, kind or "?")
    if trig.get("retry_of_url"):
        text = f"{text}, retry of [the run that failed]({trig['retry_of_url']})"
    tz = context["timezone"]
    parts = [text]
    slot = context.get("slot")
    if slot is not None:
        parts.append(f"slot {_local(slot, tz, '%Y-%m-%d %H:%M')} {_zone(slot, tz)}")
    if started:
        same_day = slot is not None and _local(slot, tz, "%Y-%m-%d") == _local(started, tz, "%Y-%m-%d")
        parts.append(f"{verb} {_local(started, tz, '%H:%M:%S' if same_day else '%Y-%m-%d %H:%M:%S')}" + ("" if same_day else f" {_zone(started, tz)}"))
    return " · ".join(parts)


def _tree_text(tree):
    tree = tree or {}
    kind = tree.get("kind")
    if kind == "worktree":
        return f"worktree {_code(tree['path'], True)} on {_code(tree.get('branch') or '?', True)} from {_code((tree.get('base') or '')[:7], True)}, a clean checkout of that commit; your checkout is not touched"
    if kind == "checkout":
        where = f"{_code(tree['branch'], True)}" if tree.get("branch") else "detached HEAD"
        n = tree.get("uncommitted_before")
        state = "clean when the run began" if not n else f"{n} uncommitted file{'s' if n != 1 else ''} when the run began"
        return f"{where} @ {_code((tree.get('head') or '')[:7], True)}, {state} (not the commit GitHub shows for this run)"
    if kind == "none":
        return f"{_code(tree.get('path') or '?', True)}, not a git checkout"
    return "unknown"


def _run_text(snapshot):
    meta, header = snapshot["meta"], snapshot["header"]
    settings = meta.get("settings") or {}
    init = meta.get("init") or {}
    parts = [_code(settings.get("profile") or "?", True), _cell(f"{init.get('model') or settings.get('model')} / {settings.get('effort')}")]
    if meta.get("started_at") and meta.get("ended_at"):
        parts.append(_duration(meta["ended_at"] - meta["started_at"]))
    calls = sum((header.get("tool_calls") or {}).values())
    parts.append(f"{calls} tool call{'s' if calls != 1 else ''}")
    if isinstance(header.get("cost_usd"), (int, float)):
        parts.append(f"${header['cost_usd']:.2f}" if header["cost_usd"] >= 0.005 else "<$0.01")
    return " · ".join(parts)


def _alerts(snapshot, context):
    out = []
    outcome = context.get("outcome") or {}
    caution, warning, note = [], [], []
    if snapshot is None:
        if outcome.get("kind") == "skipped":
            prev = outcome.get("previous") or {}
            link = f"[the earlier run]({prev['url']})" if prev.get("url") else "an earlier run"
            note.append(f"**Skipped: {outcome.get('reason') or 'this slot already ran'}** — {link}{' (' + prev['state'] + ')' if prev.get('state') else ''}. A trigger that comes late for a slot that already ran does nothing.")
        elif outcome.get("kind") == "check":
            if not outcome.get("ok"):
                caution.append("**This runner cannot start a scheduled worker yet.** " + "; ".join(c["detail"] for c in outcome.get("checks") or [] if not c["ok"]))
        else:
            caution.append(f"**{outcome.get('error') or 'No worker was started.'}**")
            if outcome.get("instead"):
                caution.append(outcome["instead"])
    else:
        meta, header = snapshot["meta"], snapshot["header"]
        state = meta.get("state")
        if state in RED:
            caution.append({"failed": "**The run failed.**", "timed_out": "**The run timed out.**", "orphaned": "**The run's supervisor died before recording an outcome.**"}[state] + (f" {_code(_one_line(meta.get('error'), 300))}" if meta.get("error") else ""))
            last = (snapshot.get("text") or "").strip()
            if last:
                caution.append(f"Last message: {_one_line(last, 300)}")
        elif state == "completed" and snapshot["schema"] and snapshot["json"] is None:
            caution.append("**The run ended without structured output**, though it was asked for a JSON answer.")
        elif state == "interrupted":
            if context.get("stopped_by_finish"):
                note.append("**Cancelled.** The worker was stopped; its session can be resumed (see *Continue on your Mac*).")
            else:
                caution.append("**The run was stopped before the job ended** (`stop` on this Mac, or the run's own deadline). Its session can be resumed.")
        denials = header.get("permission_denials") or []
        if denials:
            n = len(denials)
            warning.append(f"**{n} permission denial{'s' if n != 1 else ''}.** The worker tried something its profile does not allow.")
            warning += [f"- {_code(d.get('tool') or '?')} {_code(_one_line(_target(d.get('tool'), d.get('input')), 200))}" for d in denials[:20]]
        if meta.get("mode_mismatch"):
            mode = (meta.get("init") or {}).get("permission_mode")
            profile = (meta.get("settings") or {}).get("profile")
            warning.append(f"**The worker started in `{mode}` mode, not `{EXPECTED_MODE.get(profile)}`** as the `{profile}` profile needs: treat what it could do as unknown.")
        exceptions = header.get("profile_exceptions") or []
        if exceptions:
            warning.append(f"**{len(exceptions)} setting{'s' if len(exceptions) != 1 else ''} in your Claude Code files widen{'s' if len(exceptions) == 1 else ''} the `{(meta.get('settings') or {}).get('profile')}` profile:** " + "; ".join(f"`{e['setting']}` in `{e['file']}`" for e in exceptions[:5]))
        seen = context.get("attention") or []
        if seen:
            warning.append("**It needed attention while it ran**, which nobody could give: " + "; ".join(f"{a.get('reason')} at {a.get('at')}" for a in seen[:10]))
    for w in context.get("warnings") or []:
        warning.append(w)
    if caution:
        out.append("> [!CAUTION]\n" + _quote(caution))
    if warning:
        out.append("> [!WARNING]\n" + _quote(warning))
    if note:
        out.append("> [!NOTE]\n" + _quote(note))
    return out


def _details(summary, body, open_=False):
    return f"<details{' open' if open_ else ''}><summary>{summary}</summary>\n\n{body}\n\n</details>"


def _prompt(context, cuts):
    text = context.get("prompt")
    if not text:
        return None
    text, cut = _cut(text, _limit(context, "prompt", PROMPT_BYTES), "The prompt", "the workflow file holds it whole")
    if cut:
        cuts.append(cut)
    return _details("<b>Prompt</b>", _fence(text, "text", minimum=4))


def _answer(snapshot, context, cuts):
    if snapshot["schema"]:
        if snapshot["json"] is None:
            return None
        text, cut = _cut(json.dumps(snapshot["json"], indent=2, ensure_ascii=False), _limit(context, "answer", ANSWER_BYTES), "The answer", f"`{context['log_call'].replace(' log ', ' result ')}` prints it whole")
        if cut:
            cuts.append(cut)
        return _fence(text, "json")
    text = (snapshot.get("text") or "").strip("\n")
    if not text:
        return None
    text, cut = _cut(text, _limit(context, "answer", ANSWER_BYTES), "The answer", f"`{context['log_call'].replace(' log ', ' result ')}` prints it whole")
    if cut:
        cuts.append(cut)
    return text


def _changes(snapshot, context):
    ch = context.get("changes")
    profile = (snapshot["meta"].get("settings") or {}).get("profile")
    if ch is None or profile == "read-only":
        return None
    files = ch.get("files") or []
    lines = []
    shown = files[: _limit(context, "change_rows", CHANGE_ROWS)]
    width = min(max((len(f["path"]) for f in shown), default=0), 80)
    used = 0
    for n, f in enumerate(shown):
        if used > CHANGE_BYTES:
            shown = shown[:n]
            break
        if f.get("note"):
            what = f"({f['note']})"
        elif f.get("new_lines") is not None:
            what = f"(new, {f['new_lines']} line{'s' if f['new_lines'] != 1 else ''})"
        elif f.get("lines"):
            what = f"+{f['lines'][0]} −{f['lines'][1]}"
        elif f["status"].strip() == "D":
            what = "(deleted)"
        else:
            what = ""
        if f.get("committed") and "committed" not in what:
            what = (what + " committed").strip()
        lines.append(f"{f['status'].ljust(2)} {f['path'].ljust(width)}  {what}".rstrip())
        used += len(lines[-1].encode("utf-8"))
    where = ch.get("where") or "the project checkout"
    committed = sum(1 for f in files if f.get("committed"))
    pending = sum(1 for f in files if not f.get("committed") or f.get("uncommitted_too"))
    state = "" if not files else (", uncommitted" if not committed else (", committed" if not pending else f", {committed} committed, {pending} with uncommitted changes"))
    head = f"<b>Changes</b> · {len(files)} file{'s' if len(files) != 1 else ''} changed during the run in {where}{state}"
    if len(files) > len(shown):
        lines.append(f"… and {len(files) - len(shown)} more")
    body = [_fence("\n".join(lines), "text")] if lines else ["Nothing changed."]
    moved = ch.get("head_moved")
    if moved:
        body.append(f"HEAD moved during the run: {_code(moved['from'])} → {_code(moved['to'])}" + (f", {moved['commits']} commit{'s' if moved['commits'] != 1 else ''}." if moved["commits"] else ", no new commit."))
    if ch.get("not_git"):
        edited, listed, used = ch["not_git"], [], 0
        for path in edited[: _limit(context, "change_rows", CHANGE_ROWS)]:
            if used > CHANGE_BYTES:
                break
            listed.append(f"- {_code(path)}")
            used += len(listed[-1].encode("utf-8"))
        if len(edited) > len(listed):
            listed.append(f"- … and {len(edited) - len(listed)} more")
        body = ["Not a git checkout, so only what the edit tools wrote is known; files a shell command wrote are not here:", "\n".join(listed) or "- none"]
    if ch.get("kept"):
        k = ch["kept"]
        body.append(f"The worktree is kept because it holds these changes: {_code(k['path'])} on branch {_code(k['branch'])}. Move what you need into your tree, then `{k['clean']}`.")
    elif ch.get("branch_kept"):
        b = ch["branch_kept"]
        body.append(f"The worktree was removed; its branch {_code(b['branch'])} keeps the commits (`git log {b['branch']}`).")
    elif ch.get("removed"):
        body.append("The worktree had nothing to keep and was removed.")
    if not ch.get("not_git") and ch.get("kind") != "worktree":
        body.append("What another process changed in this checkout at the same time shows here too.")
    return _details(head, "\n\n".join(body), open_=True)


def _result_cell(row):
    k = row["kind"]
    if k == "bash":
        return f"exit {'?' if row['exit'] is None else row['exit']} · {_size(row['bytes'])}"
    if k == "denied":
        return "not allowed"
    if k == "agent":
        return f"{row['tools']} tools · {_size(row['bytes'])}"
    if k == "result":
        return f"${row['cost_usd']:.4f}" if isinstance(row.get("cost_usd"), (int, float)) else ""
    if k == "running":
        return "no result"
    return "error" if row.get("error") else ""


def _step_cell(row):
    return {"denied": "🚫 denied", "running": "running"}.get(row["kind"], row["kind"])


def _detail_cell(row):
    k = row["kind"]
    if k == "denied":
        return f"{_code(row['tool'] or '?', True)} {_code(_one_line(_target(row['tool'], row['input'])), True)}"
    if k == "mcp":
        return _code(f"{row['server']}/{row['name']}", True)
    if k == "tool":
        return f"{_code(row['tool'] or '?', True)} {_code(_one_line(row['detail']), True)}"
    if k == "retry":
        return _cell(f"attempt {row['attempt']}/{row['max_retries']} · {_one_line(row['error'])} {row['error_status'] or ''}".rstrip())
    if k == "task":
        return _cell(f"{row['status']} {_one_line(row['description'])}")
    if k == "result":
        return f"{row['subtype']} · {row['num_turns']} turns"
    if k == "compact":
        return "the conversation was compacted"
    return _code(_one_line(row.get("detail") or ""), True)


def _activity(snapshot, context, cuts):
    rows = snapshot["rows"]
    started = snapshot["meta"].get("started_at") or snapshot["meta"].get("created_at")
    ended = snapshot["meta"].get("ended_at")
    table = [r for r in rows if r["kind"] in TOOL_ROWS]
    if not table:
        return None
    lines = ["| # | Time | Step | Detail | Result |", "|--:|--:|:--|:--|:--|"]
    numbered = {}
    for n, r in enumerate(table, 1):
        numbered[id(r)] = n
        if n > ACTIVITY_ROWS:
            continue
        at = _epoch(r.get("time"))
        if at is None and r["kind"] == "result" and r is table[-1] and ended:
            at = ended
        cells = [str(n), _clock(at - started) if at is not None and started else "", _step_cell(r), _detail_cell(r), _result_cell(r)]
        lines.append("|" + "|".join(f" {c} " if c else " " for c in cells) + "|")
    if len(table) > ACTIVITY_ROWS:
        cuts.append(f"The activity shows {ACTIVITY_ROWS} of {len(table)} rows; `{context['log_call']}` prints all of it")
    below = []
    budget = EXCERPTS_BYTES
    for r in table[:ACTIVITY_ROWS]:
        if r["kind"] == "bash" and r["exit"] not in (0, None) and r["output"].strip() and budget > 0:
            out = r["output"]
            data = out.encode("utf-8")
            if len(data) > 2 * EXCERPT_BYTES:
                out = trim_bytes(out, EXCERPT_BYTES) + "\n…\n" + data[-EXCERPT_BYTES:].decode("utf-8", "ignore")
            block = f"**#{numbered[id(r)]}** exited {r['exit']}:\n\n{_fence(trim_bytes(out, max(0, budget - 200)))}"
            budget -= len(block.encode("utf-8"))
            below.append(block)
    final = (snapshot.get("text") or "").strip()
    last_n = 0
    for r in rows:
        if id(r) in numbered:
            last_n = numbered[id(r)]
        elif r["kind"] == "msg" and r["text"].strip() != final and budget > 0:
            text = r["text"].strip()
            if len(text.encode("utf-8")) > budget:
                text = trim_bytes(text, max(0, budget - 200)) + " …"
                cuts.append(f"A message from the worker was cut; `{context['log_call']}` prints all of them")
            block = f"**After #{last_n}:** {text}" if last_n else f"**Before the first call:** {text}"
            budget -= len(block.encode("utf-8"))
            below.append(block)
    init = next((r for r in rows if r["kind"] == "init"), None)
    limits = next((r for r in rows if r["kind"] == "ratelimit"), None)
    foot = []
    if init:
        foot.append(f"Started as {init['model']} in `{init['mode']}` mode")
    if limits:
        pct = [f"{label} {round(v * 100)}%" for label, v in (("5h", limits.get("five_hour")), ("7d", limits.get("seven_day"))) if isinstance(v, (int, float))]
        if pct:
            foot.append("usage limits at start: " + ", ".join(pct))
    body = "\n".join(lines)
    if below:
        body += "\n\n" + "\n\n".join(below)
    if foot:
        body += "\n\n" + " · ".join(foot)
    calls = sum(1 for r in table if r["kind"] not in ("result", "retry", "compact", "task"))
    return _details(f"<b>Activity</b> · {calls} tool call{'s' if calls != 1 else ''}", body)


def _continue(snapshot, context):
    meta = snapshot["meta"]
    c = context["continue"]
    cwd = (meta.get("init") or {}).get("cwd") or meta.get("cwd")
    code = "\n".join([
        "# ask the same session a follow-up (it remembers this run)",
        f'uv run "{c["cli"]}" resume {meta["run_id"]} "…" --project "{c["project"]}"',
        "# or open the session yourself",
        f'cd "{cwd}" && claude --resume {meta.get("session_id")}',
    ])
    return _details("<b>Continue on your Mac</b>", f"{_fence(code, 'bash')}\n\nRun `{meta['run_id']}` · full record in `{c['run_dir']}`")


def _table(rows):
    return "\n".join(["| | |", "|:--|:--|"] + [f"| **{k}** | {v} |" for k, v in rows])


def render_summary(snapshot, context):
    """The summary's markdown (see `_render`), within GitHub's step summary limit: when every section at its own limit would still be too much, the activity goes, then the change list and the answer shrink, before anything is cut blindly."""
    for limits in FALLBACKS:
        text = _render(snapshot, {**context, "_limits": limits})
        if len(text.encode("utf-8")) <= TOTAL_BYTES:
            return text
    return trim_bytes(text, TOTAL_BYTES) + "\n\n…cut to fit GitHub's step summary limit\n"


def _render(snapshot, context):
    """The summary's markdown. `snapshot` is `observe.snapshot` of the run, or None when the job started no worker (skipped, a check, a refusal); `context` carries what the run cannot know: `name`, `timezone`, `trigger` ({kind, attempt, retry_of_url}), `slot`, `prompt`, `tree` (what the worker saw), `changes`, `attention` seen while it ran, `warnings` from the Finish step, `stopped_by_finish`, `outcome` (for no worker: {kind: skipped|check|refused|missing, …}), `continue` ({cli, project, run_dir}) and `log_call`."""
    cuts = []
    parts = [_title(snapshot, context)]
    started = (snapshot["meta"].get("started_at") or snapshot["meta"].get("created_at")) if snapshot else context.get("at")
    rows = []
    if snapshot:
        rows.append(("Run", _run_text(snapshot)))
    if context.get("trigger"):
        rows.append(("Trigger", _trigger_text(context, started, "started" if snapshot else "at")))
    if context.get("tree"):
        rows.append(("Local tree", _tree_text(context["tree"])))
    outcome = context.get("outcome") or {}
    if snapshot is None and outcome.get("kind") == "check":
        rows += [(c["name"], ("✅ " if c["ok"] else "❌ ") + c["detail"]) for c in outcome.get("checks") or []]
    if rows:
        parts.append(_table(rows))
    parts += _alerts(snapshot, context)
    prompt = _prompt(context, cuts)
    if prompt:
        parts.append(prompt)
    if snapshot:
        answer = _answer(snapshot, context, cuts)
        if answer:
            parts.append(answer)
        tail = [x for x in (_changes(snapshot, context), _activity(snapshot, context, cuts) if _limit(context, "activity", True) else None, _continue(snapshot, context)) if x]
        if tail:
            parts.append("---")
            parts += tail
    if snapshot and not _limit(context, "activity", True):
        cuts.append(f"The activity was left out to fit GitHub's step summary limit; `{context.get('log_call')}` prints it")
    if cuts:
        parts.append("> [!NOTE]\n" + _quote(cuts))
    return "\n\n".join(parts) + "\n"
