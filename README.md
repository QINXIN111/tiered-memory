# tiered-memory

[![tests](https://github.com/QINXIN111/tiered-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/QINXIN111/tiered-memory/actions/workflows/ci.yml)

**Your agent's always-on memory file is full. Stop putting facts in it — put an index in it.**

One 341-line file, zero dependencies that splits agent memory into two tiers:

```
MEMORY.md      (small, always injected)   one line per topic + a wiki:<topic> pointer
wiki/*.md      (unbounded, read on demand) the actual details
```

The agent reads the index on every turn. When it needs the details behind a pointer, it runs one command.

No vector database. No embeddings. No service. Just Markdown, grep and Git.

```
$ wikimem search "api 8080"
wiki:infra:4  - api listens on 8080; deploy via ./deploy.sh

$ wikimem show infra --grep port
  4| - api listens on 8080; deploy via ./deploy.sh
  5| - staging is the same but on 8081
```

---

## The problem

Every serious agent setup injects a memory file at session start: `MEMORY.md` in Hermes,
`CLAUDE.md` in Claude Code, `AGENTS.md` in Codex. It is capped by the context budget,
usually a couple thousand characters.

Ours hit **99% full** — 31 long entries, 3,437 bytes. After that:

- new facts either overwrite old ones (history lost), or
- nothing gets written (the same mistake happens again next week)

The fix is not "store more". It is **"spend the budget on a table of contents, not on content."**

## What we ended up with

| | before | after |
|---|---|---|
| always-injected file | 3,437 B / 31 entries | **1,727 B / 9 index lines** |
| details | inside those 31 entries | 9 notes, 44 KB, read on demand |
| budget used | 99% | **48%** |

Nothing was lost: we diffed every constant (hostnames, ports, script names, invite codes)
against the old file after the migration.

## Install

```bash
git clone https://github.com/QINXIN111/tiered-memory.git
cd tiered-memory
python3 wikimem.py init          # creates ~/.wikimem/{MEMORY.md,wiki/}
```

Optional — put it on your PATH:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/wikimem.py" ~/.local/bin/wikimem
chmod +x wikimem.py
```

No dependencies. Python 3.10+.

## Commands

| command | what it does |
|---|---|
| `wikimem init` | create `MEMORY.md` + `wiki/` + a sample note |
| `wikimem search "a b"` | all words must match; prints `wiki:topic:line` |
| `wikimem show infra --grep port --ctx 2` | print only the matching lines (`--ctx` = context) |
| `wikimem add infra "text"` | append a stamped bullet: `- [2026-11-12][agent] text` |
| `wikimem lint` | duplicates, notes untouched for 120 days, version conflicts, index budget |
| `wikimem index` | rebuild `wiki/INDEX.md` |
| `wikimem sync` | `git pull --rebase` → commit → push to **every** remote |

Flags: `--root DIR`, `--index FILE`, `--json` on `search`/`show`/`lint`/`sync`.

## How you use it with an agent

1. Tell the agent, once, in the index file itself:

   ```
   Memory is tiered. This file is only the index.
   If you see wiki:xxx, run `wikimem show xxx` before answering. Never guess from the index line.
   ```

2. When the agent learns something durable:

   ```
   $ wikimem add infra "api listens on 8080"
   ```

   then add one line to `MEMORY.md`:

   ```
   infra: hosts, ports, deploy steps → wiki:infra
   ```

3. Cron `wikimem lint` weekly. It only reports; it never edits.

## Why an index instead of a vector store

| | vector DB | this |
|---|---|---|
| setup | embedding model, index, service | one file |
| explainability | "the top-k looked similar" | you can read the line it matched |
| cost | model calls on write and read | zero |
| diff-able | no | `git diff` |
| corpus size | scales to millions | fine to a few thousand facts |

Agent memory is tens to hundreds of facts, not millions of documents. A grep over 44 KB
returns in under a millisecond and you can *see* why it matched.

## Many agents, one memory

Multiple agents (Claude Code, Codex, Hermes, a local harness) writing to the same notes
is where memory systems rot. Four rules, all enforced by the tool:

1. **Partition by domain.** `wiki/<domain>/<topic>.md` — one writer per domain. Most
   conflicts never happen because two agents never touch the same file.
2. **Append, never rewrite.** `wikimem add` stamps `[date][agent]`. When two entries
   disagree, both stay; a human or a lead agent decides.
3. **Pull before you write, push when you are done.** `wikimem sync` does
   `pull --rebase`, commit, push to every remote — conflicts surface in seconds,
   not after a week.
4. **Report conflicts, never auto-merge.** `wikimem lint` flags the same version
   string with two different values. The tool never picks a winner.

Why not CRDTs, a central memory service, or a shared SQLite? Because for a
few hundred facts those add a service to operate, and Git already gives you
versioning, conflict detection, auditing, rollback and a free off-site copy.

**The most dangerous memory bug is not a missing fact — it is a silently merged wrong one.**

## What it deliberately does not do

- **No automatic extraction.** Writing memory is a judgement call; automating it
  turns noise and one-off conclusions into "facts".
- **No full-text injection.** Only the index goes in. Loading everything is how you
  get back to the 2,200-character wall.
- **No database.** Markdown + Git is the storage layer. If a tool can't `diff` it,
  it doesn't belong in memory.

## Repo layout

```
wikimem.py              the whole CLI (341 lines)
tests/                  14 pytest cases
examples/               a small memory root you can copy
docs/design.md          longer design notes: what we tried, what we rejected
```

## Status

Extracted from a production agent setup that has been running this way since 2026-11,
with two private Git remotes and a nightly sync. Battle-tested against one very messy
real workload; the API may still change.

MIT.
