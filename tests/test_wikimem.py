import json
import os
import time
from pathlib import Path

import pytest

import wikimem


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMEM_ROOT", str(tmp_path / "mem"))
    monkeypatch.setenv("WIKIMEM_AGENT", "tester")
    wikimem.ROOT = tmp_path / "mem"
    wikimem.INDEX = tmp_path / "mem" / "MEMORY.md"
    assert wikimem.main(["init"]) == 0
    return tmp_path / "mem"


def test_init_creates_structure(root):
    assert (root / "wiki" / "project.md").exists()
    assert (root / "MEMORY.md").read_text().strip()


def test_add_stamps_date_and_agent(root):
    assert wikimem.main(["add", "infra", "api listens on 8080"]) == 0
    line = (root / "wiki" / "infra.md").read_text().splitlines()[-1]
    assert line.startswith("- [") and "][tester] " in line
    assert time.strftime("%Y-%m-%d") in line


def test_add_rejects_bad_topic(root):
    assert wikimem.main(["add", "../evil", "x"]) == 2


def test_search_requires_all_words(root, capsys):
    wikimem.main(["add", "infra", "api listens on 8080"])
    wikimem.main(["add", "infra", "worker listens on 9090"])
    capsys.readouterr()
    assert wikimem.main(["search", "api 8080"]) == 0
    out = capsys.readouterr().out
    assert "api listens" in out and "worker" not in out
    assert wikimem.main(["search", "api 9090"]) == 1


def test_show_grep_context(root, capsys):
    for i in range(5):
        wikimem.main(["add", "infra", f"line {i}"])
    wikimem.main(["add", "infra", "the needle"])
    capsys.readouterr()
    assert wikimem.main(["show", "infra", "--grep", "needle", "--ctx", "1"]) == 0
    out = capsys.readouterr().out
    assert "needle" in out


def test_show_missing_suggests(root):
    assert wikimem.main(["show", "infr"]) == 1


def test_lint_detects_duplicate(root, capsys):
    wikimem.main(["add", "infra", "same text"])
    wikimem.main(["add", "infra", "same text"])
    capsys.readouterr()
    assert wikimem.main(["lint"]) == 1
    assert "duplicate" in capsys.readouterr().out


def test_lint_detects_version_conflict(root, capsys):
    wikimem.main(["add", "svc", "current version v1.2.0"])
    wikimem.main(["add", "svc", "version: v1.3.0"])
    capsys.readouterr()
    assert wikimem.main(["lint"]) == 1
    out = capsys.readouterr().out
    assert "conflict" in out and "v1.2.0" in out


def test_lint_ignores_script_filename_versions(root, capsys):
    wikimem.main(["add", "svc", "current version v1.3.0"])
    wikimem.main(["add", "svc", "rollback script rollback-to-v1.2.0.sh"])
    capsys.readouterr()
    wikimem.main(["lint"])
    assert "conflict" not in capsys.readouterr().out


def test_lint_stale(root, capsys):
    old = root / "wiki" / "legacy.md"
    old.write_text("# legacy\n\n- old fact\n")
    six_months = time.time() - 200 * 86400
    os.utime(old, (six_months, six_months))
    capsys.readouterr()
    assert wikimem.main(["lint", "--days", "120"]) == 1
    assert "stale" in capsys.readouterr().out


def test_lint_index_budget(root, capsys):
    (root / "MEMORY.md").write_text("x" * 3000)
    capsys.readouterr()
    assert wikimem.main(["lint", "--max-chars", "2200"]) == 1
    assert "budget" in capsys.readouterr().out


def test_lint_json(root, capsys):
    (root / "MEMORY.md").write_text("y" * 3000)
    capsys.readouterr()
    wikimem.main(["lint", "--max-chars", "100", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert any(p["kind"] == "index-budget" for p in data["problems"])


def test_index_lists_titles(root, capsys):
    wikimem.main(["add", "infra", "a fact"])
    capsys.readouterr()
    assert wikimem.main(["index"]) == 0
    body = (root / "wiki" / "INDEX.md").read_text()
    assert "wiki:infra" in body


def test_sync_without_git_fails(root):
    assert wikimem.main(["sync"]) == 2


def test_root_flag_before_subcommand(tmp_path, capsys):
    target = tmp_path / "elsewhere"
    assert wikimem.main(["--root", str(target), "init"]) == 0
    capsys.readouterr()
    assert (target / "wiki" / "project.md").exists()


def test_root_flag_after_subcommand(tmp_path, capsys):
    target = tmp_path / "later"
    assert wikimem.main(["init", "--root", str(target)]) == 0
    capsys.readouterr()
    assert (target / "wiki" / "project.md").exists()


def test_viz_writes_html(root, tmp_path, capsys):
    wikimem.main(["add", "infra", "api listens on 8080"])
    capsys.readouterr()
    out = tmp_path / "map.html"
    assert wikimem.main(["viz", "-o", str(out)]) == 0
    html = out.read_text()
    assert "api listens on 8080" in html
    assert "<script>" in html and "wiki:infra" in html


def test_viz_default_path(root, capsys):
    assert wikimem.main(["viz"]) == 0
    capsys.readouterr()
    assert (root / "memory-map.html").exists()


def test_scan_claude_reads_jsonl(tmp_path, monkeypatch):
    import json as _json
    import sessions as S

    fake = tmp_path / "home"
    d = fake / ".claude" / "projects" / "-tmp-proj"
    d.mkdir(parents=True)
    lines = [
        {"type": "user", "timestamp": "2026-11-01T10:00:00", "message": {"content": "fix the login bug"}},
        {"type": "assistant", "timestamp": "2026-11-01T10:00:05", "message": {"content": "ok"}},
        {"type": "user", "timestamp": "2026-11-02T09:00:00", "message": {"content": "now add tests"}},
    ]
    (d / "s1.jsonl").write_text("\n".join(_json.dumps(x) for x in lines))

    monkeypatch.setattr(S, "HOME", fake)
    row = S.scan_claude()
    assert row and row["sessions"] == 1
    assert row["messages"] == 3
    assert "add tests" in row["sample"]


def test_scan_opencode_reads_sqlite(tmp_path, monkeypatch):
    import sqlite3
    import sessions as S

    fake = tmp_path / "home"
    d = fake / ".local" / "share" / "opencode"
    d.mkdir(parents=True)
    db = d / "opencode.db"
    c = sqlite3.connect(db)
    c.execute("create table session_v2 (id text, title text)")
    c.execute("create table session_message (id text, session_id text, time_created int)")
    c.execute("insert into session_v2 values ('a','first chat')")
    c.execute("insert into session_message values ('m1','a',1794000000)")
    c.commit()
    c.close()

    monkeypatch.setattr(S, "HOME", fake)
    row = S.scan_opencode()
    assert row and row["sessions"] == 1 and row["messages"] == 1
    assert row["sample"] == "first chat"


def test_scan_is_empty_and_silent_on_bare_machine(tmp_path, monkeypatch):
    import sessions as S

    monkeypatch.setattr(S, "HOME", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert S.scan() == []


def test_scan_cli_reports_nothing(tmp_path, monkeypatch, capsys):
    import sessions as S

    monkeypatch.setattr(S, "HOME", tmp_path / "empty2")
    (tmp_path / "empty2").mkdir()
    capsys.readouterr()
    assert wikimem.main(["scan"]) == 1
    assert "no agent session stores" in capsys.readouterr().out
