-- Sageroom initial schema
-- Run this in the Supabase SQL editor

-- ============================================================
-- TABLES
-- ============================================================

create table public.brains (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  display_name text not null,
  tagline text,
  category text,
  avatar_url text,
  is_active boolean default true,
  created_at timestamptz default now()
);

create table public.user_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  stripe_customer_id text unique,
  stripe_subscription_id text unique,
  status text not null default 'inactive',
  current_period_end timestamptz,
  free_messages_used integer not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  brain_slug text not null,
  title text,
  created_at timestamptz default now(),
  last_message_at timestamptz default now()
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz default now()
);

create table public.group_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  brain_slugs text[] not null,
  question text not null,
  status text not null default 'pending'
    check (status in ('pending','round1','round2','synthesis','complete','failed')),
  created_at timestamptz default now(),
  completed_at timestamptz
);

create table public.group_responses (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.group_sessions(id) on delete cascade,
  brain_slug text not null,
  round integer not null check (round in (1, 2)),
  content text,
  created_at timestamptz default now()
);

create table public.group_synthesis (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.group_sessions(id) on delete cascade,
  content text not null,
  created_at timestamptz default now()
);

create table public.ai_usage_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id),
  group_session_id uuid references public.group_sessions(id),
  brain_slug text,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  cache_read_tokens integer not null default 0,
  cache_write_tokens integer not null default 0,
  cost_usd numeric(10,6) not null default 0,
  created_at timestamptz default now()
);

create table public.user_monthly_costs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  month_year text not null,
  total_cost_usd numeric(10,4) not null default 0,
  updated_at timestamptz default now(),
  unique(user_id, month_year)
);

-- ============================================================
-- INDEXES
-- ============================================================

create index on public.conversations(user_id, last_message_at desc);
create index on public.messages(conversation_id, created_at asc);
create index on public.ai_usage_log(user_id, created_at desc);
create index on public.user_monthly_costs(user_id, month_year);
create index on public.group_sessions(user_id, created_at desc);
create index on public.user_subscriptions(user_id);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

alter table public.brains enable row level security;
alter table public.user_subscriptions enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.group_sessions enable row level security;
alter table public.group_responses enable row level security;
alter table public.group_synthesis enable row level security;
alter table public.ai_usage_log enable row level security;
alter table public.user_monthly_costs enable row level security;

-- brains: any authenticated user can read
create policy "brains_select" on public.brains
  for select to authenticated using (is_active = true);

-- user_subscriptions: own row only
create policy "subscriptions_select" on public.user_subscriptions
  for select using (auth.uid() = user_id);
create policy "subscriptions_insert" on public.user_subscriptions
  for insert with check (auth.uid() = user_id);
create policy "subscriptions_update" on public.user_subscriptions
  for update using (auth.uid() = user_id);

-- conversations: own rows only
create policy "conversations_select" on public.conversations
  for select using (auth.uid() = user_id);
create policy "conversations_insert" on public.conversations
  for insert with check (auth.uid() = user_id);
create policy "conversations_update" on public.conversations
  for update using (auth.uid() = user_id);
create policy "conversations_delete" on public.conversations
  for delete using (auth.uid() = user_id);

-- messages: own rows only
create policy "messages_select" on public.messages
  for select using (auth.uid() = user_id);
create policy "messages_insert" on public.messages
  for insert with check (auth.uid() = user_id);

-- group_sessions: own rows only
create policy "group_sessions_select" on public.group_sessions
  for select using (auth.uid() = user_id);
create policy "group_sessions_insert" on public.group_sessions
  for insert with check (auth.uid() = user_id);
create policy "group_sessions_update" on public.group_sessions
  for update using (auth.uid() = user_id);

-- group_responses and synthesis: via parent session ownership
create policy "group_responses_select" on public.group_responses
  for select using (
    exists (select 1 from public.group_sessions gs
            where gs.id = session_id and gs.user_id = auth.uid())
  );

create policy "group_synthesis_select" on public.group_synthesis
  for select using (
    exists (select 1 from public.group_sessions gs
            where gs.id = session_id and gs.user_id = auth.uid())
  );

-- ai_usage_log and monthly costs: own rows only
create policy "usage_log_select" on public.ai_usage_log
  for select using (auth.uid() = user_id);

create policy "monthly_costs_select" on public.user_monthly_costs
  for select using (auth.uid() = user_id);
