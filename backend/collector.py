"""Read-only rollout collector. Also runs over SSH, without remote installation."""
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import time

VERSION = 6
HEAD_BYTES = 196608
TAIL_BYTES = 1572864


def redact(text):
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----", "[PRIVATE KEY REDACTED]", str(text))
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b", "[TOKEN REDACTED]", text)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(\b(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|bearer_token)\b[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}]+", r"\1[REDACTED]", text)
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    return text


def clean_user(text):
    for tag in ("environment_context", "external_codex_apps_open_page", "permissions_instructions", "recommended_plugins"):
        text = re.sub(r"<" + tag + r">[\s\S]*?</" + tag + r">", "", text)
    # Injected repository instructions are a user-role setup message, not the
    # user's work goal. Keep any actual request following that block.
    text = re.sub(r"(?:^|\n)# AGENTS\.md instructions[^\n]*\s*<INSTRUCTIONS>[\s\S]*?</INSTRUCTIONS>", "", text)
    return text.strip()


def timestamp(value, fallback=0):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return fallback


def read_registry(root):
    titles = {}
    archive_states = {}
    # A URI opened with mode=ro never changes the Codex database.
    for p in sorted(root.glob("state*.sqlite"), reverse=True):
        try:
            with sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=1) as db:
                cols = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
                if {"id", "title"} <= cols:
                    titles.update(dict(db.execute("SELECT id,title FROM threads")))
                    if "archived" in cols:
                        archive_states.update({r[0]: bool(r[1]) for r in db.execute("SELECT id,archived FROM threads") if r[1] in (0,1)})
                    break
        except sqlite3.Error:
            continue
    index = root / "session_index.jsonl"
    if index.exists():
        try:
            for line in index.open():
                try:
                    item = json.loads(line)
                    name = item.get("thread_name") or item.get("title")
                    if name:
                        titles[item.get("id", "")] = name
                except (ValueError, AttributeError):
                    pass
        except OSError:
            pass
    return titles, archive_states


def read_titles(root):
    return read_registry(root)[0]


def path_thread_id(path):
    match = re.search(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$", path.name, re.I)
    if match:
        return match.group(1)
    try:
        with path.open("rb") as stream:
            row = json.loads(stream.readline(HEAD_BYTES))
        if row.get("type") == "session_meta":
            return (row.get("payload") or {}).get("id")
    except (OSError, ValueError, AttributeError):
        pass
    return None


def parse_rollout(path, host, titles=None):
    stat = path.stat()
    with path.open("rb") as f:
        head = f.read(HEAD_BYTES)
        if HEAD_BYTES < stat.st_size <= HEAD_BYTES + TAIL_BYTES:
            f.seek(0)
            raw = f.read()
        elif stat.st_size > HEAD_BYTES + TAIL_BYTES:
            f.seek(stat.st_size - TAIL_BYTES)
            offset = f.tell()
            tail = f.read()
            tail = tail.split(b"\n", 1)[-1]
            raw = head.rsplit(b"\n", 1)[0] + b"\n" + tail
        else:
            raw = head
    metadata = None
    messages = []
    fallback = []
    tools = collections.deque(maxlen=8)
    seen = set()
    active = False
    last_event = 0
    malformed = 0
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            malformed += 1
            continue
        payload = item.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        typ = item.get("type")
        stamp = timestamp(item.get("timestamp"), stat.st_mtime)
        if typ == "session_meta":
            metadata = payload
        elif typ == "response_item":
            role = payload.get("role")
            if payload.get("type") == "message" and role in ("user", "assistant"):
                content = payload.get("content", [])
                text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict)) if isinstance(content, list) else str(content)
                if role == "user":
                    text = clean_user(text)
                # Developer/system instructions, reasoning and encrypted content are excluded.
                if text.strip():
                    messages.append({"role": role, "text": redact(text)[:9000], "at": stamp})
            elif payload.get("type") in ("function_call_output", "custom_tool_call_output"):
                output = payload.get("output", "")
                if isinstance(output, str):
                    tools.append({"role": "tool", "text": redact(output)[-1800:], "at": stamp})
        elif typ == "event_msg":
            kind = payload.get("type")
            if kind in ("task_started", "turn_started"):
                active, last_event = True, stamp
            elif kind in ("task_complete", "turn_complete", "turn_aborted", "task_aborted"):
                active, last_event = False, stamp
            elif kind in ("user_message", "agent_message"):
                text = payload.get("message", "")
                role = "user" if kind == "user_message" else "assistant"
                if role == "user":
                    text = clean_user(text)
                if text.strip():
                    fallback.append({"role": role, "text": redact(text)[:9000], "at": stamp})
    if not metadata:
        return None
    source = metadata.get("source", "")
    if isinstance(source, dict) and "subagent" in source:
        return None
    if "guardian" in str(metadata.get("thread_source", "")).lower():
        return None
    messages = messages or fallback
    unique = []
    for message in messages:
        key = (message["role"], message["text"], message["at"])
        if key not in seen:
            seen.add(key)
            unique.append(message)
    users = [m for m in unique if m["role"] == "user"]
    if not users:
        return None
    thread_id = metadata.get("id") or metadata.get("session_id")
    if not thread_id:
        return None
    recent = unique[-18:]
    if users[0] not in recent:
        recent.insert(0, users[0])
    # Keep the full latest user instruction and final answer within a bounded context.
    while len(json.dumps(recent, ensure_ascii=False)) > 32000 and len(recent) > 3:
        recent.pop(1)
    recent += list(tools)[-4:]
    recent.sort(key=lambda m: m["at"])
    digest = hashlib.sha256(json.dumps([unique[-18:], list(tools), active], sort_keys=True).encode()).hexdigest()
    return {
        "id": host + ":" + str(thread_id), "thread_id": str(thread_id), "host": host,
        "title": redact((titles or {}).get(thread_id) or users[0]["text"].splitlines()[0])[:180],
        "cwd": str(metadata.get("cwd", "")), "path": str(path), "messages": recent,
        "fingerprint": digest, "updated_at": max([m["at"] for m in unique] + [m["at"] for m in tools] + [last_event]),
        "active": active, "last_event_at": last_event,
        "truncated": stat.st_size > HEAD_BYTES + TAIL_BYTES or len(unique) > len(recent),
        "malformed_lines": malformed,
    }


