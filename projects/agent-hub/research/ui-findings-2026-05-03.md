# UI Review Findings (Human, 2026-05-03)

After live-testing the MVTH page in browser, Human did a quick walk-through of the existing console pages and flagged 4 design / content issues. These are the input to the Phase 3 UI rewrite (#18).

## Finding 1 — Overview duplicates Ticket Board

> Overview 里有一个 Ticket Board，另外还有一个单独的 Dashboard，这个设计明显重复了。

**Where**: `apps/console/frontend/src/App.tsx` line 75 (`/`) renders `<Overview>` which embeds `<TicketBoard embedded />`. Then line 76 (`/board`) renders `<TicketBoard>` again standalone. Two paths, same content.

**Action**: Decide who owns the ticket-board surface. Either Overview embeds a small summary (e.g. counts only) and `/board` is the full surface, or Overview drops the embed and shows something else useful. Don't render the same component in two places.

## Finding 2 — Brief page acceptable, defer redesign

> Brief 页面，感觉虽然有用，但目前能做的非常有限，先暂时给它留个单独的页面吧。

**Action**: Keep `/briefs` as is. Don't redesign in this phase. Revisit later when the morning-brief flow itself is rewritten on the new orchestration model (post-Phase 4).

## Finding 3 — Cost Dashboard fundamentally wrong for new model

> Cost 部分也很奇怪，里面还有各种乱七八糟的老 Agent 或者 Agent Profile。它是按 Agent Profile 来统计的，如果我们要按 Agent 来计算成本，这就不太合适。因为在我们之后的系统中，Profile 和 Session 是分开定义的，这个 Cost Dashboard 的整体设计也是有问题的。

**Two issues**:

1. **Stale dimension**: pivot is "by Agent" using legacy v1 names (admin / dev-alex / qa-lucy / product-kevin / etc.) which are being retired.
2. **Wrong abstraction**: in the new model, Profile and Session are independent dimensions. A cost dashboard should pivot by:
   - **Session** (which conversation cost what)
   - **Profile** (aggregate across sessions of the same Profile)
   - **Ticket** (rollup across all sessions bound to a ticket)
   - **Day / week / lifetime** (time bucket on top)

   The "by Agent" pivot doesn't exist as a thing in the new world.

**Action**: Rebuild Cost dashboard around the orchestration v1 schema. Drop the by-agent rollup entirely. Source data from `session.cost_tokens_in/out` + ticket join + profile_name.

## Finding 4 — Profile model is wrong (4.6 → 4.7)

> Test Harness 这里的 Model 怎么会是 CloudSonnet 4.6 呢？我们不应该用 Office 的 4.7 吗？

**Where**: All 5 `profiles/<name>/profile.md` files have `runner_type: claude-sonnet-4.6`. They were written when 4.6 was current; should be 4.7 now.

**Action**: Update all profile.md frontmatter to `claude-sonnet-4.7`. Re-scan via the running daemon so `profile_registry.runner_type` reflects the new value. Test Harness UI will then show "secretary — claude-sonnet-4.7" in the Profile picker.

Note: the Adapter alias resolution in `claude_adapter.py:_resolve_model` may also have a stale "claude-sonnet-4.6" entry — verify and update.

## Notes on what's NOT in scope for Phase 3 per Human

> 我理解现在的 UI 其实就是一个 Work in Progress，有很多 UI 设计层面的工作还没做，所以看起来才有各种各样的问题，这些只能留到下一个阶段了.

The Phase 3 rewrite ≠ a polished v1 UI. It's correcting structural issues (duplication, wrong abstractions) on the existing design language. Big visual / UX redesign is a separate later phase.

## Test Harness assessment

> Assistant Harness，我刚才看了一下，用起来好像没什么问题。我可以连接到相关服务，然后让它去打招呼。

**Status**: ✅ ratified by Human. MVTH (#17) is acceptable for now. The Profile picker / Spawn / Send / Conversation flow works. (Just the model name on the dropdown needs the 4.6 → 4.7 fix.)

## Source

Human's verbatim review on 2026-05-03 in the orchestration-v1 development conversation. Recorded as input for Phase 3 (#18) Full UI Rewrite.
