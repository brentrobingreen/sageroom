-- Extend group_sessions status constraint to support conversational session states
alter table public.group_sessions drop constraint if exists group_sessions_status_check;
alter table public.group_sessions add constraint group_sessions_status_check
  check (status in ('pending','active','round1','round2','synthesis','synthesized','complete','failed'));