def collect(request):
    host = request.get("host", "mac")
    root = pathlib.Path(request.get("root") or os.environ.get("CODEX_HOME") or str(pathlib.Path.home() / ".codex")).expanduser().resolve()
    if not (root / "sessions").is_dir():
        raise RuntimeError("Codex sessions 目录不存在: " + str(root / "sessions"))
    known = request.get("known", {})
    limit = min(max(int(request.get("limit", 40)), 1), 300)
    days = int(request.get("days", 0))
    cutoff = time.time() - days * 86400 if days else 0
    candidates = {}
    titles, archive_states = read_registry(root)
    active_paths, archived_paths, path_ids = {}, {}, {}
    for folder, destination in (("sessions",active_paths),("archived_sessions",archived_paths)):
        for path in (root/folder).rglob("*.jsonl"):
            thread_id = path_thread_id(path)
            if thread_id:
                destination[thread_id] = path
                path_ids[str(path)] = thread_id
    for thread_id in archived_paths:
        if thread_id not in active_paths:
            archive_states[thread_id] = True
    for thread_id in active_paths:
        archive_states.setdefault(thread_id, False)
    for path in (root/"sessions").rglob("*.jsonl"):
        if archive_states.get(path_ids.get(str(path)), False):
            continue
        try:
            s = path.stat()
            if s.st_mtime >= cutoff:
                candidates[str(path)] = (s.st_mtime_ns,s.st_size)
        except OSError:
            continue
    changed = [(p, s) for p, s in candidates.items() if known.get(p) != list(s)]
    changed.sort(key=lambda x: x[1][0], reverse=True)
    conversations, files, errors = [], {}, []
    for name, stat in changed[:limit]:
        try:
            conversation = parse_rollout(pathlib.Path(name), host, titles)
            if conversation and not archive_states.get(conversation["thread_id"], False):
                conversations.append(conversation)
            files[name] = list(stat)
        except (OSError, ValueError) as e:
            errors.append({"path": name, "error": type(e).__name__})
    return {"host": host, "root": str(root), "conversations": conversations, "files": files,
            "archive_states": archive_states,
            "total_files": len(candidates), "remaining_files": max(0, len(changed) - limit),
            "read_errors": errors, "collected_at": time.time(), "collector_version": VERSION}


if __name__ == "__main__":
    try:
        print(json.dumps(collect(json.load(sys.stdin)), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"error": redact(str(error))[:500]}))
        sys.exit(1)
