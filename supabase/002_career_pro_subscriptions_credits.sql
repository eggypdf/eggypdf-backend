-- EggyPDF Career Pro subscriptions, monthly AI credits and creator-code access.
-- Run after 001_career_accounts.sql.

alter table public.career_entitlements
  add column if not exists plan text,
  add column if not exists access_source text,
  add column if not exists subscription_status text,
  add column if not exists dodo_subscription_id text,
  add column if not exists dodo_customer_id text,
  add column if not exists current_period_start timestamptz,
  add column if not exists current_period_end timestamptz,
  add column if not exists cancel_at_period_end boolean not null default false,
  add column if not exists expires_at timestamptz,
  add column if not exists creator_code text;

do $$ begin
  alter table public.career_entitlements
    add constraint career_entitlements_plan_check
    check (plan is null or plan in ('monthly','annual','promo','legacy'));
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.career_entitlements
    add constraint career_entitlements_source_check
    check (access_source is null or access_source in ('paid','creator','manual','legacy'));
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.career_entitlements
    add constraint career_entitlements_subscription_status_check
    check (subscription_status is null or subscription_status in ('pending','active','on_hold','paused','cancelled','failed','expired','promo','legacy'));
exception when duplicate_object then null; end $$;

create unique index if not exists career_entitlements_subscription_idx
on public.career_entitlements(dodo_subscription_id)
where dodo_subscription_id is not null;

