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
