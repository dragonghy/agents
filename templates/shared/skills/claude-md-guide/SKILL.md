---
name: claude-md-guide
description: How to maintain a project's claude.md file -- the project's working memory loaded into every agent session.
---

# claude.md Maintenance Guide

## Purpose

`claude.md` is the project's **working memory**. It is loaded into every agent session automatically. Its job is to give any agent enough context to start working on a task without reading dozens of files first.

## Hard Rule: MAX 300 Lines

claude.md must never exceed 300 lines. This is a hard cap. If you need to add content and the file is near the limit, move existing detail into `docs/` and replace it with a pointer.

## What Belongs in claude.md

1. **Project purpose** (2-3 sentences) -- What this project does and who it serves.
2. **Tech stack and key dependencies** -- Languages, frameworks, major libraries, versions only if they matter.
3. **Core architecture** (brief) -- How the system is structured at a high level. Not a full design doc, just enough to orient someone.
4. **Key conventions** -- Naming patterns, branching strategy, deployment process, code style rules that aren't enforced by linters.
5. **Critical constraints and known pitfalls** (top 5-10) -- Things that will bite you if you don't know about them. Database quirks, API limitations, race conditions, etc.
6. **Pointers to detailed docs** -- Brief description + file path for each. Example: "API design: see `docs/api-spec.md`"

## What Does NOT Belong

Move these to dedicated files and leave only a pointer in claude.md:

| Content | Where it goes |
|---|---|
| Detailed API specs | `docs/api-spec.md` or similar |
| Step-by-step procedures | `skills/` (as a SKILL.md) |
| Decision logs and rationale | `docs/decisions/` |
| Full architecture diagrams | `docs/architecture.md` |
| Meeting notes | `docs/notes/` |
| Long lists of examples | `docs/examples/` |

## Maintenance Rules

### When completing a task

After finishing any task that produces reusable knowledge, evaluate:
- Does this knowledge belong in claude.md? (general, frequently needed, affects all agents)
- Or does it belong in docs/ or a skill? (specific, procedural, deep detail)

### When adding content

1. Check the current line count first.
2. If near the 300-line limit, review the file for content that can be moved to docs/.
3. Add your content with the minimum words necessary.
4. Prefer the **pointer structure**: one-line summary + link to detail file.

### When reviewing

- Remove outdated information (deprecated features, resolved pitfalls, old conventions).
- Consolidate duplicate or overlapping sections.
- Verify that pointers still point to existing files.
- Never let it grow unbounded -- treat 300 lines as a budget, not a target.

### Structure template

```markdown
# Project Name

## Purpose
[2-3 sentences]

## Tech Stack
[Bullet list of key technologies]

## Architecture
[Brief overview, 5-15 lines max]

## Key Directories
[Map of important directories and what they contain]

## Conventions
[Naming, branching, deployment rules]

## Known Pitfalls
[Top 5-10 things that will bite you]

## References
[Pointers to detailed docs, each as: brief desc -> file path]
```

## Anti-Patterns

- **Dumping full specs** -- claude.md is an index, not an encyclopedia.
- **Copy-pasting error logs** -- Summarize the issue and fix, link to the ticket.
- **Adding "just in case" info** -- If it's not needed for most tasks, it doesn't belong here.
- **Forgetting to prune** -- Every addition should prompt a review of what can be removed.
