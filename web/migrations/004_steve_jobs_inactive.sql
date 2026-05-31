-- Steve Jobs brain failed quality review — insufficient source material.
-- Set inactive until re-collected and re-reviewed in v1.1.
-- Run this after 002_seed_brains.sql.

update public.brains set is_active = false where slug = 'steve_jobs';
