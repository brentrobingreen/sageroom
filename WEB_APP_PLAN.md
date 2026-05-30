# Brain Builder Web App — Full Implementation Plan

All tasks must be executed against the rules in CLAUDE.md.
Complete tasks in phase order. Do not start a phase until all prior-phase tasks are done.

---

## PRE-BUILD DECISIONS — Resolve before writing any code

These 8 decisions change the architecture. Wrong answers cost days.

1. **Product name** — "Brain Builder" is the pipeline. The consumer app needs its own brand. Candidates: Council, Consilium, The Brains, Mentors, Luminary. This affects domain, Stripe product, legal entity, all copy.
2. **Free tier policy** — (a) no free trial, (b) N free messages then paywall, (c) 7-day trial then $20/month. Drives the entire auth/billing flow.
3. **Launch brain list** — Which 5–10 thinkers ship at launch? Must be decided so the pipeline can be run and brains manually reviewed before development starts.
4. **Group chat limits** — Max brains per group (recommend 4). Max group sessions per user per day (recommend 2). Max exchanges per group session (recommend 15). These drive schema and frontend design.
5. **User-generated brains** — Can paying users upload their own PDFs and run the pipeline? Yes = major scope addition (async job queue, file uploads). No = founder-curated library only. Defer to v2 unless explicitly in scope.
6. **Conversation persistence** — Keep forever, or expire after N days? Affects storage costs and GDPR deletion requirements.
7. **Monthly AI cost cap per user** — Recommend $8–10/user/month. This is the server-side hard ceiling enforced before every Claude call.
8. **Legal jurisdiction** — Where is the business registered? Determines Terms of Service and Privacy Policy template (US, UK, EU each differ).

---

## Phase 0 — Foundation Setup

**0.1** Resolve all 8 pre-build decisions. Write answers down. Do not proceed until done.

**0.2** Choose and register product domain.

**0.3** Create Supabase project. Note: project URL, anon key, service role key. Enable email/password auth. Disable phone auth.

**0.4** Create Stripe account. Create subscription product at $20/month recurring. Note the `price_xxx` ID. Create webhook endpoint pointing to `https://<domain>/webhooks/stripe`. Subscribe to: `checkout.session.completed`, `customer.subscription.deleted`, `customer.subscription.updated`, `invoice.payment_failed`. Note webhook signing secret.

**0.5** Create Railway project. Create `web-prod` and `web-staging` services. Add environment variables to both: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `MAX_MONTHLY_AI_COST_USD`, `MAX_DAILY_GROUP_SESSIONS`, `ALLOWED_ORIGIN`, `ADMIN_EMAILS`. Staging uses Stripe test-mode keys.

**0.6** Set Anthropic monthly spend cap in console (e.g. $50 until there is revenue). Non-optional.

**0.7** Scaffold `web/` directory with all empty files matching the architecture in CLAUDE.md.

**0.8** Write `web/requirements.txt`: `fastapi`, `uvicorn[standard]`, `anthropic>=0.40.0`, `supabase`, `stripe`, `python-dotenv`, `slowapi`, `httpx`, `pytest`, `pytest-asyncio`.

**0.9** Write `Procfile`: `web: uvicorn web.main:app --host 0.0.0.0 --port $PORT --workers 2`

**0.10** Build and deploy "hello world" FastAPI app to Railway staging. `GET /health` returns `{"status": "ok"}`. Verify Railway builds, deploys, and responds before any real code is written.

---

## Phase 1 — Database Schema

**1.1** Write `web/migrations/001_initial.sql` with tables:
- `brains` (id, slug, display_name, tagline, category, avatar_url, is_active, created_at)
- `user_subscriptions` (id, user_id, stripe_customer_id, stripe_subscription_id, status, current_period_end)
- `conversations` (id, user_id, brain_slug, title, created_at, last_message_at)
- `messages` (id, conversation_id, user_id, role, content, created_at)
- `group_sessions` (id, user_id, brain_slugs[], question, status, created_at, completed_at)
- `group_responses` (id, session_id, brain_slug, round, content, created_at)
- `group_synthesis` (id, session_id, content, created_at)
- `ai_usage_log` (id, user_id, conversation_id, group_session_id, brain_slug, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, created_at)
- `user_monthly_costs` (id, user_id, month_year, total_cost_usd, updated_at) — unique on (user_id, month_year)

**1.2** Add RLS policies to `001_initial.sql`. Every table enabled. Key rule: `user_id = auth.uid()` on all user-owned tables. `brains` is SELECT-only for authenticated users.

