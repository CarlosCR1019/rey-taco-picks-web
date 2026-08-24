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

-- public_picks depends on picks.id, so recreate it around the bigint upgrade.
drop view if exists public.public_picks;

alter table public.picks
    alter column id type bigint using id::bigint;

alter table public.picks
    add column if not exists batch_id uuid references public.pick_batches(id),
    add column if not exists active boolean not null default false,
    add column if not exists source text,
    add column if not exists source_event_id text,
    add column if not exists source_market_key text,
    add column if not exists source_selection_key text,
    add column if not exists source_observed_at timestamptz,
    add column if not exists source_starts_at timestamptz;

create index if not exists picks_active_batch_idx
    on public.picks (batch_id, active, estado);

create index if not exists picks_source_event_idx
    on public.picks (source, source_event_id);

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
    resultado_verificado_at,
    source,
    source_event_id,
    source_market_key,
    source_selection_key,
    source_observed_at,
    source_starts_at
from public.picks
where visibility = 'public';

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
    resumed_batch public.pick_batches%rowtype;
    created_batch uuid;
    first_pick_id bigint;
    public_pick_count bigint;
    public_parlay_count bigint;
    audit_entry jsonb;
    observed_at_value timestamptz;
    starts_at_value timestamptz;
    persisted_picks jsonb;
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

    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where jsonb_typeof(value) <> 'object'
           or nullif(btrim(value->>'source'), '') is null
           or nullif(btrim(value->>'source_event_id'), '') is null
           or nullif(btrim(value->>'source_market_key'), '') is null
           or nullif(btrim(value->>'source_selection_key'), '') is null
           or nullif(btrim(value->>'source_observed_at'), '') is null
           or nullif(btrim(value->>'source_starts_at'), '') is null
           or length(btrim(value->>'source')) not between 1 and 100
           or length(btrim(value->>'source_event_id')) not between 1 and 500
           or length(btrim(value->>'source_market_key')) not between 1 and 1000
           or length(btrim(value->>'source_selection_key')) not between 1 and 500
    ) then
        raise exception 'each requested pick must have complete source audit fields';
    end if;

    for audit_entry in
        select value from jsonb_array_elements(requested_picks) as entry(value)
    loop
        if (audit_entry->>'source_observed_at') !~
           '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$' then
            raise exception 'source_observed_at must be UTC and not in the future';
        end if;
        begin
            observed_at_value := (audit_entry->>'source_observed_at')::timestamptz;
        exception
            when invalid_datetime_format or datetime_field_overflow then
                raise exception 'source_observed_at must be UTC and not in the future';
        end;
        if observed_at_value > now() then
            raise exception 'source_observed_at must be UTC and not in the future';
        end if;
        if (audit_entry->>'source_starts_at') !~
           '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$' then
            raise exception 'source_starts_at must be UTC, after source_observed_at, and in the future';
        end if;
        begin
            starts_at_value := (audit_entry->>'source_starts_at')::timestamptz;
        exception
            when invalid_datetime_format or datetime_field_overflow then
                raise exception 'source_starts_at must be UTC, after source_observed_at, and in the future';
        end;
        if starts_at_value <= observed_at_value or starts_at_value <= now() then
            raise exception 'source_starts_at must be UTC, after source_observed_at, and in the future';
        end if;
    end loop;

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

    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where (value->>'source_starts_at')::timestamptz <= clock_timestamp()
    ) then
        raise exception 'source_starts_at expired while waiting for publication lock';
    end if;

    insert into public.scraper_runs (run_key, source_hash)
    values (requested_run_key, requested_source_hash)
    on conflict (run_key) do nothing;

    select *
    into claimed_run
    from public.scraper_runs
    where run_key = requested_run_key
    for update;

    if claimed_run.status in ('published', 'partial') then
        select *
        into resumed_batch
        from public.pick_batches
        where run_id = claimed_run.id
        for update;

        if not found then
            raise exception 'completed scraper run has no persisted pick batch';
        end if;
        if not resumed_batch.active then
            raise exception 'scraper run batch is inactive or superseded';
        end if;
        created_batch := resumed_batch.id;

        if exists (
            select 1
            from public.picks as persisted_row
            where persisted_row.batch_id = created_batch
              and (
                  persisted_row.source_starts_at is null
                  or persisted_row.source_starts_at <= clock_timestamp()
              )
        ) then
            raise exception 'persisted pick event is stale';
        end if;

        select coalesce(jsonb_agg(jsonb_build_object(
            'id', persisted_row.id,
            'categoria', persisted_row.categoria,
            'partido', persisted_row.partido,
            'pick', persisted_row.pick,
            'cuota', persisted_row.cuota,
            'confianza', persisted_row.confianza,
            'razonamiento', persisted_row.razonamiento,
            'marcador', persisted_row.marcador,
            'estado', persisted_row.estado,
            'es_parlay', persisted_row.es_parlay,
            'liga', persisted_row.liga,
            'mercado', persisted_row.mercado,
            'riesgo', persisted_row.riesgo,
            'resultado_apuesta', persisted_row.resultado_apuesta,
            'ganancia_simulada', persisted_row.ganancia_simulada,
            'fecha_generacion', persisted_row.fecha_generacion,
            'fecha_evento', persisted_row.fecha_evento,
            'horario', persisted_row.horario,
            'odds_mercado', persisted_row.odds_mercado,
            'tiene_valor', persisted_row.tiene_valor,
            'visibility', persisted_row.visibility,
            'source', persisted_row.source,
            'source_event_id', persisted_row.source_event_id,
            'source_market_key', persisted_row.source_market_key,
            'source_selection_key', persisted_row.source_selection_key,
            'source_observed_at', persisted_row.source_observed_at,
            'source_starts_at', persisted_row.source_starts_at
        ) order by persisted_row.id), '[]'::jsonb)
        into persisted_picks
        from public.picks as persisted_row
        where persisted_row.batch_id = created_batch;

        if jsonb_array_length(persisted_picks) = 0 then
            raise exception 'completed scraper run has no persisted pick batch';
        end if;

        return jsonb_build_object(
            'run_id', claimed_run.id,
            'batch_id', created_batch,
            'created', false,
            'delivery_status', claimed_run.delivery_status,
            'picks', persisted_picks
        );
    end if;

    if claimed_run.source_hash <> requested_source_hash then
        raise exception 'run key % already belongs to a different source hash', requested_run_key;
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
        source,
        source_event_id,
        source_market_key,
        source_selection_key,
        source_observed_at,
        source_starts_at,
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
        case
            when (requested_rows.populated).visibility = 'public' then null
            else (requested_rows.populated).razonamiento
        end,
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
        (requested_rows.populated).source,
        (requested_rows.populated).source_event_id,
        (requested_rows.populated).source_market_key,
        (requested_rows.populated).source_selection_key,
        (requested_rows.populated).source_observed_at,
        (requested_rows.populated).source_starts_at,
        created_batch,
        true
    from requested_rows;

    if exists (
        select 1
        from public.picks as persisted_row
        where persisted_row.batch_id = created_batch
          and persisted_row.source_starts_at <= clock_timestamp()
    ) then
        raise exception 'source_starts_at expired during batch persistence';
    end if;

    update public.scraper_runs
    set status = 'published', finished_at = now()
    where id = claimed_run.id;

    select coalesce(jsonb_agg(jsonb_build_object(
        'id', persisted_row.id,
        'categoria', persisted_row.categoria,
        'partido', persisted_row.partido,
        'pick', persisted_row.pick,
        'cuota', persisted_row.cuota,
        'confianza', persisted_row.confianza,
        'razonamiento', persisted_row.razonamiento,
        'marcador', persisted_row.marcador,
        'estado', persisted_row.estado,
        'es_parlay', persisted_row.es_parlay,
        'liga', persisted_row.liga,
        'mercado', persisted_row.mercado,
        'riesgo', persisted_row.riesgo,
        'resultado_apuesta', persisted_row.resultado_apuesta,
        'ganancia_simulada', persisted_row.ganancia_simulada,
        'fecha_generacion', persisted_row.fecha_generacion,
        'fecha_evento', persisted_row.fecha_evento,
        'horario', persisted_row.horario,
        'odds_mercado', persisted_row.odds_mercado,
        'tiene_valor', persisted_row.tiene_valor,
        'visibility', persisted_row.visibility,
        'source', persisted_row.source,
        'source_event_id', persisted_row.source_event_id,
        'source_market_key', persisted_row.source_market_key,
        'source_selection_key', persisted_row.source_selection_key,
        'source_observed_at', persisted_row.source_observed_at,
        'source_starts_at', persisted_row.source_starts_at
    ) order by persisted_row.id), '[]'::jsonb)
    into persisted_picks
    from public.picks as persisted_row
    where persisted_row.batch_id = created_batch;

    if jsonb_array_length(persisted_picks) = 0 then
        raise exception 'created scraper run has no persisted picks';
    end if;

    return jsonb_build_object(
        'run_id', claimed_run.id,
        'batch_id', created_batch,
        'created', true,
        'delivery_status', claimed_run.delivery_status,
        'picks', persisted_picks
    );
