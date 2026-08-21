begin;

create extension if not exists pgcrypto;

alter table if exists public.profiles
    add column if not exists role text not null default 'user',
    add column if not exists telegram_id text,
    add column if not exists telegram_username text;

alter table if exists public.picks
    add column if not exists visibility text not null default 'premium',
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

revoke all on function public.is_active_subscriber(uuid) from public;
grant execute on function public.is_active_subscriber(uuid) to authenticated;
revoke all on function public.is_admin(uuid) from public;
grant execute on function public.is_admin(uuid) to authenticated;

alter table public.profiles enable row level security;
alter table public.picks enable row level security;
alter table public.subscriptions enable row level security;
alter table public.promo_codes enable row level security;
alter table public.payment_reviews enable row level security;

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

commit;
