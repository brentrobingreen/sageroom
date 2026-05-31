-- Conversational group chat messages
-- Replaces the round-based group_responses model for new sessions

create table if not exists public.group_messages (
  id          uuid        default gen_random_uuid() primary key,
  session_id  uuid        references public.group_sessions(id) on delete cascade not null,
  brain_slug  text,                        -- null for user messages
  role        text        not null check (role in ('user', 'assistant')),
  turn        int         not null default 1,
  content     text        not null,
  created_at  timestamptz default now() not null
);

alter table public.group_messages enable row level security;

create policy "Users can access their own group messages"
  on public.group_messages for all
  using (
    session_id in (
      select id from public.group_sessions where user_id = auth.uid()
    )
  );

create index if not exists group_messages_session_created
  on public.group_messages(session_id, created_at asc);