create table if not exists public.career_credit_wallets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  balance integer not null default 2000 check (balance >= 0),
  monthly_allowance integer not null default 2000 check (monthly_allowance > 0),
  period_start timestamptz not null default now(),
  period_end timestamptz not null default (now() + interval '1 month'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.career_credit_ledger (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  action text not null,
  delta integer not null,
  balance_after integer not null check (balance_after >= 0),
  request_id text not null unique,
  created_at timestamptz not null default now()
);

create index if not exists career_credit_ledger_user_created_idx
on public.career_credit_ledger(user_id, created_at desc);

create table if not exists public.career_creator_codes (
  code text primary key,
  status text not null default 'active' check (status in ('active','redeemed','revoked')),
  access_months integer check (access_months is null or access_months > 0),
  monthly_credits integer not null default 2000 check (monthly_credits > 0),
  expires_at timestamptz,
  redeemed_by uuid references auth.users(id) on delete set null,
  redeemed_at timestamptz,
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.career_webhook_events (
  webhook_id text primary key,
  event_type text not null,
  processed boolean not null default false,
  last_error text,
  received_at timestamptz not null default now(),
  processed_at timestamptz
);

alter table public.career_credit_wallets enable row level security;
alter table public.career_credit_ledger enable row level security;
alter table public.career_creator_codes enable row level security;
alter table public.career_webhook_events enable row level security;

-- Read-only access for the signed-in owner. All writes stay server-side.
drop policy if exists "Users can read own Career Pro credit wallet" on public.career_credit_wallets;
create policy "Users can read own Career Pro credit wallet"
on public.career_credit_wallets for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "Users can read own Career Pro credit ledger" on public.career_credit_ledger;
create policy "Users can read own Career Pro credit ledger"
on public.career_credit_ledger for select
to authenticated
using (auth.uid() = user_id);

-- No client policies are created for creator codes or webhook events.

create or replace function public.career_ensure_credit_wallet(p_user_id uuid)
returns public.career_credit_wallets
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ent public.career_entitlements%rowtype;
  v_wallet public.career_credit_wallets%rowtype;
begin
  select * into v_ent
  from public.career_entitlements
  where user_id = p_user_id;

  if not found or v_ent.status <> 'active' then
    raise exception 'CAREER_PRO_INACTIVE';
  end if;

  if v_ent.expires_at is not null and v_ent.expires_at <= now() then
    update public.career_entitlements
      set status = 'inactive', updated_at = now()
    where user_id = p_user_id;
    raise exception 'CAREER_PRO_INACTIVE';
  end if;

  if v_ent.subscription_status in ('on_hold','paused','failed','expired') then
    raise exception 'CAREER_PRO_INACTIVE';
  end if;

  if v_ent.subscription_status = 'cancelled'
     and coalesce(v_ent.current_period_end, v_ent.expires_at) is not null
     and coalesce(v_ent.current_period_end, v_ent.expires_at) <= now() then
    update public.career_entitlements
      set status = 'inactive', updated_at = now()
    where user_id = p_user_id;
    raise exception 'CAREER_PRO_INACTIVE';
  end if;

  insert into public.career_credit_wallets(user_id)
  values (p_user_id)
  on conflict (user_id) do nothing;

  select * into v_wallet
  from public.career_credit_wallets
  where user_id = p_user_id
  for update;

  if v_wallet.period_end <= now() then
    update public.career_credit_wallets
      set balance = monthly_allowance,
          period_start = now(),
          period_end = now() + interval '1 month',
          updated_at = now()
    where user_id = p_user_id
    returning * into v_wallet;

    insert into public.career_credit_ledger(user_id, action, delta, balance_after, request_id)
    values (
      p_user_id,
      'monthly_reset',
      v_wallet.monthly_allowance,
      v_wallet.balance,
      'reset:' || p_user_id::text || ':' || extract(epoch from v_wallet.period_start)::bigint::text
    )
    on conflict (request_id) do nothing;
  end if;

  return v_wallet;
end;
$$;

create or replace function public.career_consume_credits(
  p_user_id uuid,
  p_amount integer,
  p_action text,
  p_request_id text
)
returns public.career_credit_wallets
language plpgsql
security definer
set search_path = public
as $$
declare
  v_wallet public.career_credit_wallets%rowtype;
begin
  if p_amount <= 0 or p_amount > 2000 then
    raise exception 'INVALID_CREDIT_AMOUNT';
  end if;

  if exists(select 1 from public.career_credit_ledger where request_id = p_request_id) then
    select * into v_wallet from public.career_credit_wallets where user_id = p_user_id;
    return v_wallet;
  end if;

  v_wallet := public.career_ensure_credit_wallet(p_user_id);

  select * into v_wallet
  from public.career_credit_wallets
  where user_id = p_user_id
  for update;

  if v_wallet.balance < p_amount then
    raise exception 'INSUFFICIENT_CREDITS';
  end if;

  update public.career_credit_wallets
    set balance = balance - p_amount,
        updated_at = now()
  where user_id = p_user_id
  returning * into v_wallet;

  insert into public.career_credit_ledger(user_id, action, delta, balance_after, request_id)
  values (p_user_id, p_action, -p_amount, v_wallet.balance, p_request_id);

  return v_wallet;
end;
$$;

create or replace function public.career_refund_credits(
  p_user_id uuid,
  p_amount integer,
  p_action text,
  p_request_id text
)
returns public.career_credit_wallets
language plpgsql
security definer
set search_path = public
as $$
declare
  v_wallet public.career_credit_wallets%rowtype;
begin
  if p_amount <= 0 then
    raise exception 'INVALID_CREDIT_AMOUNT';
  end if;

  if exists(select 1 from public.career_credit_ledger where request_id = p_request_id) then
    select * into v_wallet from public.career_credit_wallets where user_id = p_user_id;
    return v_wallet;
  end if;

  select * into v_wallet
  from public.career_credit_wallets
  where user_id = p_user_id
  for update;

  if not found then
    v_wallet := public.career_ensure_credit_wallet(p_user_id);
  end if;

  update public.career_credit_wallets
    set balance = least(monthly_allowance, balance + p_amount),
        updated_at = now()
  where user_id = p_user_id
  returning * into v_wallet;

  insert into public.career_credit_ledger(user_id, action, delta, balance_after, request_id)
  values (p_user_id, p_action, p_amount, v_wallet.balance, p_request_id);

  return v_wallet;
end;
$$;

create or replace function public.career_reset_credits(
  p_user_id uuid,
  p_allowance integer default 2000
)
returns public.career_credit_wallets
language plpgsql
security definer
set search_path = public
as $$
declare
  v_wallet public.career_credit_wallets%rowtype;
begin
  insert into public.career_credit_wallets(
    user_id, balance, monthly_allowance, period_start, period_end
  ) values (
    p_user_id, p_allowance, p_allowance, now(), now() + interval '1 month'
  )
  on conflict (user_id) do update
    set balance = excluded.balance,
        monthly_allowance = excluded.monthly_allowance,
        period_start = excluded.period_start,
        period_end = excluded.period_end,
        updated_at = now()
  returning * into v_wallet;

  insert into public.career_credit_ledger(user_id, action, delta, balance_after, request_id)
  values (
    p_user_id,
    'subscription_credit_grant',
    p_allowance,
    v_wallet.balance,
    'grant:' || p_user_id::text || ':' || extract(epoch from v_wallet.period_start)::bigint::text
  )
  on conflict (request_id) do nothing;

  return v_wallet;
end;
$$;

create or replace function public.career_redeem_creator_code(
  p_user_id uuid,
  p_code text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_code text := upper(trim(coalesce(p_code, '')));
  v_row public.career_creator_codes%rowtype;
  v_existing public.career_entitlements%rowtype;
  v_access_expires timestamptz;
begin
  if length(v_code) < 6 or length(v_code) > 80 then
    return jsonb_build_object('success', false, 'error', 'Invalid creator code.');
  end if;

  select * into v_existing
  from public.career_entitlements
  where user_id = p_user_id;

  if found and v_existing.status = 'active'
     and (v_existing.expires_at is null or v_existing.expires_at > now()) then
    return jsonb_build_object('success', false, 'error', 'Career Pro is already active on this account.');
  end if;

  select * into v_row
  from public.career_creator_codes
  where code = v_code
  for update;

  if not found or v_row.status <> 'active' then
    return jsonb_build_object('success', false, 'error', 'This creator code is invalid or has already been used.');
  end if;

  if v_row.expires_at is not null and v_row.expires_at <= now() then
    return jsonb_build_object('success', false, 'error', 'This creator code has expired.');
  end if;

  if v_row.access_months is null then
    v_access_expires := null;
  else
    v_access_expires := now() + make_interval(months => v_row.access_months);
  end if;

  update public.career_creator_codes
    set status = 'redeemed',
        redeemed_by = p_user_id,
        redeemed_at = now(),
        updated_at = now()
  where code = v_code;

  insert into public.career_entitlements(
    user_id, status, product_id, purchased_at, plan, access_source,
    subscription_status, current_period_start, current_period_end,
    expires_at, creator_code, cancel_at_period_end
  ) values (
    p_user_id, 'active', 'creator_code', now(), 'promo', 'creator',
    'promo', now(), v_access_expires, v_access_expires, v_code, false
  )
  on conflict (user_id) do update
    set status = 'active',
        product_id = 'creator_code',
        purchased_at = now(),
        plan = 'promo',
        access_source = 'creator',
        subscription_status = 'promo',
        dodo_checkout_id = null,
        dodo_payment_id = null,
        dodo_subscription_id = null,
        dodo_customer_id = null,
        current_period_start = now(),
        current_period_end = v_access_expires,
        expires_at = v_access_expires,
        creator_code = v_code,
        cancel_at_period_end = false,
        updated_at = now();

  perform public.career_reset_credits(p_user_id, v_row.monthly_credits);

  return jsonb_build_object(
    'success', true,
    'plan', 'promo',
    'monthly_credits', v_row.monthly_credits,
    'expires_at', v_access_expires
  );
end;
$$;

revoke all on function public.career_ensure_credit_wallet(uuid) from public, anon, authenticated;
revoke all on function public.career_consume_credits(uuid, integer, text, text) from public, anon, authenticated;
revoke all on function public.career_refund_credits(uuid, integer, text, text) from public, anon, authenticated;
revoke all on function public.career_reset_credits(uuid, integer) from public, anon, authenticated;
revoke all on function public.career_redeem_creator_code(uuid, text) from public, anon, authenticated;

grant execute on function public.career_ensure_credit_wallet(uuid) to service_role;
grant execute on function public.career_consume_credits(uuid, integer, text, text) to service_role;
grant execute on function public.career_refund_credits(uuid, integer, text, text) to service_role;
grant execute on function public.career_reset_credits(uuid, integer) to service_role;
grant execute on function public.career_redeem_creator_code(uuid, text) to service_role;
