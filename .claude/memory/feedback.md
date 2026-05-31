---
name: feedback
description: Confirmed approaches and corrections from testing sessions
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 6ce57e75-8de0-4a30-a5d5-29ee8ec7095b
---

## Brain responses were too long and essay-like

Removing "Lead with frameworks" and "Diagnose before prescribing" from system prompts fixed it. The conversational style rules (2–3 paragraphs, no headers, one question) are the right approach.

**Why:** Those two instructions caused Claude to produce structured essays. Validated after fix applied.

**How to apply:** If brain response quality comes up again, check the system prompt for instructions that encourage completeness over conversation.

---

## Group chat (live back-and-forth) is not the right model

The synthesis is the valuable output — not managing a live multi-threaded conversation. Replaced with council deliberation: structured phases (context → perspectives → synthesis).

**Why:** "I'm struggling with the 3 opinions running at once." Even with lead/reactor pattern and therapist approach, the live chat format was cognitively overwhelming. The synthesis was always what users found valuable.

**How to apply:** Don't revert to live group chat. The deliberation model is the right one. Follow-up questions are handled by new deliberation cycles, not chat threads.

---

## User prefers doing over explaining

When setup is required, find a way to do it programmatically rather than giving instructions.

**Why:** "can you do this for me? if not step me through how to do this myself" — confirmed preference for autonomous action. Used CLI tools (stripe CLI, supabase CLI) to do everything programmatically.

**How to apply:** Always attempt the automated path first. Only fall back to instructions if genuinely blocked.

---

## Daily session limits block testing — backdate sessions rather than disabling limits

When the user hit the daily group session limit during testing, the fix was to backdate today's sessions in Supabase rather than removing the limit from code.

**Why:** Keeps the production safety guardrail intact while unblocking testing.

**How to apply:** Use the Supabase API to backdate `group_sessions.created_at` for the test user rather than changing `MAX_DAILY_GROUP_SESSIONS`.
