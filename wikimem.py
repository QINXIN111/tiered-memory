#!/usr/bin/env python3
"""tiered-memory — keep your agent's always-on memory small, put the rest on disk.

The always-injected memory file (INDEX) holds one line per topic. The details
live in wiki/<topic>.md and are read on demand. Git gives you versioning,
conflict detection and a free backup.

Usage:
  wikimem init
  wikimem search "deploy port"
  wikimem show infra --grep port
  wikimem add infra "api listens on 8080"
  wikimem lint
  wikimem index
  wikimem sync

Environment:
  WIKIMEM_ROOT      default ~/.wikimem
  WIKIMEM_INDEX     default <root>/MEMORY.md   (the always-injected file)
  WIKIMEM_AGENT     author stamp written by `add` (default $USER)
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".wikimem"
ROOT = Path(os.environ.get("WIKIMEM_ROOT") or DEFAULT_ROOT).expanduser()
INDEX: Path | None = None


def wiki_dir() -> Path:
    return ROOT / "wiki"


def index_path() -> Path:
    if INDEX is not None:
        return INDEX
    env = os.environ.get("WIKIMEM_INDEX")
    return Path(env).expanduser() if env else ROOT / "MEMORY.md"


def notes() -> list[Path]:
    d = wiki_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.md") if p.name != "INDEX.md")


def lines_of(p: Path) -> list[str]:
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


# ---------------------------------------------------------------- commands


def cmd_init(force: bool) -> int:
    wiki_dir().mkdir(parents=True, exist_ok=True)
    idx = index_path()
    if not idx.exists() or force:
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text(
            "# Always-injected memory index.\n"
            "# One line per topic: short facts + a `wiki:<topic>` pointer.\n"
            "# See docs/design.md for the rules.\n\n"
            "project: what it is; how to run it → wiki:project\n"
            "infra: hosts, ports, deploy steps → wiki:infra\n",
            encoding="utf-8",
        )
    ex = wiki_dir() / "project.md"
    if not ex.exists():
        ex.write_text(
            "# project\n\n"
            "- [2026-01-01][setup] Runs with `make dev`; tests with `make test`\n"
            "- Read this file only when the index line is not enough\n",
            encoding="utf-8",
        )
    print(f"initialized: {ROOT}")
    print(f"  index : {idx}")
    print(f"  wiki  : {wiki_dir()}")
    return 0


def _kws(q: str) -> list[str]:
    return [k.lower() for k in q.split() if k.strip()]


def cmd_search(kw: str, limit: int, as_json: bool) -> int:
    kws = _kws(kw)
    hits = []
    for p in notes():
        for i, line in enumerate(lines_of(p), 1):
            low = line.lower()
            if kws and all(k in low for k in kws):
                hits.append({"topic": p.stem, "line": i, "text": line.strip()})
    if as_json:
        print(json.dumps(hits[:limit], ensure_ascii=False, indent=1))
    else:
        for h in hits[:limit]:
            print(f"wiki:{h['topic']}:{h['line']}  {h['text'][:180]}")
        print(f"\n{len(hits)} hit(s) in {len(notes())} note(s)", file=sys.stderr)
    return 0 if hits else 1


def cmd_show(topic: str, grep: str | None, ctx: int, as_json: bool) -> int:
    p = wiki_dir() / f"{topic}.md"
    if not p.exists():
        cands = difflib.get_close_matches(topic, [x.stem for x in notes()], n=3)
        print(f"no such note: wiki:{topic}" + (f"; did you mean {', '.join(cands)}?" if cands else ""),
              file=sys.stderr)
        return 1
    ls = lines_of(p)
    if not grep:
        if as_json:
            print(json.dumps({"topic": topic, "lines": ls}, ensure_ascii=False, indent=1))
        else:
            for i, line in enumerate(ls, 1):
                print(f"{i:>3}| {line}")
        return 0
    idxs = [i for i, l in enumerate(ls) if grep.lower() in l.lower()]
    if not idxs:
        print(f"no match for {grep!r} in wiki:{topic}", file=sys.stderr)
        return 1
    shown = set()
    for i in idxs:
        for j in range(max(0, i - ctx), min(len(ls), i + ctx + 1)):
            if j not in shown:
                print(f"{j+1:>3}| {ls[j]}")
                shown.add(j)
    return 0


def cmd_add(topic: str, text: str, agent: str | None) -> int:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", topic):
        print("topic must be [A-Za-z0-9._-]+", file=sys.stderr)
        return 2
    wiki_dir().mkdir(parents=True, exist_ok=True)
    p = wiki_dir() / f"{topic}.md"
    if not p.exists():
        p.write_text(f"# {topic}\n\n", encoding="utf-8")
    who = agent or os.environ.get("WIKIMEM_AGENT") or os.environ.get("USER") or "agent"
    stamp = time.strftime("%Y-%m-%d")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- [{stamp}][{who}] {text.strip()}\n")
    print(f"appended to wiki:{topic}")
    return 0


def cmd_index() -> int:
    out = ["# Memory wiki index", ""]
    for p in notes():
        ls = lines_of(p)
        title = next((l.lstrip("# ").strip() for l in ls if l.startswith("#")), p.stem)
        bullets = [l for l in ls if l.lstrip().startswith(("-", "*"))]
        out.append(f"## {title}  → wiki:{p.stem}")
        out.append(f"{len(bullets)} entries / {len(ls)} lines / updated "
                   f"{time.strftime('%Y-%m-%d', time.localtime(p.stat().st_mtime))}")
        out.append("")
    (wiki_dir() / "INDEX.md").write_text("\n".join(out), encoding="utf-8")
    print(f"rebuilt INDEX.md ({len(notes())} notes)")
    return 0


def cmd_lint(days: int, max_chars: int, as_json: bool) -> int:
    problems: list[dict] = []
    seen: dict[str, str] = {}
    versions: dict[str, set[str]] = {}
    now = time.time()

    for p in notes():
        ls = lines_of(p)
        if not ls or not ls[0].startswith("#"):
            problems.append({"kind": "missing-title", "where": p.name})
        for i, line in enumerate(ls, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            where = f"wiki:{p.stem}:{i}"
            if len(s) > 220:
                problems.append({"kind": "too-long", "where": where, "chars": len(s)})
            key = re.sub(r"[^\w\u4e00-\u9fff]", "", s.lower())[:80]
            if key:
                if key in seen and seen[key] != where:
                    problems.append({"kind": "duplicate", "where": where, "other": seen[key]})
                else:
                    seen[key] = where
            if re.search(r"version|当前版本|已上线", s, re.I):
                for m in re.finditer(r"\bv(\d+\.\d+(?:\.\d+)?)\b(?!\.sh)", s):
                    versions.setdefault(p.stem, set()).add(m.group(1))
        age = (now - p.stat().st_mtime) / 86400
        if age > days:
            problems.append({"kind": "stale", "where": f"wiki:{p.stem}", "days": int(age)})

    for topic, vs in versions.items():
        if len(vs) > 1:
            problems.append({"kind": "version-conflict", "where": f"wiki:{topic}",
                             "versions": sorted(vs)})

    idx = index_path()
    if idx.exists():
        body = idx.read_text(encoding="utf-8")
        if len(body) > max_chars:
            problems.append({"kind": "index-budget", "where": str(idx), "chars": len(body),
                             "budget": max_chars})

    if as_json:
        print(json.dumps({"problems": problems}, ensure_ascii=False, indent=1))
    else:
        for pr in problems:
            kind = pr["kind"]
            if kind == "duplicate":
                print(f"[duplicate] {pr['where']} ≈ {pr['other']}")
            elif kind == "version-conflict":
                print(f"[conflict] {pr['where']} has versions {', '.join('v'+v for v in pr['versions'])}")
            elif kind == "stale":
                print(f"[stale {pr['days']}d] {pr['where']}")
            elif kind == "index-budget":
                print(f"[budget] {pr['chars']} chars > {pr['budget']} in {pr['where']}")
            else:
                print(f"[{kind}] {pr['where']}")
        print(f"\n{len(problems)} problem(s)")
    return 0 if not problems else 1


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def cmd_sync(message: str | None, as_json: bool) -> int:
    """pull --rebase, commit local changes, push to every remote."""
    if not (ROOT / ".git").exists():
        print(f"{ROOT} is not a git repository; run `git init` first", file=sys.stderr)
        return 2
    log: list[str] = []

    pull = _git("pull", "--rebase", "--autostash")
    log.append(f"pull: {'ok' if pull.returncode == 0 else pull.stderr.strip()[:200]}")

    status = _git("status", "--porcelain")
    if status.stdout.strip():
        _git("add", "-A")
        msg = message or f"memory sync {time.strftime('%Y-%m-%d %H:%M')}"
        c = _git("-c", "user.name=tiered-memory", "-c", "user.email=memory@local", "commit", "-m", msg)
        log.append(f"commit: {'ok' if c.returncode == 0 else c.stderr.strip()[:200]}")
    else:
        log.append("commit: nothing to commit")

    remotes = [r for r in _git("remote").stdout.split() if r]
    if not remotes:
        log.append("push: no remotes configured")
    for r in remotes:
        p = _git("push", "-q", r, "HEAD")
        log.append(f"push {r}: {'ok' if p.returncode == 0 else p.stderr.strip()[:200]}")

    if as_json:
        print(json.dumps({"log": log}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(log))
    return 0 if all("ok" in x or "nothing" in x or "no remotes" in x for x in log) else 1


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="memory root (default ~/.wikimem or $WIKIMEM_ROOT)")
    common.add_argument("--index", help="always-injected index file (default <root>/MEMORY.md)")

    ap = argparse.ArgumentParser(prog="wikimem", description="Tiered memory for AI agents.",
                                 parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create root, index and a sample note", parents=[common])
    s.add_argument("--force", action="store_true", help="overwrite the index file")

    p = sub.add_parser("search", help="keyword search across notes (all words must match)", parents=[common])
    p.add_argument("kw")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("show", help="print a note, optionally only matching lines", parents=[common])
    p.add_argument("topic")
    p.add_argument("--grep")
    p.add_argument("--ctx", type=int, default=2)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("add", help="append one stamped bullet to a note", parents=[common])
    p.add_argument("topic")
    p.add_argument("text")
    p.add_argument("--agent")

    p = sub.add_parser("lint", help="duplicates, stale notes, version conflicts, index budget", parents=[common])
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--max-chars", type=int, default=2200)
    p.add_argument("--json", action="store_true")

    sub.add_parser("index", help="rebuild wiki/INDEX.md", parents=[common])

    p = sub.add_parser("sync", help="git pull --rebase, commit, push to every remote", parents=[common])
    p.add_argument("-m", "--message")
    p.add_argument("--json", action="store_true")

    ns = ap.parse_args(argv)

    global ROOT, INDEX
    if ns.root:
        ROOT = Path(ns.root).expanduser()
    if ns.index:
        INDEX = Path(ns.index).expanduser()

    if ns.cmd == "init":
        return cmd_init(ns.force)
    if ns.cmd == "search":
        return cmd_search(ns.kw, ns.limit, ns.json)
    if ns.cmd == "show":
        return cmd_show(ns.topic, ns.grep, ns.ctx, ns.json)
    if ns.cmd == "add":
        return cmd_add(ns.topic, ns.text, ns.agent)
    if ns.cmd == "lint":
        return cmd_lint(ns.days, ns.max_chars, ns.json)
    if ns.cmd == "index":
        return cmd_index()
    if ns.cmd == "sync":
        return cmd_sync(ns.message, ns.json)
    return 1


if __name__ == "__main__":
    sys.exit(main())