**1.3** Add indexes to `001_initial.sql`: `conversations(user_id, last_message_at DESC)`, `messages(conversation_id, created_at ASC)`, `ai_usage_log(user_id, created_at DESC)`, `user_monthly_costs(user_id, month_year)`.

**1.4** Apply migration in Supabase SQL editor. Verify all tables, RLS, indexes exist.

**1.5** Write `web/migrations/002_seed_brains.sql`. Insert row for Tony Robbins (and all other launch brains). Commit.

---

## Phase 2 — Core Services

**2.1** Write `web/brain_registry.py`. Loads all `brains/*/brain.md` and `brains/*/system_prompt.md` at module import time into `BRAIN_REGISTRY: dict[str, Brain]`. The combined context string must be assembled identically every call (same bytes, same separator) for cache correctness. `get_brain(slug)` raises `KeyError` on miss.

**2.2** Write `web/db.py`. Module-level Supabase client using service-role key. `get_supabase()` function. Never exposes anon key.

**2.3** Write `web/models.py`. Pydantic v2 models: `ChatRequest`, `GroupChatRequest` (with 2–4 brain validator), `ConversationOut`, `MessageOut`, `BrainOut`, `SubscriptionStatusOut`, `UsageStatsOut`.

**2.4** Write `web/services/cost_service.py`:
- Named pricing constants for Sonnet 4.6 (input, output, cache write, cache read per million tokens). Verify against current Anthropic pricing page.
- `async log_usage(user_id, usage_obj, ...)` — computes USD cost, writes to `ai_usage_log`, upserts `user_monthly_costs`.
- `async check_cost_cap(user_id)` — raises `HTTPException(429)` if over cap.
- `async get_monthly_cost(user_id, month_year) -> float`.

**2.5** Write `web/services/brain_service.py`:
- `get_all_brains() -> list[BrainOut]` — metadata only, no brain doc content.
- `get_brain_or_404(slug) -> Brain` — wraps registry, raises `404` on miss.

**2.6** Write `web/services/billing_service.py`:
- `async create_checkout_session(user_id, email) -> str` — Stripe checkout URL.
- `async create_portal_session(user_id) -> str` — Stripe portal URL.
- `async get_subscription_status(user_id) -> SubscriptionStatusOut`.
- `async is_subscriber(user_id) -> bool`.
- `async handle_checkout_complete(session)`, `handle_subscription_deleted(sub)`, `handle_subscription_updated(sub)`, `handle_payment_failed(invoice)`.

**2.7** Write `web/services/chat_service.py`:
- `async stream_chat(user_id, brain_slug, message, conversation_id, history) -> AsyncGenerator[str, None]`
- Assembles Anthropic messages: combined context as first user turn with `cache_control: ephemeral`, then conversation history, then new message.
- Streams via `anthropic.AsyncAnthropic().messages.stream()`.
- Yields `data: {"type": "token", "text": chunk}` SSE strings.
- After stream completes: calls `cost_service.log_usage`, saves assistant message to DB, updates `conversations.last_message_at`.
- On error: yields `data: {"type": "error", "message": "..."}`.

**2.8** Write `web/services/group_chat_service.py`:
- `async run_group_chat(session_id, user_id, brain_slugs, question)`
- Round 1: `asyncio.gather` all brain calls in parallel. Each call uses full combined context with `cache_control`. Collect full responses (not streamed).
- Round 2: each brain receives all other brains' Round 1 responses. `asyncio.gather` again.
- Synthesis: single Claude call with neutral facilitator prompt weaving all Round 2 responses.
- Saves all responses to DB. Updates `group_sessions.status` at each stage.

---

## Phase 3 — FastAPI Routes

**3.1** Write `web/main.py`. App factory with: lifespan (loads brain registry, logs count), static file mount, all routers at `/api`, CORS middleware (env-var origins), slowapi middleware, `RateLimitExceeded` handler.

**3.2** Write auth dependency in `web/routers/auth.py`. `get_current_user` FastAPI dependency: extracts bearer token, calls `supabase.auth.get_user(token)`, returns user dict, raises `401` on failure.

**3.3** Write `web/routers/brains.py`:
- `GET /api/brains` — all active brains. Auth required.
- `GET /api/brains/{slug}` — single brain metadata. Auth required.

**3.4** Write `web/routers/chat.py`:
- `GET /api/conversations` — user's conversation list, ordered by `last_message_at` DESC.
- `GET /api/conversations/{id}/messages` — messages for one conversation.
- `DELETE /api/conversations/{id}` — delete conversation and messages.
- `POST /api/chat/stream` — main chat endpoint. Auth + subscription check + cost cap check. Returns `StreamingResponse(content-type: text/event-stream)`. Creates conversation if none exists. Loads last 20 messages as history. Saves user message before streaming. Calls `chat_service.stream_chat`.

