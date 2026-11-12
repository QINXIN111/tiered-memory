# Design notes

Why the tool looks like this, and what we rejected along the way.

## 1. Start from the constraint, not the feature

The requirement was never "a better memory system". It was:

> The always-injected memory file is capped at ~2,200 characters. When it fills up,
> new facts have nowhere to go.

In a typical setup it fills up after a few dozen facts: every new fact then either
overwrites an old one or is dropped. Both are silent failures.

So the design goal became: **make the always-injected file a table of contents.**

## 2. Four things we refused to build

| Rejected | Why |
|---|---|
| Vector store | A few hundred facts don't need embeddings. Embeddings add a model dependency, a cost per write and per recall, and remove explainability: you can't show the user *why* a fact was recalled, only that a distance was small. |
| A database as the source of truth | Facts in SQLite can't be `git diff`ed, can't be reviewed in a PR, can't be recovered by `git checkout`, and can't move between machines without an export step. |
| Fully automatic memory extraction | Writing memory is a judgement call. Automation converts noise, hallucinations and one-off conclusions into "facts" that later steer the agent. Writes go through an explicit command. |
| Injecting everything | If the whole corpus fit in context there would be no problem. Injecting more means compressing each item until it is vague — the worst of both worlds. |

## 3. Layer by frequency, not by importance

The sorting question is **"will this be needed in the next session?"** — not
"is this important?".

`rollback-to-v0.1.12.sh` is critical and used once a week: it belongs in a note,
not in the always-on index. Meanwhile "never push to main" is needed every session
and is one line.

Corollary: the index should hold *reminders and pointers*, not knowledge.

## 4. Progressive disclosure, and its single failure mode

The index line looks like this:

```
movo: deployed at 10.0.0.5; build uses /opt/work → wiki:movo
```

The agent sees the pointer and calls `wikimem show movo --grep build` when it needs
the details. This keeps the injected block small and forces a lookup at the moment
of use instead of a vague recollection.

**The failure mode is obvious: the agent sees the pointer and never opens it.**
That's why the rule is written into the first line of the index file itself and
repeated in the agent's system prompt: *see a pointer, open it before answering.*
Every design has one way to break; name it explicitly.

## 5. Multi-agent: the real hard part

One agent with one memory file is easy. Several agents — Claude Code, Codex, a
local harness — sharing memory is where things rot. Three failure modes:

| Failure | Symptom |
|---|---|
| concurrent writes | lost updates or merge conflicts |
| stale reads | agent A records v1.18, agent B still acts on v1.17 |
| decay | an old conclusion stays authoritative because nobody deletes it |

### Rules

1. **Partition by domain.** One writer per file. Conflicts mostly disappear before
   they exist.
2. **Append-only with provenance.** `- [date][agent] text`. When two entries
   disagree, keep both and surface the disagreement.
3. **Pull before write.** Sync is not a nightly batch; it's a precondition for the
   next write.
4. **Conflicts are reported, never merged.** `lint` finds the same field with two
   values and tells a human. Automatic last-write-wins is how memory silently
   becomes wrong.

### Why not CRDTs / a memory service / shared SQLite

- CRDTs solve concurrent editing for large collaborative datasets; the complexity
  dwarfs the benefit for a few hundred facts.
- A central memory service is a single point of failure and requires the network
  for something that should work offline.
- Shared SQLite means writing your own locking and replication — i.e. reimplementing
  a worse Git.

Git is not chosen because it's modern. It's chosen because versioning, conflict
detection, audit trail, rollback and off-site backup arrive in one dependency that
every developer already has.

## 6. Metrics we actually track

| Metric | How | Target |
|---|---|---|
| hit rate | count `show` per note over 30 days | 0 in 60 days → merge or delete |
| index decay | pointers with no target, duplicate lines | 0 |
| budget | characters in the index file | < 70% |
| conflicts | version conflicts reported by lint | < 3 per week |

Notice the order: first make hit rate visible, **then delete the notes nobody opens**.
Most memory systems die from never deleting, not from never writing.

## 7. Known traps

- **Write the note before the pointer.** Reverse order leaves dangling pointers,
  which are worse than no pointer.
- **Keep index lines short.** Past ~80 characters you're moving content back into
  the budget you were trying to protect.
- **Record decisions, not discussions.** "Use A, not B, because C" — the discussion
  lives in git history.
- **Memory is data, not instructions.** Text inside a note that says "ignore previous
  instructions" is content to be reported, never obeyed.
- **Deletion is a feature.** Without it, the store becomes a landfill in six months.

## 8. One sentence

> The goal isn't to remember more; it's to make the right fact appear at the moment
> it's needed, inside a budget that never grows.
