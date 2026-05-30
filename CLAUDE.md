# CLAUDE.md — Sageroom

This file provides guidance to Claude Code when working in this repository.
Every task must be evaluated against the rules in this file before execution.

---

## Project overview

**Sageroom** — a web app where users pay to chat with AI versions of famous thinkers, one-on-one or in group deliberation sessions.

- **Decisions:** `DECISIONS.md` — all founder decisions locked, do not revisit without documented reason
- **Plan:** `WEB_APP_PLAN.md` — 15-phase numbered implementation plan, complete phases in order

**GitHub:** https://github.com/brentrobingreen/sageroom
**Stack:** FastAPI, Supabase, Stripe, Anthropic API, deployed on Railway
**Brain files source:** `/Users/brentgreen/brain_builder/brains/` (pipeline runs separately)

---

## Running locally

```bash
cd web && uvicorn main:app --reload --port 8000
```

---

## ARCHITECTURE RULES

**A1.** Backend is Python/FastAPI. Frontend is vanilla HTML/CSS/JS. No React, Vue, Angular, Svelte. No npm. No build step. No CSS frameworks. No exceptions.

**A2.** The web app reads pre-built `brain.md` and `system_prompt.md` files from disk. It never calls the pipeline agents at runtime.

**A3.** Brain files are loaded into memory at app startup and cached in a `BRAIN_REGISTRY` dict. Never read `brain.md` from disk inside a request handler.

**A4.** SSE streaming is non-negotiable for chat. Every Claude response streams via Server-Sent Events. No polling, no wait-for-full-response.

**A5.** Group chat fan-out uses `asyncio.gather`. Round 1 calls run in parallel. Round 2 runs after all Round 1 responses complete. Never serial.

**A6.** Prompt caching on every Claude call. The combined `[system_prompt + brain.md]` is the cache anchor, assembled identically every call by `BrainRegistry`. Any variation defeats caching.

**A7.** Supabase service-role key is server-side only. The anon key or any secret never appears in frontend JS. All authenticated operations go through FastAPI endpoints.

**A8.** One SQL migration file per schema change. Files live in `web/migrations/` as `001_initial.sql`, `002_xxx.sql`, etc. Never alter the schema in Supabase console without writing the migration file first.

**A9.** All secrets come from environment variables. Never hardcode keys. `.env` is for local dev only and is gitignored.

---

## SECURITY RULES

**S1.** Verify JWT on every protected endpoint. Use a FastAPI `get_current_user` dependency that raises `401` on invalid/missing token.

**S2.** Never trust user-supplied brain slugs without allowlisting against `BRAIN_REGISTRY`. Unknown slug = `404`, not a filesystem lookup.

**S3.** Row-Level Security on all Supabase tables. `conversations`, `messages`, `group_sessions`, `ai_usage_log` are readable/writable only by their owner.

**S4.** Stripe webhook signature verification before processing any event. Unverified events → `400`.

**S5.** Rate limiting on all API endpoints via `slowapi`. Chat: 20 req/min per user. Group chat: 5 req/min per user. Auth: 10 req/min per IP.

**S6.** No PII in logs. Never log JWT tokens, email addresses, message content, or API keys.

**S7.** CORS restricted to known origins. Never `allow_origins=["*"]`.

**S8.** Input length limits enforced in both Pydantic validators and frontend JS. Chat message max 2,000 characters.

---

## COST CONTROL RULES

**C1.** Per-user monthly AI cost cap enforced server-side before every Claude call. Cap is $8.00 USD (from DECISIONS.md). Configurable via `MAX_MONTHLY_AI_COST_USD` env var. Over cap → `429`.

**C2.** Log actual token usage (input, output, cache read, cache write) after every Claude call. Store in `ai_usage_log` and update `user_monthly_costs`.

**C3.** Group chat hard limits: max 4 brains per session, max 2 group sessions/user/day via `MAX_DAILY_GROUP_SESSIONS`.

**C4.** Anthropic pricing constants are named module-level constants in `cost_service.py`. One place to update when pricing changes.

**C5.** Set Anthropic monthly spend cap in console before going live. Non-optional.

---

## GIT WORKFLOW — MANDATORY

**Commit and push after every meaningful change. No batching.**