**3.5** Write `web/routers/group_chat.py`:
- `GET /api/group-sessions` — user's session list.
- `GET /api/group-sessions/{id}` — full session with all responses and synthesis.
- `POST /api/group-chat` — initiate session. Auth + subscription + daily limit check. Runs synchronously (returns when complete) if typically < 60 seconds; otherwise use `BackgroundTasks` and return `session_id` immediately for polling.
- `GET /api/group-chat/{id}/status` — status polling endpoint.

**3.6** Write `web/routers/billing.py`:
- `GET /api/billing/status` — subscription status, period end, monthly AI cost.
- `POST /api/billing/checkout` — Stripe checkout URL. Idempotent (return `already_subscribed` if active).
- `POST /api/billing/portal` — Stripe portal URL.

**3.7** Write `web/routers/webhooks.py`:
- `POST /webhooks/stripe` — raw body endpoint. Verify signature first. Route to billing service handlers. Return `200` on success, `400` on bad signature. Note: this route must NOT have JWT auth middleware.

**3.8** Write `web/routers/admin.py`:
- Gate all routes: check `current_user.email in ADMIN_EMAILS`.
- `GET /api/admin/costs` — monthly AI spend per user.
- `GET /api/admin/usage` — brain usage counts.
- `GET /api/admin/subscribers` — count of active subscribers.

---

## Phase 4 — Frontend

**4.1** Write `web/static/css/main.css`. CSS custom properties for colours, spacing, typography. Mobile-first base styles. Media queries at 768px and 1200px. Components: `.card`, `.btn`, `.btn-primary`, `.btn-ghost`, `.input`, `.spinner`, `.brain-card`, `.message-bubble-user`, `.message-bubble-ai`, `.sidebar`. Dark mode via `prefers-color-scheme`.

**4.2** Write `web/static/js/auth.js`. Supabase auth init (load SDK from CDN). `signUp`, `signIn`, `signOut`, `getSession`, `getToken`. Auth state change listener. `requireAuth()` — call at top of every protected page to redirect unauthenticated users.

**4.3** Write `web/static/js/api.js`. `apiFetch(path, options)` — auto-adds `Authorization: Bearer` header, handles 401 (redirect to login), handles 429 (user-friendly message). `streamChat(brainSlug, message, conversationId, onToken, onDone, onError)` — EventSource wrapper. All other API call functions.

**4.4** Write `web/static/index.html` (landing page). Hero with pitch and sign-up CTA. "How it works" 3-step section. Brain library preview grid. Pricing ($20/month). Legal disclaimer. Footer with Terms and Privacy links. Sign-up/sign-in modal using Supabase JS.

**4.5** Write `web/static/chat.html`. Layout: collapsible left sidebar (brain list + conversation history + "New chat"), main chat area (transcript + message input), top bar (brain name + avatar). Paywall overlay shown when not subscribed. Full page responsive — sidebar collapses to bottom sheet on mobile.

**4.6** Write `web/static/js/chat.js`. Init: `requireAuth()`, load brains, load conversations, restore last brain from localStorage. `selectBrain(slug)`, `selectConversation(id)`, `sendMessage()`. SSE streaming renders tokens progressively. Optimistic user bubble (append immediately before response arrives). Basic markdown rendering (bold, italic, code blocks). Keyboard shortcuts: Enter to send, Shift+Enter for newline, Escape to abort stream.

**4.7** Write `web/static/group.html`. Brain selector grid (checkboxes, min 2 max 4 enforced). Question textarea. "Convene the council" submit button. Results area with per-brain tabs for Round 1 and Round 2, prominent synthesis section. Past sessions list.

**4.8** Write `web/static/js/group.js`. Brain selection toggle UI with 2–4 limit enforcement. Submit handler: calls `startGroupChat`, shows loading state with per-brain indicators. Polls `getGroupSession(id)` every 2 seconds until `status = complete` or `failed`. Renders all rounds and synthesis when done.

**4.9** Write `web/static/account.html`. Subscription status (plan, renewal date). "Subscribe" or "Manage subscription" button. Monthly usage stats (AI cost, messages, group sessions). Sign out button.

**4.10** Add brain avatars to `web/static/images/`. One image per brain, 400×400px. Confirm usage rights for any real photographs.

**4.11** Write `web/static/404.html` and `web/static/500.html`. Consistent with design. Link back to home.

---

## Phase 5 — Auth Flow

