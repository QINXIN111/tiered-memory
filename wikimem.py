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


VIZ_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tiered-memory · __TITLE__</title>
<style>
  :root {
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2129; --line:#2a3038;
    --fg:#e6edf3; --muted:#8b949e; --accent:#a371f7; --ok:#3fb950; --warn:#d29922; --bad:#f85149;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"PingFang SC","Microsoft YaHei",sans-serif; }
  header { padding:22px 28px 14px; border-bottom:1px solid var(--line); }
  h1 { margin:0 0 4px; font-size:19px; letter-spacing:.2px; }
  h1 span { color:var(--accent); }
  .sub { color:var(--muted); font-size:12.5px; }
  .stats { display:flex; gap:22px; margin-top:14px; flex-wrap:wrap; }
  .stat b { font-size:18px; font-weight:600; }
  .stat span { display:block; color:var(--muted); font-size:11.5px; text-transform:uppercase; letter-spacing:.6px; }
  .budget { margin-top:16px; max-width:640px; }
  .bar { height:9px; background:#21262d; border-radius:6px; overflow:hidden; }
  .bar > i { display:block; height:100%; background:linear-gradient(90deg,var(--ok),#56d364); }
  .bar.warn > i { background:linear-gradient(90deg,var(--warn),#e3b341); }
  .bar.bad > i { background:linear-gradient(90deg,var(--bad),#ff7b72); }
  .bar-label { display:flex; justify-content:space-between; color:var(--muted); font-size:11.5px; margin-top:5px; }
  main { display:grid; grid-template-columns:minmax(280px,340px) 1fr; gap:20px; padding:20px 28px 40px; align-items:start; }
  @media (max-width:900px){ main{ grid-template-columns:1fr; } }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; }
  .panel h2 { margin:0; padding:12px 14px; font-size:12.5px; text-transform:uppercase; letter-spacing:.7px;
              color:var(--muted); border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; }
  .panel h2 button { background:var(--panel2); color:var(--fg); border:1px solid var(--line); border-radius:6px;
                     padding:3px 8px; font-size:11px; cursor:pointer; }
  .panel h2 button:hover { border-color:var(--accent); }
  .index { padding:10px 12px; font:12px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre-wrap; color:#c9d1d9; }
  .index .ptr { color:var(--accent); }
  .search { padding:12px 14px; border-bottom:1px solid var(--line); }
  .search input { width:100%; background:var(--panel2); border:1px solid var(--line); color:var(--fg);
                  border-radius:8px; padding:9px 11px; font-size:13px; outline:none; }
  .search input:focus { border-color:var(--accent); }
  .notes { padding:6px 0 10px; }
  details { border-bottom:1px solid var(--line); }
  details:last-child { border-bottom:0; }
  summary { list-style:none; cursor:pointer; padding:12px 14px; display:flex; gap:10px; align-items:baseline; }
  summary::-webkit-details-marker { display:none; }
  summary:hover { background:var(--panel2); }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--accent); flex:0 0 auto; margin-top:6px; }
  .name { font-weight:600; }
  .meta { color:var(--muted); font-size:11.5px; margin-left:auto; white-space:nowrap; }
  .entries { padding:2px 14px 14px 34px; }
  .entry { padding:7px 0; border-top:1px dashed #232932; display:flex; gap:10px; }
  .entry:first-child { border-top:0; }
  .stamp { color:var(--muted); font:11px ui-monospace,monospace; white-space:nowrap; padding-top:2px; }
  .text { flex:1; }
  mark { background:#6e40c9; color:#fff; border-radius:3px; padding:0 2px; }
  .issues { margin:0 28px 28px; padding:12px 14px; border:1px solid #3d2b1f; background:#1f1a16; border-radius:10px; }
  .issues b { color:var(--warn); }
  .issues div { color:#d7c7b8; font-size:12.5px; }
  footer { color:var(--muted); font-size:11.5px; padding:0 28px 30px; }
</style>
</head>
<body>
<header>
  <h1>tiered-memory <span>· memory map</span></h1>
  <div class="sub">Context holds the index. Everything else lives on disk. Click a note to open it.</div>
  <div class="stats">
    <div class="stat"><b id="s-notes">0</b><span>notes</span></div>
    <div class="stat"><b id="s-entries">0</b><span>facts</span></div>
    <div class="stat"><b id="s-chars">0</b><span>chars on disk</span></div>
    <div class="stat"><b id="s-index">0</b><span>index chars</span></div>
    <div class="stat"><b id="s-issues">0</b><span>lint issues</span></div>
  </div>
  <div class="budget">
    <div class="bar" id="bar"><i style="width:0%"></i></div>
    <div class="bar-label"><span id="bar-left">index budget</span><span id="bar-right"></span></div>
  </div>
</header>

<main>
  <section class="panel">
    <h2>Always in context <button id="copy">copy</button></h2>
    <div class="index" id="index"></div>
  </section>

  <section class="panel">
    <h2>On disk</h2>
    <div class="search"><input id="q" placeholder="filter facts…  (try: deploy, 8081, postgres)"></div>
    <div class="notes" id="notes"></div>
  </section>
</main>

<div class="issues" id="issues" style="display:none"></div>
<footer>generated by <code>wikimem viz</code> · __WHEN__</footer>

<script>
const DATA = __DATA__;
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const hl = (s, q) => {
  if (!q) return esc(s);
  const i = s.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return esc(s);
  return esc(s.slice(0,i)) + '<mark>' + esc(s.slice(i, i+q.length)) + '</mark>' + esc(s.slice(i+q.length));
};

document.getElementById('s-notes').textContent = DATA.notes.length;
document.getElementById('s-entries').textContent = DATA.stats.entries;
document.getElementById('s-chars').textContent = DATA.stats.chars.toLocaleString();
document.getElementById('s-index').textContent = DATA.index.chars.toLocaleString();
document.getElementById('s-issues').textContent = DATA.issues.length;

const pct = Math.min(100, Math.round(DATA.index.chars / DATA.index.budget * 100));
const bar = document.getElementById('bar');
bar.querySelector('i').style.width = Math.min(100, pct) + '%';
if (pct >= 100) bar.classList.add('bad'); else if (pct >= 75) bar.classList.add('warn');
document.getElementById('bar-left').textContent = 'index budget ' + pct + '%';
document.getElementById('bar-right').textContent = DATA.index.chars + ' / ' + DATA.index.budget + ' chars';

document.getElementById('index').innerHTML = DATA.index.lines.length
  ? DATA.index.lines.map(l => esc(l).replace(/(wiki:[A-Za-z0-9._-]+)/g, '<span class="ptr">$1</span>')).join('\n')
  : '<span style="color:#8b949e">(index file not found)</span>';

document.getElementById('copy').onclick = async () => {
  await navigator.clipboard.writeText(DATA.index.lines.join('\n'));
  const b = document.getElementById('copy'); b.textContent = 'copied'; setTimeout(()=>b.textContent='copy', 1200);
};

function render(q) {
  const box = document.getElementById('notes');
  box.innerHTML = '';
  DATA.notes.forEach(n => {
    const hits = q ? n.entries.filter(e => (e.text + ' ' + n.topic).toLowerCase().includes(q.toLowerCase())) : n.entries;
    if (q && !hits.length) return;
    const d = document.createElement('details');
    if (q) d.open = true;
    d.innerHTML = '<summary><i class="dot"></i><span class="name">' + esc(n.title) +
      '</span><span class="meta">' + n.entries.length + ' facts · ' + esc(n.updated) + ' → wiki:' + esc(n.topic) + '</span></summary>' +
      '<div class="entries">' + hits.map(e =>
        '<div class="entry"><span class="stamp">' + esc(e.stamp) + (e.agent ? ' ' + esc(e.agent) : '') +
        '</span><span class="text">' + hl(e.text, q) + '</span></div>').join('') + '</div>';
    box.appendChild(d);
  });
  if (!box.children.length) box.innerHTML = '<div style="padding:16px;color:#8b949e">no facts match that filter</div>';
}
render('');

document.getElementById('q').addEventListener('input', e => render(e.target.value.trim()));

if (DATA.issues.length) {
  const el = document.getElementById('issues');
  el.style.display = 'block';
  el.innerHTML = '<b>' + DATA.issues.length + ' lint issue(s)</b>' +
    DATA.issues.map(i => '<div>' + esc(i.kind) + ' — ' + esc(i.where) + '</div>').join('');
}
</script>
</body>
</html>
"""


def _parse_entries(ls: list[str]) -> list[dict]:
    out = []
    for line in ls:
        s = line.strip()
        if not s.startswith(("-", "*")):
            continue
        m = re.match(r"^[-*]\s*\[(\d{4}-\d{2}-\d{2})\](?:\[([^\]]+)\])?\s*(.*)$", s)
        if m:
            out.append({"stamp": m.group(1), "agent": m.group(2) or "", "text": m.group(3)})
        else:
            out.append({"stamp": "", "agent": "", "text": s.lstrip("-* ").strip()})
    return out


def cmd_viz(out_path: str | None, budget: int) -> int:
    """Write a single self-contained HTML file. No server, no network, no deps."""
    payload_notes = []
    total_chars = 0
    total_entries = 0
    for p in notes():
        ls = lines_of(p)
        body = "\n".join(ls)
        total_chars += len(body)
        entries = _parse_entries(ls)
        total_entries += len(entries)
        title = next((l.lstrip("# ").strip() for l in ls if l.startswith("#")), p.stem)
        payload_notes.append({
            "topic": p.stem,
            "title": title,
            "entries": entries,
            "chars": len(body),
            "updated": time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime)),
        })

    idx = index_path()
    idx_lines = idx.read_text(encoding="utf-8").splitlines() if idx.exists() else []

    data = {
        "notes": payload_notes,
        "stats": {"entries": total_entries, "chars": total_chars},
        "index": {"path": str(idx), "chars": sum(len(l) for l in idx_lines) + max(0, len(idx_lines) - 1),
                  "budget": budget, "lines": idx_lines},
        "issues": [{"kind": pr["kind"], "where": pr["where"]} for pr in _lint_problems(120, budget)],
    }

    tpl = VIZ_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    tpl = tpl.replace("__TITLE__", ROOT.name or "memory")
    tpl = tpl.replace("__WHEN__", time.strftime("%Y-%m-%d %H:%M"))

    out = Path(out_path).expanduser() if out_path else ROOT / "memory-map.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tpl, encoding="utf-8")
    print(f"wrote {out}  ({len(payload_notes)} notes, {total_entries} facts)")
    print("open it in a browser — no server needed")
    return 0


def _lint_problems(days: int = 120, max_chars: int = 2200) -> list[dict]:
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

    return problems


def cmd_lint(days: int, max_chars: int, as_json: bool) -> int:
    problems = _lint_problems(days, max_chars)
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
    # default=SUPPRESS so a subparser never overwrites a global flag given before the command
    common.add_argument("--root", default=argparse.SUPPRESS,
                        help="memory root (default ~/.wikimem or $WIKIMEM_ROOT)")
    common.add_argument("--index", default=argparse.SUPPRESS,
                        help="always-injected index file (default <root>/MEMORY.md)")

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

    p = sub.add_parser("viz", help="write a self-contained HTML memory map", parents=[common])
    p.add_argument("-o", "--out", help="output html path (default <root>/memory-map.html)")
    p.add_argument("--max-chars", type=int, default=2200)

    p = sub.add_parser("sync", help="git pull --rebase, commit, push to every remote", parents=[common])
    p.add_argument("-m", "--message")
    p.add_argument("--json", action="store_true")

    ns = ap.parse_args(argv)

    global ROOT, INDEX
    if getattr(ns, "root", None):
        ROOT = Path(ns.root).expanduser()
    if getattr(ns, "index", None):
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
    if ns.cmd == "viz":
        return cmd_viz(ns.out, ns.max_chars)
    if ns.cmd == "sync":
        return cmd_sync(ns.message, ns.json)
    return 1


if __name__ == "__main__":
    sys.exit(main())
