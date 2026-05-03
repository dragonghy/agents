# Autonomy Charter — orchestration-v1 Branch

> **Read this at the start of every work session on this branch.**
> If your context was compacted or you've lost track of state, this file
> tells you what your job is and how to make decisions.

## Mandate (verbatim from Human, 2026-05-02)

> 接下来这个过程中，我希望你自己推进这个项目。除非你已经 block 到完全不知道该干嘛，否则我希望你能尽可能（as far as possible）自己推进。

## Default behavior: PUSH FORWARD

When you face a choice, **decide and document**, don't ask. The Human is unavailable. Asking ≠ being careful; it's stalling. Document the decision in the progress journal with rationale; if Human disagrees later it's a 1-line revert.

## What you ARE allowed to decide alone

- Implementation details (file structure, naming, test layout, error handling)
- Library choices (use what's already in the project; pick one if you must add a dep)
- Order of work within a phase (the phases themselves are fixed)
- Refactor scope (clean as you go is fine; big-bang refactors → defer to follow-up tasks)
- Schema iterations (tweak as you discover; document why in commit message)
- Profile system prompt content (write it; Human will adjust if he disagrees)
- Test strategy (you decide what's tested + how)
- Web UI tech stack details (if Phase 3 you reach it without input, pick one and go)
- Adapter abstractions (pick the cleanest interface)

## What you MUST escalate (real blocks only)

These are the only valid reasons to stop and wait for Human:

1. **Need a real-world credential / personal data** that's not already in 1Password Agents vault and you don't have a way to acquire (e.g. Human's Google OAuth token for an account he hasn't authorized).
2. **An action that would spend Human's money** beyond LLM API tokens (subscriptions, server costs, payments). Tokens are pre-approved.
3. **An action that contradicts an explicitly-ratified decision** in the design doc Decision Log. If you find yourself wanting to do the opposite of a Decision Log entry, escalate.
4. **A destructive action on production** — deleting Human-visible data, wiping a database, force-pushing to main, irreversibly closing tickets that may matter.
5. **A genuine technical wall** that you've attempted ≥ 2 fundamentally different approaches on and remain stuck.
6. **A discovered bug in currently-running production code** affecting Human directly RIGHT NOW (different from "future feature has a bug" — the latter is just normal dev work).

If none of these apply, **don't escalate. Decide.**

## Common false-positive blocks (don't escalate for these)

- "I don't know which of two approaches is best" → pick one, write rationale in commit, move on
- "There's a minor naming choice" → pick the one that reads cleanest; rename is cheap
- "Tests are failing in a confusing way" → debug; this is normal dev work
- "I should ask if Human wants X feature" → the design doc already says what to build; if Human wanted X he'd have said
- "What if Human disagrees with my profile prompt wording?" → he can edit it later; don't wait
- "PR review feedback on my own PR" → you are the reviewer; self-review rigorously, then merge
- "Web UI styling looks ugly" → ship functional first, polish in a follow-up

## Working rhythm (each work session)

1. **At session start**: read this file, then `orchestration-v1-progress.md`, then `TaskList`
2. **Pick the next in_progress or pending task** (smallest one that unblocks the most downstream work)
3. **Mark it in_progress** in TaskList (`TaskUpdate`)
4. **Do the work**
5. **Commit + push** (don't accumulate uncommitted changes — push is the durability layer)
6. **Append to progress journal**: 1 paragraph per commit (what / why / next)
7. **Mark task completed** in TaskList
8. **Repeat** until either: tasks list empty, or you hit a real block from the criteria above

## Commit hygiene

- Small commits over big ones. Each commit = one logical step.
- Commit message body should explain **why**, not just **what**.
- Push immediately after each commit. The remote is your real memory.
- Never `git push --force` to `feat/orchestration-v1` once it's shared.
- Co-author trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

## When you finish Phase 1

Don't ask "should I start Phase 2?" — just start. The phases are linear in the design doc; finishing one means starting the next. Same for Phase 2 → 3, etc.

## When ALL tasks are done (Phase 6 complete)

- Run the full test suite one more time.
- Push the final commit.
- Open a PR from `feat/orchestration-v1` to `main` with a comprehensive summary (what changed, what got deleted, migration notes, anything Human needs to verify before merging).
- DO NOT self-merge a branch this large. Add a comment on the PR pinging Human, then mark the final task completed and stop.

## When stuck on something < 2 hours

Don't escalate. Try a second approach. Read documentation. Look at existing code patterns. The Anthropic SDK / Claude Agent SDK is well-documented; most "I don't know how" problems are 1 docs page away.

## When stuck on something ≥ 2 hours

Then escalate. Write a concise message to Human via the appropriate channel (this fork doesn't have Telegram MCP; the message goes into the next conversation turn). Include:

1. What you were trying to do (1 sentence)
2. What you tried (2-3 bullets)
3. What failed and why (1 short paragraph)
4. What you'd need to unblock (specific question or info)

## How to handle context compaction / loss

If you find yourself starting fresh with no memory of prior work:

1. Read this file (`AUTONOMY-CHARTER.md`)
2. Read `projects/agent-hub/orchestration-v1-progress.md` (state of the work)
3. Read `projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md` (what we're building)
4. Run `git log --oneline feat/orchestration-v1` (recent commits = recent decisions)
5. Run `TaskList` (current task status)
6. Pick the next in_progress / pending task and resume from where it left off

Don't re-discuss the design with Human — it's already settled. Just continue building.
