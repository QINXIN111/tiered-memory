"""Agent session discovery.

Point: after `pip install`, the user should immediately see what every local
coding agent already remembers — without configuring anything.

Adapters are read-only and defensive: a broken store returns an error string
instead of raising, and nothing is ever written back to another agent's data.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

HOME = Path.home()


def _mb(p: Path) -> float:
    try:
        if p.is_file():
            return round(p.stat().st_size / 1e6, 1)
        total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        return round(total / 1e6, 1)
    except Exception:
        return 0.0


def _iso(ts: float | int | None) -> str:
    if not ts:
        return ""
    try:
        v = float(ts)
        if v > 1e12:  # milliseconds
            v /= 1000
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(v))
    except Exception:
        return ""


def _clip(s: str, n: int = 130) -> str:
    s = " ".join((s or "").split())
    return s[:n] + ("…" if len(s) > n else "")


# ------------------------------------------------------------------ adapters


def scan_claude() -> dict | None:
    root = HOME / ".claude" / "projects"
    if not root.is_dir():
        return None
    files = list(root.glob("*/*.jsonl"))
    if not files:
        return None
    msgs = 0
    last = 0.0
    sample = ""
    for f in files:
        try:
            with f.open("r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    msgs += 1
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    ts = d.get("timestamp") or d.get("time") or 0
                    if isinstance(ts, str):
                        try:
                            ts = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                        except Exception:
                            ts = 0
                    if ts and ts > last:
                        last = ts
                    if d.get("type") == "user":
                        c = d.get("message", {}).get("content")
                        if isinstance(c, list):
                            c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                        if isinstance(c, str) and c.strip() and not c.startswith("<"):
                            sample = _clip(c)
        except Exception:
            continue
    return {"agent": "Claude Code", "root": str(root), "sessions": len(files), "messages": msgs,
            "last_at": _iso(last), "size_mb": _mb(root), "sample": sample, "error": ""}


def scan_codex() -> dict | None:
    root = HOME / ".codex"
    if not root.is_dir():
        return None
    files = list(root.rglob("*.jsonl"))
    if not files:
        return None
    msgs = 0
    last = 0.0
    sample = ""
    for f in files:
        try:
            with f.open("r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    msgs += 1
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    ts = d.get("ts") or d.get("timestamp") or 0
                    if isinstance(ts, (int, float)) and ts > last:
                        last = ts
                    txt = d.get("text") or (d.get("payload") or {}).get("text")
                    if isinstance(txt, str) and txt.strip():
                        sample = _clip(txt)
        except Exception:
            continue
    return {"agent": "Codex", "root": str(root), "sessions": len(files), "messages": msgs,
            "last_at": _iso(last), "size_mb": _mb(root), "sample": sample, "error": ""}


def scan_gemini() -> dict | None:
    root = HOME / ".gemini" / "tmp"
    if not root.is_dir():
        return None
    files = list(root.rglob("chats/*.json"))
    if not files:
        return None
    msgs = 0
    last = 0.0
    sample = ""
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            msgs += len(data.get("messages", data if isinstance(data, list) else []))
            for m in (data.get("messages") or [])[-3:]:
                if isinstance(m, dict):
                    t = m.get("content") or m.get("text") or ""
                    if isinstance(t, str) and t.strip():
                        sample = _clip(t)
                    ts = m.get("timestamp")
                    if isinstance(ts, (int, float)) and ts > last:
                        last = ts
        except Exception:
            continue
    return {"agent": "Gemini CLI", "root": str(root), "sessions": len(files), "messages": msgs,
            "last_at": _iso(last), "size_mb": _mb(root), "sample": sample, "error": ""}


def scan_opencode() -> dict | None:
    db = HOME / ".local" / "share" / "opencode" / "opencode.db"
    if not db.exists():
        return None
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        sessions = c.execute("select count(*) from session_v2").fetchone()[0]
        try:
            msgs = c.execute("select count(*) from session_message").fetchone()[0]
        except Exception:
            msgs = 0
        last = 0
        try:
            last = c.execute("select max(time_created) from session_message").fetchone()[0] or 0
        except Exception:
            pass
        sample = ""
        try:
            row = c.execute("select title from session_v2 order by rowid desc limit 1").fetchone()
            sample = _clip(row[0] if row else "")
        except Exception:
            pass
        c.close()
        return {"agent": "OpenCode / Pi", "root": str(db.parent), "sessions": sessions,
                "messages": msgs, "last_at": _iso(last), "size_mb": _mb(db),
                "sample": sample, "error": ""}
    except Exception as e:
        return {"agent": "OpenCode / Pi", "root": str(db.parent), "sessions": 0, "messages": 0,
                "last_at": "", "size_mb": _mb(db), "sample": "", "error": str(e)[:80]}


def scan_hermes() -> dict | None:
    home = HOME / ".hermes"
    db = home / "state.db"
    if not db.exists():
        return None
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        sessions = c.execute("select count(*) from sessions").fetchone()[0]
        msgs = c.execute("select count(*) from messages").fetchone()[0]
        last = c.execute("select max(timestamp) from messages").fetchone()[0] or 0
        sample = ""
        try:
            row = c.execute("select content from messages where role='user' order by id desc limit 1").fetchone()
            sample = _clip(row[0] if row else "")
        except Exception:
            pass
        c.close()
        return {"agent": "Hermes", "root": str(home), "sessions": sessions, "messages": msgs,
                "last_at": _iso(last), "size_mb": _mb(db), "sample": sample, "error": ""}
    except Exception as e:
        return {"agent": "Hermes", "root": str(home), "sessions": 0, "messages": 0, "last_at": "",
                "size_mb": _mb(db), "sample": "", "error": str(e)[:80]}


ADAPTERS = (scan_claude, scan_codex, scan_gemini, scan_opencode, scan_hermes)


def scan() -> list[dict]:
    """Every local agent store we can read, never raising."""
    out = []
    for fn in ADAPTERS:
        try:
            r = fn()
        except Exception as e:  # adapter bug must not break the CLI
            r = {"agent": fn.__name__, "root": "", "sessions": 0, "messages": 0, "last_at": "",
                 "size_mb": 0, "sample": "", "error": str(e)[:80]}
        if r:
            out.append(r)
    return out
