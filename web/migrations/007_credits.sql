-- Credit-based access model
-- Replaces subscription with one-time credit packs

alter table public.user_subscriptions
  add column if not exists credits_balance int not null default 0;

create table if not exists public.credit_purchases (
  id                       uuid        default gen_random_uuid() primary key,
  user_id                  uuid        not null,
  stripe_payment_intent_id text,
  pack_id                  text        not null,
  credits                  int         not null,
  amount_aud_cents         int         not null,
  created_at               timestamptz default now() not null
);

alter table public.credit_purchases enable row level security;

create policy "Users can read their own purchases"
  on public.credit_purchases for select
  using (user_id = auth.uid());

create index if not exists credit_purchases_user
  on public.credit_purchases(user_id, created_at desc);
