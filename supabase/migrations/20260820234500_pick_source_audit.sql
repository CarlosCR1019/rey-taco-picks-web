begin;

alter table public.picks
    add column if not exists source text,
    add column if not exists source_event_id text,
    add column if not exists source_market_key text,
    add column if not exists source_selection_key text,
    add column if not exists source_observed_at timestamptz;

create index if not exists picks_source_event_idx
    on public.picks (source, source_event_id);

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'picks_source_audit_complete_check'
          and conrelid = 'public.picks'::regclass
    ) then
        -- Historical rows may remain entirely null; any row that starts an
        -- audit identity must carry the whole bounded identity atomically.
        alter table public.picks
            add constraint picks_source_audit_complete_check
            check (
                (
                    source is null
                    and source_event_id is null
                    and source_market_key is null
                    and source_selection_key is null
                    and source_observed_at is null
                )
                or (
                    length(btrim(source)) between 1 and 100
                    and length(btrim(source_event_id)) between 1 and 500
                    and length(btrim(source_market_key)) between 1 and 1000
                    and length(btrim(source_selection_key)) between 1 and 500
                    and source_observed_at is not null
                )
            ) not valid;
    end if;
end
$$;

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
    resultado_verificado_at,
    source,
    source_event_id,
    source_market_key,
    source_selection_key,
    source_observed_at
from public.picks
where visibility = 'public';

-- Replace the RPC after the columns exist so upgrades and fresh installations
-- both deserialize and insert the same complete source-audit contract.
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

    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where jsonb_typeof(value) <> 'object'
           or nullif(btrim(value->>'source'), '') is null
           or nullif(btrim(value->>'source_event_id'), '') is null
           or nullif(btrim(value->>'source_market_key'), '') is null
           or nullif(btrim(value->>'source_selection_key'), '') is null
           or nullif(btrim(value->>'source_observed_at'), '') is null
           or length(btrim(value->>'source')) not between 1 and 100
           or length(btrim(value->>'source_event_id')) not between 1 and 500
           or length(btrim(value->>'source_market_key')) not between 1 and 1000
           or length(btrim(value->>'source_selection_key')) not between 1 and 500
           or coalesce(value->>'source_observed_at', '')
                !~* '(z|[+-][0-9]{2}:[0-9]{2})$'
           or (value->>'source_observed_at')::timestamptz is null
    ) then
        raise exception 'each requested pick must have complete source audit fields';
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

    perform pg_advisory_xact_lock(20260820233000);

    insert into public.scraper_runs (run_key, source_hash)
    values (requested_run_key, requested_source_hash)
    on conflict (run_key) do nothing;

    select *
    into claimed_run
    from public.scraper_runs
    where run_key = requested_run_key
    for update;

    if claimed_run.source_hash <> requested_source_hash then
        raise exception 'run key % already belongs to a different source hash', requested_run_key;
    end if;

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
        (requested_rows.populated).source,
        (requested_rows.populated).source_event_id,
        (requested_rows.populated).source_market_key,
        (requested_rows.populated).source_selection_key,
        (requested_rows.populated).source_observed_at,
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

revoke all on function public.publish_pick_batch(text, text, jsonb)
    from public, anon, authenticated;
grant execute on function public.publish_pick_batch(text, text, jsonb)
    to service_role;

create or replace function public.scraper_schema_status()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'version', 2,
        'public_picks', to_regclass('public.public_picks') is not null,
        'publish_pick_batch',
            to_regprocedure('public.publish_pick_batch(text,text,jsonb)') is not null,
        'source_audit',
            exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_event_id'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_market_key'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_selection_key'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_observed_at'
            )
    );
$$;

revoke all on function public.scraper_schema_status()
    from public, anon, authenticated;
grant execute on function public.scraper_schema_status()
    to service_role;

commit;