**5.1** Sign-up flow: email + password → `supabase.auth.signUp()` → handle email confirmation state → redirect to `chat.html`.

**5.2** Sign-in flow: email + password → `supabase.auth.signInWithPassword()` → redirect to `chat.html`. Handle "Invalid credentials" with clear error message.

**5.3** Sign-out: `supabase.auth.signOut()` → clear session → redirect to landing.

**5.4** Auth state on page load: `requireAuth()` in every protected page's JS init. Redirects to landing with `?redirect=<path>` so user lands back after sign-in.

**5.5** Verify token refresh: test a session open for over 1 hour still works without re-login.

---

## Phase 6 — Billing Integration

**6.1** Stripe Checkout flow: click subscribe → `POST /api/billing/checkout` → redirect to Stripe URL. On success Stripe redirects to `account.html?payment=success`.

**6.2** Handle `?payment=success` on account page: show confirmation banner, reload subscription status (wait up to 5 seconds for webhook to fire).

**6.3** Stripe Customer Portal: "Manage subscription" → `POST /api/billing/portal` → redirect to Stripe Portal.

**6.4** Handle `customer.subscription.deleted` webhook: set status `cancelled`, next chat attempt shows paywall.

**6.5** Handle `invoice.payment_failed` webhook: set status `past_due`, show payment failure banner on chat page with link to Stripe Portal.

**6.6** Test full billing cycle in Stripe test mode: subscribe → chat works → cancel → chat blocked → resubscribe → chat works again.

---

## Phase 7 — Cost Controls

**7.1** Enforce cost cap in `stream_chat` before first yield. Returns SSE error event with `monthly_cost_cap_exceeded` type. Frontend shows human-readable message with reset date.

**7.2** Verify usage logging captures `cache_read_tokens` and `cache_write_tokens` correctly and applies the correct (discounted) rate.

**7.3** Verify Anthropic pricing constants match current pricing page. Do this check the day before launch.

**7.4** Enforce group chat daily limit in group chat endpoint before initiating session.

**7.5** Verify admin cost endpoint returns useful data by running a few test conversations and checking the numbers match.

---

## Phase 8 — Tests

**8.1** `test_cost_service.py`: cost calculation correctness, cap enforcement (under/over), monthly rollover.

**8.2** `test_chat_service.py`: happy path streaming, unknown brain 404, context assembled identically on repeated calls (cache key test).

**8.3** `test_billing_service.py`: checkout idempotency, subscription status transitions, `is_subscriber` returns correct boolean.

**8.4** `test_group_chat_service.py`: Round 1 parallelism verified, Round 2 includes other brains' responses, daily limit enforcement.

**8.5** `test_endpoints.py`: auth required on all protected routes, subscription required on chat routes, webhook signature verification, group chat brain count validation (422 on 5 brains).

**8.6** Run full test suite. All tests pass before proceeding.

---

## Phase 9 — Brain Library

**9.1** Finalise launch brain list (from pre-build decision 3). Minimum 5 brains across categories.

**9.2** Run `python pipeline.py "<Name>"` for each brain. Verify `brain.md` is at least 10,000 characters. Verify `system_prompt.md` references correct frameworks.

**9.3** Manually review every `brain.md` before launch. Check for: hallucinated quotes, misattributed ideas, factual errors. A brain that fails this check does not ship.

**9.4** Write `web/brain_quality_checklist.md`: one row per brain (slug, verified quotes count, frameworks count, manual review status, reviewer, date).

**9.5** Insert all reviewed brains into Supabase `brains` table with `is_active = true`.

**9.6** Add avatar image for each brain to `web/static/images/`.

---

## Phase 10 — Production Readiness

**10.1** Adjust `.gitignore` to confirm `brains/*/brain.md` and `brains/*/system_prompt.md` are NOT excluded (they ship in the repo). Add `brains/*/test_results.md` to gitignore.

**10.2** Configure Railway health check at `/health`. Must respond within 5 seconds.

**10.3** Configure Railway auto-deploy: `main` → prod, `staging` → staging.

**10.4** Verify all production environment variables are set in Railway prod service. Walk through every `os.environ` reference in the codebase.

**10.5** Configure logging in `main.py`: structured format, log all HTTP requests (method, path, status, duration), log all Claude API calls (brain slug, tokens, cost). Never log message content.

