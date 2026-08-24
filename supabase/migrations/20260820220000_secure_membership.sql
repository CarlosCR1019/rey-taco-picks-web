begin;

create extension if not exists pgcrypto;

alter table if exists public.profiles
    add column if not exists role text not null default 'user',
    add column if not exists telegram_id text,
    add column if not exists telegram_username text;

with duplicate_links as (
    select id, row_number() over (partition by telegram_id order by id) as position
    from public.profiles
    where telegram_id is not null
)
update public.profiles as profiles
set telegram_id = null
from duplicate_links
where profiles.id = duplicate_links.id and duplicate_links.position > 1;

create unique index if not exists profiles_telegram_id_unique
    on public.profiles (telegram_id)
    where telegram_id is not null;

alter table if exists public.picks
    add column if not exists visibility text not null default 'premium',
    add column if not exists fecha_evento date,
    add column if not exists horario text,
    add column if not exists resultado_unidades numeric not null default 0,
    add column if not exists resultado_fuente text,
    add column if not exists resultado_evento_id text,
    add column if not exists resultado_marcador text,
    add column if not exists resultado_verificado_at timestamptz;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'picks_visibility_check'
    ) then
        alter table public.picks
            add constraint picks_visibility_check
            check (visibility in ('public', 'premium'));
    end if;
end
$$;

-- Repair legacy data before installing the global invariant. The latest public
-- pending pick remains free; any older duplicate becomes premium again.
with public_pending as (
    select id, row_number() over (order by id desc) as position
    from public.picks
    where visibility = 'public' and estado = 'pendiente'
)
update public.picks as picks
set visibility = 'premium'
from public_pending
where picks.id = public_pending.id and public_pending.position > 1;

create unique index if not exists picks_one_public_pending_idx
    on public.picks ((1))
    where visibility = 'public' and estado = 'pendiente';

create table if not exists public.subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    provider text not null check (provider in ('stripe', 'spei', 'promo')),
    provider_customer_id text,
    provider_subscription_id text,
    status text not null check (
        status in ('incomplete', 'trialing', 'active', 'past_due', 'canceled', 'expired')
    ),
    current_period_end timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (provider, provider_subscription_id)
);

alter table public.subscriptions
    add column if not exists provider_event_created bigint not null default 0,
    add column if not exists provider_event_id text not null default '';

create index if not exists subscriptions_user_status_idx
    on public.subscriptions (user_id, status, current_period_end desc);

create table if not exists public.promo_codes (
    id uuid primary key default gen_random_uuid(),
    code_hash text not null unique,
    access_days integer not null check (access_days between 1 and 365),
    expires_at timestamptz not null,
    usage_limit integer not null default 1 check (usage_limit > 0),
    uses integer not null default 0 check (uses >= 0),
    created_by uuid references auth.users(id),
    created_at timestamptz not null default now()
);

create table if not exists public.payment_reviews (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete set null,
    telegram_id text,
    telegram_username text,
    status text not null default 'pending_review'
        check (status in ('pending_review', 'approved', 'rejected')),
    detected_amount boolean not null default false,
    detected_bank boolean not null default false,
    receipt_filename text not null,
    reviewed_by uuid references auth.users(id),
    reviewed_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists public.telegram_link_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    token_hash bytea not null unique,
    expires_at timestamptz not null,
    used_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists public.stripe_webhook_events (
    event_id text primary key,
    event_created bigint not null,
    processed_at timestamptz not null default now()
);

create or replace function public.is_active_subscriber(check_user uuid default auth.uid())
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1
        from public.subscriptions
        where user_id = check_user
          and status in ('active', 'trialing')
          and current_period_end > now()
    );
$$;

create or replace function public.is_admin(check_user uuid default auth.uid())
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1 from public.profiles
        where id = check_user and role = 'admin'
    );
$$;

create or replace function public.create_promo_code(
    p_access_days integer,
    p_expires_at timestamptz,
    p_usage_limit integer default 1
)
returns text
language plpgsql
volatile
security definer
set search_path = public, pg_temp
as $$
declare
    raw_code text;
begin
    if not public.is_admin(auth.uid()) then raise exception 'admin required'; end if;
    if p_access_days not between 1 and 365
       or p_usage_limit < 1
       or p_expires_at <= now() then
        raise exception 'invalid promo configuration';
    end if;
    raw_code := encode(gen_random_bytes(8), 'hex');
    insert into public.promo_codes (
        code_hash, access_days, expires_at, usage_limit, created_by
    ) values (
        encode(digest(lower(raw_code), 'sha256'), 'hex'),
        p_access_days, p_expires_at, p_usage_limit, auth.uid()
    );
    return raw_code;
end;
$$;

create or replace function public.create_telegram_link_token()
returns text
language plpgsql
volatile
security definer
set search_path = public, pg_temp
as $$
declare
    raw_token text;
begin
    if auth.uid() is null then
        raise exception 'authentication required';
    end if;
    raw_token := encode(gen_random_bytes(24), 'hex');
    delete from public.telegram_link_tokens where user_id = auth.uid();
    insert into public.telegram_link_tokens (user_id, token_hash, expires_at)
    values (auth.uid(), digest(raw_token, 'sha256'), now() + interval '10 minutes');
    return raw_token;