end;
$$;

create or replace function public.resume_pick_batch(
    requested_run_key text
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    claimed_run public.scraper_runs%rowtype;
    resumed_batch public.pick_batches%rowtype;
    persisted_picks jsonb;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be empty';
    end if;

    perform pg_advisory_xact_lock(20260820233000);

    select *
    into claimed_run
    from public.scraper_runs
    where run_key = requested_run_key
    for update;

    if not found then
        return null;
    end if;
    if claimed_run.status not in ('published', 'partial') then
        return null;
    end if;

    select *
    into resumed_batch
    from public.pick_batches
    where run_id = claimed_run.id
    for update;

    if not found then
        raise exception 'completed scraper run has no persisted pick batch';
    end if;
    if not resumed_batch.active then
        raise exception 'scraper run batch is inactive or superseded';
    end if;

    if exists (
        select 1
        from public.picks as persisted_row
        where persisted_row.batch_id = resumed_batch.id
          and (
              persisted_row.source_starts_at is null
              or persisted_row.source_starts_at <= clock_timestamp()
          )
    ) then
        raise exception 'persisted pick event is stale';
    end if;

    select coalesce(jsonb_agg(jsonb_build_object(
        'id', persisted_row.id,
        'categoria', persisted_row.categoria,
        'partido', persisted_row.partido,
        'pick', persisted_row.pick,
        'cuota', persisted_row.cuota,
        'confianza', persisted_row.confianza,
        'razonamiento', persisted_row.razonamiento,
        'marcador', persisted_row.marcador,
        'estado', persisted_row.estado,
        'es_parlay', persisted_row.es_parlay,
        'liga', persisted_row.liga,
        'mercado', persisted_row.mercado,
        'riesgo', persisted_row.riesgo,
        'resultado_apuesta', persisted_row.resultado_apuesta,
        'ganancia_simulada', persisted_row.ganancia_simulada,
        'fecha_generacion', persisted_row.fecha_generacion,
        'fecha_evento', persisted_row.fecha_evento,
        'horario', persisted_row.horario,
        'odds_mercado', persisted_row.odds_mercado,
        'tiene_valor', persisted_row.tiene_valor,
        'visibility', persisted_row.visibility,
        'source', persisted_row.source,
        'source_event_id', persisted_row.source_event_id,
        'source_market_key', persisted_row.source_market_key,
        'source_selection_key', persisted_row.source_selection_key,
        'source_observed_at', persisted_row.source_observed_at,
        'source_starts_at', persisted_row.source_starts_at
    ) order by persisted_row.id), '[]'::jsonb)
    into persisted_picks
    from public.picks as persisted_row
    where persisted_row.batch_id = resumed_batch.id;

    if jsonb_array_length(persisted_picks) = 0 then
        raise exception 'completed scraper run has no persisted pick batch';
    end if;

    return jsonb_build_object(
        'run_id', claimed_run.id,
        'batch_id', resumed_batch.id,
        'created', false,
        'delivery_status', claimed_run.delivery_status,
        'picks', persisted_picks
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
    if requested_success is null then
        raise exception 'requested_success must not be null';
    end if;

    if requested_destination is null
       or requested_destination not in ('admin', 'vip', 'free') then
        raise exception 'requested_destination must be admin, vip, or free';
    end if;

    with updated as (
        select
            id,
            jsonb_set(
                delivery_status,
                array[requested_destination],
                jsonb_build_object(
                    'success', requested_success,
                    'error', left(coalesce(requested_error, ''), 200),
                    'updated_at', now()
                ),
                true
            ) as next_delivery_status
        from public.scraper_runs
        where id = requested_run_id
          and status in ('published', 'partial')
        for update
    )
    update public.scraper_runs as runs
    set delivery_status = updated.next_delivery_status,
        status = case
            when not exists (
                select 1
                from jsonb_each(updated.next_delivery_status)
                    as delivery(destination, details)
                where details->>'success' is distinct from 'true'
            ) then 'published' else 'partial'
        end
    from updated
    where runs.id = updated.id;

    if not found then
        raise exception 'unknown or unpublished scraper run %', requested_run_id;
    end if;
end;
$$;

alter table public.scraper_runs enable row level security;
alter table public.pick_batches enable row level security;

drop policy if exists picks_public_read on public.picks;
drop policy if exists picks_member_read on public.picks;
drop policy if exists picks_subscriber_read on public.picks;

create policy picks_public_read on public.picks
    for select to anon
    using (
        (estado = 'pendiente' and active and visibility = 'public')
        or (estado <> 'pendiente' and visibility = 'public')
    );

create policy picks_member_read on public.picks
    for select to authenticated
    using (
        (
            estado = 'pendiente'
            and active
            and (
                visibility = 'public'
                or public.is_active_subscriber(auth.uid())
            )
        )
        or (estado <> 'pendiente' and visibility = 'public')
    );

-- A FOR ALL policy also grants SELECT to ordinary authenticated users through
-- policy OR-composition. Keep each admin operation explicitly role-checked.
drop policy if exists picks_admin_write on public.picks;
drop policy if exists picks_admin_select on public.picks;
drop policy if exists picks_admin_insert on public.picks;
drop policy if exists picks_admin_update on public.picks;
drop policy if exists picks_admin_delete on public.picks;

create policy picks_admin_select on public.picks
    for select to authenticated
    using (public.is_admin(auth.uid()));

create policy picks_admin_insert on public.picks
    for insert to authenticated
    with check (public.is_admin(auth.uid()));

create policy picks_admin_update on public.picks
    for update to authenticated
    using (public.is_admin(auth.uid()))
    with check (public.is_admin(auth.uid()));

create policy picks_admin_delete on public.picks
    for delete to authenticated
    using (public.is_admin(auth.uid()));

-- Read-only deployment preflight. The scraper calls this before opening Chrome;
-- unlike publish_pick_batch, it cannot claim a run or mutate a batch.
create or replace function public.scraper_schema_status()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'version', 1,
        'public_picks', to_regclass('public.public_picks') is not null,
        'publish_pick_batch',
            to_regprocedure('public.publish_pick_batch(text,text,jsonb)') is not null,
        'resume_pick_batch',
            to_regprocedure('public.resume_pick_batch(text)') is not null,
        'source_audit', false
    );
$$;

revoke all on table public.scraper_runs from public, anon, authenticated;
revoke all on table public.pick_batches from public, anon, authenticated;
grant all on table public.scraper_runs to service_role;
grant all on table public.pick_batches to service_role;
grant select on public.public_picks to anon, authenticated;

revoke all on function public.publish_pick_batch(text, text, jsonb) from public, anon, authenticated;
revoke all on function public.resume_pick_batch(text) from public, anon, authenticated;
revoke all on function public.record_scraper_delivery(uuid, text, boolean, text) from public, anon, authenticated;
grant execute on function public.publish_pick_batch(text, text, jsonb) to service_role;
grant execute on function public.resume_pick_batch(text) to service_role;
grant execute on function public.record_scraper_delivery(uuid, text, boolean, text) to service_role;

revoke all on function public.scraper_schema_status() from public, anon, authenticated;
grant execute on function public.scraper_schema_status() to service_role;

revoke all on function public.get_visible_picks() from public;
grant execute on function public.get_visible_picks() to anon, authenticated;

commit;
