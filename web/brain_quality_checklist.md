# Brain Quality Checklist

One row per brain. All fields must be filled before `is_active = true` in Supabase.

| Brain | Slug | Char count | Sources | Frameworks | Manual review | Reviewer | Date | Ship? |
|---|---|---|---|---|---|---|---|---|
| Tony Robbins | tony_robbins | 53,855 | 25 | RPM model, Six Human Needs, State management, Priming, Dickens Pattern, NAC | ✓ Reviewed — no hallucinated quotes found. Strong on peak performance and psychology frameworks. | Brent | 2026-05-31 | ✅ YES |
| Warren Buffett | warren_buffett | 36,541 | 4 | Value investing, Circle of competence, Mr. Market, Owner earnings, Economic moats, 20-slot punch card | ✓ Reviewed — factually strong. Investing principles consistent with his documented letters and interviews. Conservative language, no misattribution found. | Brent | 2026-05-31 | ✅ YES |
| Robin Sharma | robin_sharma | 22,442 | 5 | 5 AM Club, The 4 Focuses of Leaders, The 3 Commitments, Daily 5, Hero/History model | ✓ Reviewed — solid coverage of leadership and mastery frameworks. Thinner than Tony/Warren due to fewer sources, but passes minimum quality bar. Consider adding more sources in v1.1. | Brent | 2026-05-31 | ✅ YES |
| Steve Jobs | steve_jobs | N/A | 2 | N/A | ✗ FAILED — synthesiser produced 0 principles, 0 frameworks, 0 quotes. Source files were raw interview transcripts the extractor could not parse into structured content. Brain not built. | — | 2026-05-31 | ❌ NO — v1.1 |

---

## Review criteria

- [ ] `brain.md` is at least 10,000 characters
- [ ] `system_prompt.md` references the correct frameworks for that person
- [ ] No hallucinated quotes (verify any specific quotes against known sources)
- [ ] No misattributed ideas (framework is known to be associated with this person)
- [ ] Tone and framing is "applying frameworks", not "being the person"
- [ ] AI disclaimer is reflected in the system prompt

## Steve Jobs — action required for v1.1

Re-run the full pipeline with higher-quality sources:
- Stanford commencement speech transcript (well-structured)
- Walter Isaacson biography excerpts (PDF)
- Macworld keynote transcripts
- Internal Apple memos and letters

Command sequence:
```bash
cd /Users/brentgreen/brain_builder
python -m agents.collector "Steve Jobs"   # re-collect with better sources
python -m agents.extractor "Steve Jobs"
python -m agents.synthesiser "Steve Jobs"
python -m agents.writer "Steve Jobs"
```

Then copy to sageroom and complete this checklist.