end;
$$;

create or replace function public.consume_telegram_link_token(
    raw_token text,
    new_telegram_id text,
    new_telegram_username text default null
)
returns boolean
language plpgsql
volatile
security definer
set search_path = public, pg_temp
as $$
declare
    link_id uuid;
    link_user uuid;
begin
    if nullif(trim(new_telegram_id), '') is null then return false; end if;
    select id, user_id into link_id, link_user
    from public.telegram_link_tokens
    where token_hash = digest(raw_token, 'sha256')
      and used_at is null
      and expires_at > now()
    for update;
    if link_id is null then return false; end if;

    update public.profiles
    set telegram_id = new_telegram_id,
        telegram_username = nullif(lower(trim(new_telegram_username)), '')
    where id = link_user;
    if not found then return false; end if;

    update public.telegram_link_tokens set used_at = now() where id = link_id;
    return true;
end;
$$;

create or replace function public.redeem_promo_code(raw_code text)
returns timestamptz
language plpgsql
volatile
security definer
set search_path = public, pg_temp
as $$
declare
    promo public.promo_codes%rowtype;
    membership_key text;
    access_end timestamptz;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    select * into promo
    from public.promo_codes
    where code_hash = encode(digest(lower(trim(raw_code)), 'sha256'), 'hex')
    for update;
    if promo.id is null or promo.expires_at <= now() or promo.uses >= promo.usage_limit then
        raise exception 'invalid or expired promo code';
    end if;

    membership_key := 'promo:' || promo.id::text || ':' || auth.uid()::text;
    if exists (
        select 1 from public.subscriptions
        where provider = 'promo' and provider_subscription_id = membership_key
    ) then raise exception 'promo code already redeemed'; end if;

    select greatest(now(), coalesce(max(current_period_end), now()))
      + make_interval(days => promo.access_days)
    into access_end
    from public.subscriptions
    where user_id = auth.uid() and status in ('active', 'trialing');

    update public.promo_codes set uses = uses + 1 where id = promo.id;
    insert into public.subscriptions (
        user_id, provider, provider_subscription_id, status, current_period_end
    ) values (auth.uid(), 'promo', membership_key, 'active', access_end);
    return access_end;
end;
$$;

create or replace function public.approve_spei_review(
    review_id uuid,
    review_user uuid,
    reviewer uuid
)
returns timestamptz
language plpgsql
volatile
security definer
set search_path = public, pg_temp
as $$
declare
    review_status text;
    linked_user uuid;
    access_end timestamptz;
begin
    if not public.is_admin(reviewer) then raise exception 'admin required'; end if;
    select payment.status, payment.user_id into review_status, linked_user
    from public.payment_reviews payment
    where payment.id = review_id
    for update;
    if review_status is distinct from 'pending_review' then
        raise exception 'review is not pending';
    end if;
    if linked_user is not null and linked_user <> review_user then
        raise exception 'review is linked to another user';
    end if;

    select greatest(now(), coalesce(max(current_period_end), now())) + interval '30 days'
    into access_end
    from public.subscriptions
    where user_id = review_user and status in ('active', 'trialing');

    insert into public.subscriptions (
        user_id, provider, provider_subscription_id, status, current_period_end
    ) values (review_user, 'spei', 'spei:' || review_id::text, 'active', access_end);
    update public.payment_reviews
    set user_id = review_user, status = 'approved', reviewed_by = reviewer, reviewed_at = now()
    where id = review_id;
    return access_end;
end;
$$;

create or replace function public.reject_spei_review(review_id uuid, reviewer uuid)
returns boolean
language plpgsql
volatile
security definer
set search_path = public, pg_temp
as $$
begin
    if not public.is_admin(reviewer) then raise exception 'admin required'; end if;
    update public.payment_reviews
    set status = 'rejected', reviewed_by = reviewer, reviewed_at = now()
    where id = review_id and status = 'pending_review';
    return found;
end;
$$;

create or replace function public.apply_stripe_subscription_event(
    p_event_id text,
    p_event_created bigint,
    p_user_id uuid,
    p_customer_id text,
    p_subscription_id text,
    p_status text,
    p_current_period_end timestamptz
)
returns boolean
language plpgsql
volatile
security definer
set search_path = public, pg_temp
as $$
declare
    affected integer;
begin
    insert into public.stripe_webhook_events (event_id, event_created)
    values (p_event_id, p_event_created)
    on conflict (event_id) do nothing;
    if not found then return false; end if;

    insert into public.subscriptions (
        user_id, provider, provider_customer_id, provider_subscription_id,
        status, current_period_end, provider_event_created, provider_event_id, updated_at
    ) values (
        p_user_id, 'stripe', p_customer_id, p_subscription_id,
        p_status, p_current_period_end, p_event_created, p_event_id, now()
    )
    on conflict (provider, provider_subscription_id) do update
    set user_id = excluded.user_id,
        provider_customer_id = excluded.provider_customer_id,
        status = excluded.status,
        current_period_end = excluded.current_period_end,
        provider_event_created = excluded.provider_event_created,
        provider_event_id = excluded.provider_event_id,
        updated_at = now()
    where excluded.provider_event_created > subscriptions.provider_event_created
       or (
           excluded.provider_event_created = subscriptions.provider_event_created
           and excluded.provider_event_id > subscriptions.provider_event_id
       );
    get diagnostics affected = row_count;
    return affected > 0;
