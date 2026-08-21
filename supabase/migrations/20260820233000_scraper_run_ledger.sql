begin;

create extension if not exists pgcrypto;

create table if not exists public.scraper_runs (
    id uuid primary key default gen_random_uuid(),
    run_key text not null unique,
    status text not null default 'running'
        check (status in ('running', 'published', 'partial', 'failed')),
    source_hash text not null,
    delivery_status jsonb not null default '{}'::jsonb,
    error_message text,
    created_at timestamptz not null default now(),
    finished_at timestamptz
);

create table if not exists public.pick_batches (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null unique references public.scraper_runs(id) on delete cascade,
    active boolean not null default false,
    created_at timestamptz not null default now()
);

create unique index if not exists pick_batches_one_active_idx
    on public.pick_batches ((1))
    where active;

alter table public.picks
    add column if not exists batch_id uuid references public.pick_batches(id),
    add column if not exists active boolean not null default false;

create index if not exists picks_active_batch_idx
    on public.picks (batch_id, active, estado);

create or replace function public.publish_pick_batch(
    requested_run_key text,
    requested_source_hash text,
    requested_picks jsonb
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    claimed_run public.scraper_runs%rowtype;
    created_batch uuid;
    first_pick_id bigint;
    public_pick_count bigint;
    public_parlay_count bigint;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be empty';
    end if;

    if requested_source_hash is null or btrim(requested_source_hash) = '' then
        raise exception 'requested_source_hash must not be empty';
    end if;

    if requested_picks is null
       or jsonb_typeof(requested_picks) <> 'array'
       or jsonb_array_length(requested_picks) = 0 then
        raise exception 'requested_picks must be a non-empty array';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where coalesce(value->>'visibility', '') not in ('public', 'premium')
    ) then
        raise exception 'each requested pick must have public or premium visibility';
    end if;

    select
        count(*) filter (where value->>'visibility' = 'public'),
        count(*) filter (
            where value->>'visibility' = 'public'
              and coalesce((value->>'es_parlay')::boolean, false)
        )
    into public_pick_count, public_parlay_count
    from jsonb_array_elements(requested_picks) as entry(value);

    if public_pick_count <> 1 or public_parlay_count <> 0 then
        raise exception 'requested_picks must contain exactly one public non-parlay pick';
    end if;

    -- The active batch is a global singleton, so serialize all publications,
    -- including publications that use different run keys.
    perform pg_advisory_xact_lock(20260820233000);

    insert into public.scraper_runs (run_key, source_hash)
    values (requested_run_key, requested_source_hash)
    on conflict (run_key) do nothing;

    select *
    into claimed_run
    from public.scraper_runs
    where run_key = requested_run_key
    for update;

    if claimed_run.status in ('published', 'partial') then
        return jsonb_build_object(
            'run_id', claimed_run.id,
            'batch_id', (
                select id
                from public.pick_batches
                where run_id = claimed_run.id
            ),
            'created', false,
            'delivery_status', claimed_run.delivery_status
        );
    end if;

    -- Demote all legacy and current public pending picks before inserting the
    -- replacement so picks_one_public_pending_idx cannot reject the batch.
    update public.picks
    set visibility = 'premium'
    where estado = 'pendiente' and visibility = 'public';

    update public.pick_batches set active = false where active;
    update public.picks set active = false where active;

    insert into public.pick_batches (run_id, active)
    values (claimed_run.id, true)
    returning id into created_batch;

    select greatest(
        coalesce(max(id), 0) + 1,
        floor(extract(epoch from clock_timestamp()) * 1000000)::bigint
    )
    into first_pick_id
    from public.picks;

    with requested_rows as (
        select
            jsonb_populate_record(null::public.picks, item.value) as populated,
            item.ordinality
        from jsonb_array_elements(requested_picks)
            with ordinality as item(value, ordinality)
    )
    insert into public.picks (
        id,
        categoria,
        partido,
        pick,
        cuota,
        confianza,
        razonamiento,
        marcador,
        estado,
        es_parlay,
        liga,
        mercado,
        riesgo,
        resultado_apuesta,
        ganancia_simulada,
        fecha_generacion,
        fecha_evento,
        horario,
        odds_mercado,
        tiene_valor,
        visibility,
        batch_id,
        active
    )
    select
        first_pick_id + requested_rows.ordinality - 1,
        (requested_rows.populated).categoria,
        (requested_rows.populated).partido,
        (requested_rows.populated).pick,
        (requested_rows.populated).cuota,
        (requested_rows.populated).confianza,
        (requested_rows.populated).razonamiento,
        (requested_rows.populated).marcador,
        'pendiente',
        coalesce((requested_rows.populated).es_parlay, false),
        (requested_rows.populated).liga,
        (requested_rows.populated).mercado,
        (requested_rows.populated).riesgo,
        (requested_rows.populated).resultado_apuesta,
        coalesce((requested_rows.populated).ganancia_simulada, 0),
        (requested_rows.populated).fecha_generacion,
        (requested_rows.populated).fecha_evento,
        (requested_rows.populated).horario,
        (requested_rows.populated).odds_mercado,
        coalesce((requested_rows.populated).tiene_valor, false),
        (requested_rows.populated).visibility,
        created_batch,
        true
    from requested_rows;

    update public.scraper_runs
    set status = 'published', finished_at = now()
    where id = claimed_run.id;

    return jsonb_build_object(
        'run_id', claimed_run.id,
        'batch_id', created_batch,
        'created', true,
        'delivery_status', claimed_run.delivery_status
    );
end;
$$;

create or replace function public.get_visible_picks()
returns setof public.picks
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select p.*
    from public.picks p
    where (
        p.estado = 'pendiente' and p.active
        and (
            p.visibility = 'public'
            or public.is_active_subscriber(auth.uid())
        )
    ) or (
        p.estado <> 'pendiente' and p.visibility = 'public'
    );
$$;

create or replace function public.record_scraper_delivery(
    requested_run_id uuid,
    requested_destination text,
    requested_success boolean,
    requested_error text default ''
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if requested_destination is null
       or requested_destination not in ('admin', 'vip', 'free') then
        raise exception 'requested_destination must be admin, vip, or free';
    end if;

    update public.scraper_runs
    set delivery_status = jsonb_set(
            delivery_status,
            array[requested_destination],
            jsonb_build_object(
                'success', requested_success,
                'error', left(coalesce(requested_error, ''), 200),
                'updated_at', now()
            ),
            true
        ),
        status = case when requested_success then status else 'partial' end
    where id = requested_run_id;

    if not found then
        raise exception 'unknown scraper run %', requested_run_id;
    end if;
end;
$$;

alter table public.scraper_runs enable row level security;
alter table public.pick_batches enable row level security;

revoke all on table public.scraper_runs from public, anon, authenticated;
revoke all on table public.pick_batches from public, anon, authenticated;
grant all on table public.scraper_runs to service_role;
grant all on table public.pick_batches to service_role;

revoke all on function public.publish_pick_batch(text, text, jsonb) from public, anon, authenticated;
revoke all on function public.record_scraper_delivery(uuid, text, boolean, text) from public, anon, authenticated;
grant execute on function public.publish_pick_batch(text, text, jsonb) to service_role;
grant execute on function public.record_scraper_delivery(uuid, text, boolean, text) to service_role;

revoke all on function public.get_visible_picks() from public;
grant execute on function public.get_visible_picks() to anon, authenticated;

commit;