**10.6** Configure custom domain on Railway. Verify HTTPS (Let's Encrypt auto-provisioned).

**10.7** Update Supabase redirect URLs in Auth settings to production domain.

**10.8** Update Stripe webhook endpoint from staging to production URL. Test-trigger an event from Stripe dashboard to confirm receipt.

**10.9** Set CORS `ALLOWED_ORIGIN` to production domain.

---

## Phase 11 — Legal Pages

**11.1** Write `web/static/terms.html`. Must cover: subscription terms, acceptable use, AI disclaimer (not professional advice), IP ownership, account termination.

**11.2** Write `web/static/privacy.html`. Must cover: data collected, how used, third-party processors (Anthropic, Supabase, Stripe, Railway), retention and deletion, GDPR rights if serving EU users, contact email.

**11.3** Implement `DELETE /api/account` endpoint: cancels subscription, deletes all user data, deletes Supabase auth user. Required for GDPR compliance.

**11.4** Add cookie consent notice to landing page (minimal — functional cookies only, no analytics at launch).

---

## Phase 12 — Mobile and Polish

**12.1** Test every page on iOS Safari and Android Chrome at 375px. Fix: font sizes, tap targets, keyboard behaviour, layout breaks.

**12.2** Mobile sidebar: hidden by default below 768px, toggled by hamburger button. Brain selector on mobile: full-screen overlay or bottom sheet.

**12.3** Chat scroll behaviour: auto-scroll to bottom as tokens stream. Pause if user scrolls up. Resume when user scrolls back to bottom.

**12.4** Copy button on AI message bubbles. `navigator.clipboard.writeText()` with "Copied!" confirmation.

**12.5** Streaming abort: Escape key or "Stop" button closes EventSource and re-enables input. Partial response stays visible.

**12.6** All empty states implemented: no conversations, no brains selected for group, group session pending, no past group sessions.

**12.7** Page `<title>` and `<meta description>` on every page. Open Graph tags on landing page.

**12.8** Favicons: `favicon.ico`, `apple-touch-icon.png`.

---

## Phase 13 — Monitoring

**13.1** Railway alerts set: CPU > 80%, memory > 80%, error rate > 5%.

**13.2** Save `web/migrations/queries/daily_cost_report.sql`: total users, active subscribers, AI spend today, AI spend this month, top 5 most expensive users this month, group sessions today. Run each morning.

**13.3** Stripe dashboard: enable email alerts for payment failures.

---

## Phase 14 — Launch Preparation

**14.1** End-to-end smoke test on production: sign up → verify email → see paywall → subscribe → single brain chat → group chat (2 brains) → account page → manage subscription → cancel → chat blocked → resubscribe → chat works. Fix all failures.

**14.2** Load test: 5 concurrent group chat sessions with 4 brains each. Verify no OOM or timeout on Railway.

**14.3** Verify prompt caching is working: after test conversations, check Anthropic API dashboard for `cache_read_tokens` > 0. If near zero, the cache key assembly is broken.

**14.4** Security checklist: JWT on every endpoint ✓, brain slugs allowlisted ✓, RLS active ✓, Stripe webhook verified ✓, rate limits active ✓, CORS restricted ✓, no secrets in frontend JS ✓.

**14.5** Check all links: Terms, Privacy, About, social links all resolve.

**14.6** Write launch announcement copy: 1-paragraph pitch, 3 bullets, pricing, CTA.

**14.7** Tag `v1.0.0` in git on the production commit.

---

## Phase 15 — Post-Launch (Week 1)

**15.1** Monitor Railway logs daily: 500 errors, 429 hits, slow requests.

**15.2** Check Anthropic API cost daily. If daily cost exceeds ceiling, identify user and investigate.

**15.3** Monitor Stripe dashboard daily: payment failures, refund requests.

**15.4** Read all user feedback. The most valuable week-1 signal is qualitative.

**15.5** Plan v1.1 based on feedback. Likely candidates: Google OAuth, conversation search, more brains, group chat streaming, user-uploaded custom brains.

---

## Known Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Group chat cost spiral (heavy users) | High | Daily session cap + monthly cost cap, both enforced server-side |
| Prompt cache warming lag (5-min TTL) | Medium | Monitor cache hit rate post-launch; economics worsen at low usage frequency |
| Brain quality (hallucinated quotes/frameworks) | High | Manual review of every brain before `is_active = true` |
| Copyright/likeness risk on living public figures | Medium | "Applying frameworks" framing, clear AI disclaimer, avoid "chat with X" language |
| Anthropic API rate limits under fan-out load | Medium | Retry with exponential backoff on 429 from Anthropic |
| Railway memory pressure under concurrent group chats | Low-Medium | Start with 512MB, load test before launch, increase if needed |
| Supabase free tier pausing inactive projects | High | Upgrade to Supabase Pro ($25/mo) before launch |
