# Sageroom — Founder Decisions

All pre-build decisions locked. Do not revisit these without a documented reason.

---

| # | Decision | Answer |
|---|---|---|
| 1 | Product name | **Sageroom** |
| 2 | Free tier policy | **10 free single-brain messages. No group chat on free tier.** |
| 3 | Launch brain list | **Tony Robbins, Warren Buffett, Robin Sharma, Steve Jobs** |
| 4 | Group chat limits | **Max 4 brains per session. Max 2 group sessions/user/day. Max 15 exchanges/session.** |
| 5 | User-generated brains | **No — founder-curated library only at launch. Defer to v2.** |
| 6 | Conversation persistence | **Forever. No expiry.** |
| 7 | Monthly AI cost cap per user | **$8.00 USD/user/month** (enforced server-side before every Claude call) |
| 8 | Legal jurisdiction | **Australia** — Privacy Policy references Australian Privacy Principles (APPs). Terms under Australian Consumer Law. |

---

## Implications

**Free tier (10 messages):**
- Tracked in `user_subscriptions.free_messages_used` column
- Single-brain chat only — group chat requires subscription
- Counter resets never (lifetime cap, not monthly) — simplest implementation
- When cap hit: paywall shown with clear pricing

**AI cost cap ($8/user/month):**
- Enforced in `cost_service.check_cost_cap()` before every Claude call
- Resets on the 1st of each UTC month
- User sees: "You've reached your AI usage limit for this month. It resets on [date]."
- Admin alert fires if any single user exceeds $6 in a month (early warning at 75%)

**Australian legal requirements:**
- Privacy Policy must reference Australian Privacy Principles (APPs) under the Privacy Act 1988
- Must include contact for privacy complaints
- Must disclose all third-party data processors (Anthropic, Supabase, Stripe, Railway)
- Notifiable Data Breaches scheme: notify OAIC and affected users within 30 days of eligible breach
- Terms must comply with Australian Consumer Law (ACL) — no unfair contract terms
- Subscription refund policy must comply with ACL consumer guarantees
- GST: if revenue exceeds AUD $75,000/year, must register for GST and charge 10% to Australian customers

**Conversation persistence (forever):**
- No expiry logic needed — simplifies the schema and backend
- GDPR/Privacy Act right to deletion still applies — `DELETE /api/account` must wipe all conversations
- Storage cost at scale: estimated 1KB per message × 200 messages/user/month = 200KB/user/month — negligible on Supabase
