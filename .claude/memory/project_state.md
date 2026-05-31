---
name: project-state
description: "Current implementation phase, what's complete, and what's next for Sageroom"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6ce57e75-8de0-4a30-a5d5-29ee8ec7095b
---

## Status as of 2026-05-31

Phases 0–12 complete. Phase 13 (monitoring) not yet started. Group chat underwent two complete redesigns this session.

**Last commit:** 6d5f027 — "Redesign group chat as council deliberation"

## What changed this session

### Bug fixes
- Group sessions status constraint updated (migration 006) to allow 'active', 'synthesized'
- `api.js` now re-exports `getToken` for group.js to import
- `/api/brains` made public — fixes infinite 401 reload loop on landing page
- `api.js` 401 handler: only calls signOut if token existed (session expired), not unauthenticated

### Brain prompt tuning (all 3 active brains)
- Removed "Lead with frameworks" and "Diagnose before prescribing" instructions
- Added conversational rules: 2–3 paragraphs max, no headers, one question per reply
- `chat_service.py` max_tokens: 2048 → 600

### Group chat: two full redesigns
**First redesign** (conversational group chat):
- New `group_messages` table (migration 005)
- SSE streaming with lead/reactor pattern
- Lead brain: 2–3 sentences + one question (120 tokens)
- Reactor brains: 1–2 sentence reaction, no question (60 tokens)
- Therapist approach: ask questions first before giving advice
- Emojis added to prompts

**Second redesign** (council deliberation — final):
- Completely replaced group chat with structured deliberation flow
- Phase 1: Setup (select thinkers + describe situation)
- Phase 2: Context (facilitator asks 0–2 clarifying questions if situation is too broad)
- Phase 3: Deliberating (each thinker gives 3–4 sentence brief, cards fill sequentially)
- Phase 4: Results (perspectives + streaming synthesis shown inline; follow-up triggers new cycle)
- New endpoints: POST /assess, POST /context, POST /deliberate, POST /followup
- Synthesis always auto-generated and shown

### Local dev setup completed
- .env created with all credentials (gitignored)
- Supabase project created (Sydney, ref: pdaudcjbckgmlsmzqrll), all 6 migrations applied
- Stripe product + AUD $20/month price created (test mode)
- Stripe webhook listener runs separately

## What's next

**Phase 13 — Monitoring** (WEB_APP_PLAN.md):
- 13.1: Railway alerts (CPU >80%, memory >80%, error rate >5%)
- 13.2: `web/migrations/queries/daily_cost_report.sql`
- 13.3: Stripe email alerts for payment failures

**Phase 14 — Launch Preparation**

**Known issues to fix:**
- Stripe webhook not activating subscriptions after checkout — subscription stays "inactive" after test payment. Needs debugging in `billing_service.py` / `webhooks.py`.
- Group chat tests (`test_group_chat_service.py`) are broken — test `run_group_chat` which no longer exists. Need rewrite.
- `supabase/` directory is untracked (auto-created by CLI link) — should add to .gitignore or commit

**Product decisions made this session:**
- Group chat (live back-and-forth) was replaced with council deliberation (structured briefing + synthesis)
- Reason: the synthesis was the valuable part, not the chat; managing 3 simultaneous threads was cognitively overwhelming
- The single 1-on-1 chat is the core product; council deliberation is the "multiple perspectives" tool