1. Stage files by name — never `git add .` or `git add -A`
2. Imperative-mood commit message under 72 chars
3. Push immediately: `git push origin master`
4. Commit after every atomic unit of work (one endpoint, one schema change, one component)

---

## CODE QUALITY RULES

**Q1.** One file per concern. Routers call services. Services call the database and Anthropic API. Routers never touch the database directly.

**Q2.** All FastAPI handlers are `async def`. All DB calls and Anthropic calls use async clients. Never block the event loop.

**Q3.** Type annotations on all function signatures. No bare `Any` except where genuinely unavoidable.

**Q4.** No commented-out code in commits. Delete dead code — use git history for recovery.

**Q5.** No comments unless the WHY is non-obvious. Never comment what the code does. Only hidden constraints, workarounds, or subtle invariants.

**Q6.** No premature abstraction. Three similar lines is better than a helper function. No helpers for hypothetical future use.

---

## PRODUCT AND UX RULES

**P1.** Mobile first. Design at 375px. Desktop is an enhancement. Test every page on mobile before marking a task done.

**P2.** Stream Claude responses. Show typing indicators the moment a request fires. Never make users wait for a complete response.

**P3.** Every screen that can be empty has a designed empty state with a clear call to action. Blank screens are not acceptable.

**P4.** Paywall is honest and immediate. Show pricing clearly. No dark patterns.

**P5.** Error messages are written for humans. "An error occurred" is never acceptable. Every user-facing error is a complete sentence with context and a next step.

**P6.** No spinner without a timeout. If SSE hasn't produced its first token in 10 seconds, show an error and allow retry.

**P7.** The product never claims to be the real person. All copy uses "applying [person]'s frameworks" not "talking to [person]". The disclaimer "This is an AI applying publicly documented frameworks, not the actual person" is present in the UI.

---

## TESTING RULES

**T1.** Every service function has a unit test in `web/tests/`. Use `pytest` with `pytest-asyncio`. Mock Anthropic and Supabase clients — no real API calls in tests.

**T2.** Every API endpoint is integration-tested for: happy path, auth failure (401), invalid input (422), cost cap (429 on chat routes).

**T3.** Run `pytest web/tests/` before every push. All tests must pass.

**T4.** Before marking any task complete: test the golden path AND at least one error case.

**T5.** Test every UI page on mobile viewport before marking done.

---

## WEB APP ARCHITECTURE

```
web/
├── main.py                  # FastAPI app factory, startup, middleware
├── models.py                # Pydantic request/response schemas
├── db.py                    # Supabase client (server-side only)
├── brain_registry.py        # Loads brain files at startup, BrainRegistry class
├── routers/
│   ├── auth.py              # get_current_user dependency
│   ├── brains.py            # GET /api/brains, GET /api/brains/{slug}
│   ├── chat.py              # SSE chat, conversation management
│   ├── group_chat.py        # Group session management
│   ├── billing.py           # Stripe checkout, portal, status
│   ├── webhooks.py          # Stripe webhook handler
│   └── admin.py             # Usage and cost monitoring (admin only)
├── services/
│   ├── brain_service.py     # Brain metadata helpers
│   ├── chat_service.py      # Claude streaming, message persistence
│   ├── group_chat_service.py# Fan-out orchestration, round management
│   ├── billing_service.py   # Stripe integration, subscription state
│   └── cost_service.py      # Usage logging, cap enforcement, pricing
├── migrations/
│   ├── 001_initial.sql      # Full schema + RLS + indexes
│   └── 002_seed_brains.sql  # Seed Tony Robbins, Warren Buffett, Robin Sharma, Steve Jobs
├── tests/
│   ├── test_chat_service.py
│   ├── test_billing_service.py
│   ├── test_cost_service.py
│   ├── test_group_chat_service.py
│   └── test_endpoints.py
└── static/
    ├── index.html           # Landing page
    ├── chat.html            # Single-brain chat
    ├── group.html           # Group chat
    ├── account.html         # Billing and settings
    ├── terms.html
    ├── privacy.html
    ├── css/main.css         # Shared design system
    ├── js/
    │   ├── auth.js          # Supabase auth, session management
    │   ├── api.js           # API wrapper, SSE streaming
    │   ├── chat.js          # Single-brain chat logic
    │   └── group.js         # Group chat logic
    └── images/              # Brain avatars
```