end;
$$;

revoke all on function public.is_active_subscriber(uuid) from public;
grant execute on function public.is_active_subscriber(uuid) to authenticated, service_role;
revoke all on function public.is_admin(uuid) from public;
grant execute on function public.is_admin(uuid) to authenticated;
revoke all on function public.create_promo_code(integer, timestamptz, integer) from public;
grant execute on function public.create_promo_code(integer, timestamptz, integer) to authenticated;
revoke all on function public.create_telegram_link_token() from public;
grant execute on function public.create_telegram_link_token() to authenticated;
revoke all on function public.consume_telegram_link_token(text, text, text) from public;
grant execute on function public.consume_telegram_link_token(text, text, text) to service_role;
revoke all on function public.redeem_promo_code(text) from public;
grant execute on function public.redeem_promo_code(text) to authenticated;
revoke all on function public.approve_spei_review(uuid, uuid, uuid) from public;
grant execute on function public.approve_spei_review(uuid, uuid, uuid) to service_role;
revoke all on function public.reject_spei_review(uuid, uuid) from public;
grant execute on function public.reject_spei_review(uuid, uuid) to service_role;
revoke all on function public.apply_stripe_subscription_event(text, bigint, uuid, text, text, text, timestamptz) from public;
grant execute on function public.apply_stripe_subscription_event(text, bigint, uuid, text, text, text, timestamptz) to service_role;

alter table public.profiles enable row level security;
alter table public.picks enable row level security;
alter table public.subscriptions enable row level security;
alter table public.promo_codes enable row level security;
alter table public.payment_reviews enable row level security;
alter table public.telegram_link_tokens enable row level security;
alter table public.stripe_webhook_events enable row level security;
revoke all on table public.stripe_webhook_events from anon, authenticated;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
    for select to authenticated
    using (id = auth.uid() or public.is_admin(auth.uid()));

drop policy if exists picks_public_read on public.picks;
create policy picks_public_read on public.picks
    for select to anon, authenticated
    using (visibility = 'public');

drop policy if exists picks_subscriber_read on public.picks;
create policy picks_subscriber_read on public.picks
    for select to authenticated
    using (visibility = 'public' or public.is_active_subscriber(auth.uid()));

drop policy if exists picks_admin_write on public.picks;
create policy picks_admin_write on public.picks
    for all to authenticated
    using (public.is_admin(auth.uid()))
    with check (public.is_admin(auth.uid()));

drop policy if exists subscriptions_select_own on public.subscriptions;
create policy subscriptions_select_own on public.subscriptions
    for select to authenticated
    using (user_id = auth.uid() or public.is_admin(auth.uid()));

drop policy if exists payment_reviews_insert_own on public.payment_reviews;
create policy payment_reviews_insert_own on public.payment_reviews
    for insert to authenticated
    with check (user_id = auth.uid());

drop policy if exists payment_reviews_admin on public.payment_reviews;
create policy payment_reviews_admin on public.payment_reviews
    for all to authenticated
    using (public.is_admin(auth.uid()))
    with check (public.is_admin(auth.uid()));

drop policy if exists promo_codes_admin on public.promo_codes;
create policy promo_codes_admin on public.promo_codes
    for all to authenticated
    using (public.is_admin(auth.uid()))
    with check (public.is_admin(auth.uid()));

create or replace view public.public_picks
with (security_invoker = true)
as
select
    id,
    categoria,
    partido,
    pick,
    cuota,
    confianza,
    razonamiento,
    fecha_generacion,
    fecha_evento,
    horario,
    tiene_valor,
    es_parlay,
    estado,
    visibility,
    resultado_unidades,
    resultado_fuente,
    resultado_marcador,
    resultado_verificado_at
from public.picks
where visibility = 'public';

create or replace function public.get_visible_picks()
returns setof public.picks
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select p.*
    from public.picks p
    where p.visibility = 'public'
       or public.is_active_subscriber(auth.uid());
$$;

revoke all on function public.get_visible_picks() from public;
grant execute on function public.get_visible_picks() to anon, authenticated;
grant select on public.public_picks to anon, authenticated;

-- Preserve one useful public selection on existing installations.
update public.picks
set visibility = 'public'
where id = (
    select id
    from public.picks
    where estado = 'pendiente'
      and coalesce(es_parlay, false) = false
    order by id desc
    limit 1
)
and not exists (
    select 1 from public.picks where visibility = 'public' and estado = 'pendiente'
);

-- A settled selection no longer has pre-game premium value and joins the
-- transparent public record through an explicit lifecycle transition.
update public.picks
set visibility = 'public'
where estado in ('ganado', 'perdido', 'void', 'revision_pendiente');

commit;
