begin;

create table public.daily_pick_portfolios (
    portfolio_date date primary key,
    revision integer not null default 0 check (revision >= 0),
    release_revision integer not null default 0 check (release_revision >= 0),
    batch_id uuid unique references public.pick_batches(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.daily_pick_scans (
    id uuid primary key default gen_random_uuid(),
    run_key text not null unique,
    portfolio_date date not null references public.daily_pick_portfolios(portfolio_date),
    source_hash text not null,
    revision integer not null check (revision > 0),
    requested_picks jsonb not null check (jsonb_typeof(requested_picks) = 'array'),
    created_at timestamptz not null default now()
);

create table public.daily_pick_entries (
    id uuid primary key default gen_random_uuid(),
    portfolio_date date not null references public.daily_pick_portfolios(portfolio_date),
    position integer not null check (position between 1 and 6),
    active boolean not null default true,
    released_revision integer,
    pick_id bigint unique references public.picks(id),
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    physical_event_key text not null check (
        physical_event_key ~ '^physical:v1:[0-9a-f]{64}$'
    ),
    source text not null,
    source_event_id text not null,
    source_market_key text not null,
    source_selection_key text not null,
    visibility text not null check (visibility in ('public', 'premium')),
    es_parlay boolean not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (portfolio_date, position),
    unique (portfolio_date, physical_event_key),
    unique (
        portfolio_date,
        source,
        source_event_id,
        source_market_key,
        source_selection_key
    ),
    check ((released_revision is null) = (pick_id is null))
);

create table public.daily_pick_releases (
    run_id uuid primary key references public.scraper_runs(id) on delete cascade,
    portfolio_date date not null references public.daily_pick_portfolios(portfolio_date),
    batch_id uuid not null references public.pick_batches(id),
    revision integer not null check (revision > 0),
    feed_eligible boolean not null default false,
    created_at timestamptz not null default now(),
    unique (portfolio_date, revision)
);

alter table public.daily_pick_portfolios enable row level security;
alter table public.daily_pick_scans enable row level security;
alter table public.daily_pick_entries enable row level security;
alter table public.daily_pick_releases enable row level security;

revoke all on table public.daily_pick_portfolios from public, anon, authenticated;
revoke all on table public.daily_pick_scans from public, anon, authenticated;
revoke all on table public.daily_pick_entries from public, anon, authenticated;
revoke all on table public.daily_pick_releases from public, anon, authenticated;
grant select, insert, update, delete on table public.daily_pick_portfolios to service_role;
grant select, insert, update, delete on table public.daily_pick_scans to service_role;
grant select, insert, update, delete on table public.daily_pick_entries to service_role;
grant select, insert, update, delete on table public.daily_pick_releases to service_role;

create or replace function public.daily_returned_pick(picked public.picks)
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'id', picked.id,
        'categoria', picked.categoria,
        'partido', picked.partido,
        'pick', picked.pick,
        'cuota', picked.cuota,
        'confianza', picked.confianza,
        'razonamiento', picked.razonamiento,
        'marcador', picked.marcador,
        'estado', picked.estado,
        'es_parlay', picked.es_parlay,
        'liga', picked.liga,
        'mercado', picked.mercado,
        'riesgo', picked.riesgo,
        'resultado_apuesta', picked.resultado_apuesta,
        'ganancia_simulada', picked.ganancia_simulada,
        'fecha_generacion', picked.fecha_generacion,
        'fecha_evento', picked.fecha_evento,
        'horario', picked.horario,
        'odds_mercado', picked.odds_mercado,
        'tiene_valor', picked.tiene_valor,
        'visibility', picked.visibility,
        'source', picked.source,
        'source_event_id', picked.source_event_id,
        'source_market_key', picked.source_market_key,
        'source_selection_key', picked.source_selection_key,
        'source_observed_at', picked.source_observed_at,
        'source_starts_at', picked.source_starts_at
    );
$$;

revoke all on function public.daily_returned_pick(public.picks)
    from public, anon, authenticated, service_role;

create or replace function public.stage_daily_pick_portfolio(
    requested_run_key text,
    requested_portfolio_date date,
    requested_source_hash text,
    requested_picks jsonb
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    existing_scan public.daily_pick_scans%rowtype;
    locked_portfolio public.daily_pick_portfolios%rowtype;
    created_scan public.daily_pick_scans%rowtype;
    candidate_rows jsonb;
    released_count integer;
    released_public_count integer;
    selected_count integer;
    expected_public_count integer;
    needed_public_count integer;
    eligible_public_count integer;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be blank';
    end if;
    if requested_portfolio_date is null then
        raise exception 'requested_portfolio_date must not be null';
    end if;
    if requested_source_hash is null or btrim(requested_source_hash) = '' then
        raise exception 'requested_source_hash must not be blank';
    end if;
    if requested_picks is null
       or jsonb_typeof(requested_picks) <> 'array'
       or jsonb_array_length(requested_picks) not between 1 and 6 then
        raise exception 'requested_picks must contain between one and six picks';
    end if;
    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where jsonb_typeof(entry.value) <> 'object'
           or nullif(btrim(entry.value->>'source'), '') is null
           or nullif(btrim(entry.value->>'source_event_id'), '') is null
           or nullif(btrim(entry.value->>'source_market_key'), '') is null
           or nullif(btrim(entry.value->>'source_selection_key'), '') is null
           or nullif(btrim(entry.value->>'physical_event_key'), '') is null
           or (entry.value->>'physical_event_key') !~
                '^physical:v1:[0-9a-f]{64}$'
           or nullif(btrim(entry.value->>'source_observed_at'), '') is null
           or nullif(btrim(entry.value->>'source_starts_at'), '') is null
           or not (entry.value ? 'es_parlay')
           or jsonb_typeof(entry.value->'es_parlay') <> 'boolean'
    ) then
        raise exception 'requested_picks contain incomplete source audit fields';
    end if;
    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where (entry.value->>'source_observed_at') !~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$'
           or (entry.value->>'source_starts_at') !~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$'
           or (entry.value->>'source_observed_at')::timestamptz > clock_timestamp()
           or (entry.value->>'source_starts_at')::timestamptz <=
                (entry.value->>'source_observed_at')::timestamptz
           or (entry.value->>'source_starts_at')::timestamptz <= clock_timestamp()
    ) then
        raise exception 'requested_picks contain invalid source timestamps';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('rey-taco-daily:' || requested_portfolio_date::text, 0)
    );

    select scans.*
    into existing_scan
    from public.daily_pick_scans as scans
    where scans.run_key = requested_run_key
    for update;

    if found then
        if existing_scan.source_hash <> requested_source_hash
           or existing_scan.portfolio_date <> requested_portfolio_date then
            raise exception 'daily scan replay does not match original request';
        end if;
        return jsonb_build_object(
            'scan_id', existing_scan.id,
            'portfolio_date', existing_scan.portfolio_date,
            'revision', existing_scan.revision,
            'created', false
        );
    end if;

    insert into public.daily_pick_portfolios (portfolio_date)
    values (requested_portfolio_date)
    on conflict (portfolio_date) do nothing;

    select portfolios.*
    into locked_portfolio
    from public.daily_pick_portfolios as portfolios
    where portfolios.portfolio_date = requested_portfolio_date
    for update;

    select
        count(*),
        count(*) filter (where entries.visibility = 'public')
    into released_count, released_public_count
    from public.daily_pick_entries as entries
    where entries.portfolio_date = requested_portfolio_date
      and entries.active
      and entries.released_revision is not null;

    expected_public_count := case
        when released_count = 0 then 0
        when released_count = 6 then 2
        else 1
    end;
    if released_public_count <> expected_public_count then
        raise exception 'released daily portfolio has invalid public allocation';
    end if;

    with raw_candidates as (
        select
            candidate.value,
            candidate.ordinality,
            row_number() over (
                partition by btrim(candidate.value->>'physical_event_key')
                order by candidate.ordinality
            ) as event_position,
            row_number() over (
                partition by lower(btrim(candidate.value->>'source')),
                    btrim(candidate.value->>'source_event_id'),
                    btrim(candidate.value->>'source_market_key'),
                    btrim(candidate.value->>'source_selection_key')
                order by candidate.ordinality
            ) as audit_position
        from jsonb_array_elements(requested_picks)
            with ordinality as candidate(value, ordinality)
    ), eligible_candidates as (
        select raw.value, raw.ordinality
        from raw_candidates as raw
        where raw.event_position = 1
          and raw.audit_position = 1
          and not exists (
              select 1
              from public.daily_pick_entries as released
              where released.portfolio_date = requested_portfolio_date
                and released.active
                and released.released_revision is not null
                and released.physical_event_key =
                    btrim(raw.value->>'physical_event_key')
          )
          and not exists (
              select 1
              from public.daily_pick_entries as released
              where released.portfolio_date = requested_portfolio_date
                and released.active
                and released.released_revision is not null
                and lower(released.source) = lower(btrim(raw.value->>'source'))
                and released.source_event_id = btrim(raw.value->>'source_event_id')
                and released.source_market_key = btrim(raw.value->>'source_market_key')
                and released.source_selection_key = btrim(raw.value->>'source_selection_key')
          )
        order by raw.ordinality
        limit greatest(0, 6 - released_count)
    )
    select coalesce(jsonb_agg(eligible.value order by eligible.ordinality), '[]'::jsonb)
    into candidate_rows
    from eligible_candidates as eligible;

    selected_count := jsonb_array_length(candidate_rows);
    loop
        expected_public_count := case
            when released_count + selected_count = 0 then 0
            when released_count + selected_count = 6 then 2
            else 1
        end;
        needed_public_count := expected_public_count - released_public_count;
        select count(*)
        into eligible_public_count
        from jsonb_array_elements(candidate_rows)
            with ordinality as candidate(value, ordinality)
        where candidate.ordinality <= selected_count
          and (candidate.value->>'es_parlay')::boolean is false;
        exit when needed_public_count >= 0
              and eligible_public_count >= needed_public_count;
        if selected_count = 0 then
            raise exception 'daily draft cannot satisfy public allocation';
        end if;
        selected_count := selected_count - 1;
    end loop;

    update public.daily_pick_entries
    set active = false, updated_at = now()
    where portfolio_date = requested_portfolio_date
      and released_revision is null;
    delete from public.daily_pick_entries
    where portfolio_date = requested_portfolio_date
      and released_revision is null;

    with selected as (
        select candidate.value, candidate.ordinality,
            count(*) filter (
                where (candidate.value->>'es_parlay')::boolean is false
            ) over (
                order by candidate.ordinality
                rows between unbounded preceding and current row
            ) as safe_position
        from jsonb_array_elements(candidate_rows)
            with ordinality as candidate(value, ordinality)
        where candidate.ordinality <= selected_count
    ), prepared as (
        select
            selected.*,
            case
                when (selected.value->>'es_parlay')::boolean is false
                 and selected.safe_position <= needed_public_count
                    then 'public'
                else 'premium'
            end as assigned_visibility
        from selected
    )
    insert into public.daily_pick_entries (
        portfolio_date,
        position,
        payload,
        physical_event_key,
        source,
        source_event_id,
        source_market_key,
        source_selection_key,
        visibility,
        es_parlay
    )
    select
        requested_portfolio_date,
        released_count + prepared.ordinality,
        jsonb_set(
            prepared.value,
            '{visibility}',
            to_jsonb(prepared.assigned_visibility),
            true
        ),
        btrim(prepared.value->>'physical_event_key'),
        btrim(prepared.value->>'source'),
        btrim(prepared.value->>'source_event_id'),
        btrim(prepared.value->>'source_market_key'),
        btrim(prepared.value->>'source_selection_key'),
        prepared.assigned_visibility,
        (prepared.value->>'es_parlay')::boolean
    from prepared
    order by prepared.ordinality;

    update public.daily_pick_portfolios
    set revision = locked_portfolio.revision + 1,
        updated_at = now()
    where portfolio_date = requested_portfolio_date
    returning * into locked_portfolio;

    insert into public.daily_pick_scans (
        run_key,
        portfolio_date,
        source_hash,
        revision,
        requested_picks
    ) values (
        requested_run_key,
        requested_portfolio_date,
        requested_source_hash,
        locked_portfolio.revision,
        requested_picks
    ) returning * into created_scan;

    return jsonb_build_object(
        'scan_id', created_scan.id,
        'portfolio_date', created_scan.portfolio_date,
        'revision', created_scan.revision,
        'created', true
    );
end;
$$;

create or replace function public.release_daily_pick_portfolio(
    requested_run_key text,
    requested_portfolio_date date
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    locked_portfolio public.daily_pick_portfolios%rowtype;
    created_run public.scraper_runs%rowtype;
    existing_run public.scraper_runs%rowtype;
    existing_release public.daily_pick_releases%rowtype;
    first_result jsonb;
    requested_delta jsonb;
    requested_full jsonb;
    release_hash text;
    active_batch uuid;
    first_pick_id bigint;
    next_release_revision integer;
    full_picks jsonb;
    delivery_picks jsonb;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be blank';
    end if;
    if requested_portfolio_date is null then
        raise exception 'requested_portfolio_date must not be null';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('rey-taco-daily:' || requested_portfolio_date::text, 0)
    );
    perform pg_advisory_xact_lock(20260820233000);

    select runs.*
    into existing_run
    from public.scraper_runs as runs
    where runs.run_key = requested_run_key
    for update;
    if found then
        select releases.*
        into existing_release
        from public.daily_pick_releases as releases
        where releases.run_id = existing_run.id;
        if not found then
            raise exception 'release run key belongs to a non-daily run';
        end if;
        if existing_release.portfolio_date <> requested_portfolio_date then
            raise exception 'daily release replay date mismatch';
        end if;
        return public.resume_daily_pick_release(requested_run_key);
    end if;

    select portfolios.*
    into locked_portfolio
    from public.daily_pick_portfolios as portfolios
    where portfolios.portfolio_date = requested_portfolio_date
    for update;
    if not found then
        return null;
    end if;

    select coalesce(jsonb_agg(entries.payload order by entries.position), '[]'::jsonb)
    into requested_delta
    from public.daily_pick_entries as entries
    where entries.portfolio_date = requested_portfolio_date
      and entries.active
      and entries.released_revision is null;
    if jsonb_array_length(requested_delta) = 0 then
        return null;
    end if;
    if exists (
        select 1
        from jsonb_array_elements(requested_delta) as delta(value)
        where (delta.value->>'source_starts_at')::timestamptz <= clock_timestamp()
    ) then
        raise exception 'daily release delta is no longer pre-match';
    end if;

    select coalesce(jsonb_agg(entries.payload order by entries.position), '[]'::jsonb)
    into requested_full
    from public.daily_pick_entries as entries
    where entries.portfolio_date = requested_portfolio_date
      and entries.active;
    if jsonb_array_length(requested_full) not between 1 and 6 then
        raise exception 'daily release contains an invalid portfolio size';
    end if;

    next_release_revision := locked_portfolio.release_revision + 1;
    release_hash := encode(
        digest(
            requested_portfolio_date::text || ':' || requested_delta::text,
            'sha256'
        ),
        'hex'
    );

    if locked_portfolio.batch_id is null then
        first_result := public.publish_pick_batch(
            requested_run_key,
            release_hash,
            requested_full
        );
        active_batch := (first_result->>'batch_id')::uuid;
        created_run.id := (first_result->>'run_id')::uuid;
        created_run.delivery_status := coalesce(
            first_result->'delivery_status', '{}'::jsonb
        );

        update public.daily_pick_portfolios
        set batch_id = active_batch,
            release_revision = next_release_revision,
            updated_at = now()
        where portfolio_date = requested_portfolio_date;

        update public.daily_pick_entries as entry
        set released_revision = next_release_revision,
            pick_id = persisted.id,
            updated_at = now()
        from public.picks as persisted
        where entry.portfolio_date = requested_portfolio_date
          and entry.active
          and entry.released_revision is null
          and persisted.batch_id = active_batch
          and persisted.source = entry.source
          and persisted.source_event_id = entry.source_event_id
          and persisted.source_market_key = entry.source_market_key
          and persisted.source_selection_key = entry.source_selection_key;
    else
        active_batch := locked_portfolio.batch_id;
        if not exists (
            select 1 from public.pick_batches as batches
            where batches.id = active_batch and batches.active
        ) then
            raise exception 'daily portfolio batch is not active';
        end if;

        insert into public.scraper_runs (
            run_key, status, source_hash, delivery_status, finished_at
        ) values (
            requested_run_key, 'running', release_hash, '{}'::jsonb, null
        ) returning * into created_run;

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
            from jsonb_array_elements(requested_delta)
                with ordinality as item(value, ordinality)
        )
        insert into public.picks (
            id, categoria, partido, pick, cuota, confianza, razonamiento,
            marcador, estado, es_parlay, liga, mercado, riesgo,
            resultado_apuesta, ganancia_simulada, fecha_generacion,
            fecha_evento, horario, odds_mercado, tiene_valor, visibility,
            source, source_event_id, source_market_key, source_selection_key,
            source_observed_at, source_starts_at, batch_id, active
        )
        select
            first_pick_id + requested_rows.ordinality - 1,
            (requested_rows.populated).categoria,
            (requested_rows.populated).partido,
            (requested_rows.populated).pick,
            (requested_rows.populated).cuota,
            (requested_rows.populated).confianza,
            case when (requested_rows.populated).visibility = 'public'
                then null else (requested_rows.populated).razonamiento end,
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
            active_batch,
            true
        from requested_rows;

        update public.daily_pick_entries as entry
        set released_revision = next_release_revision,
            pick_id = persisted.id,
            updated_at = now()
        from public.picks as persisted
        where entry.portfolio_date = requested_portfolio_date
          and entry.active
          and entry.released_revision is null
          and persisted.batch_id = active_batch
          and persisted.source = entry.source
          and persisted.source_event_id = entry.source_event_id
          and persisted.source_market_key = entry.source_market_key
          and persisted.source_selection_key = entry.source_selection_key;

        update public.scraper_runs
        set status = 'published', finished_at = now()
        where id = created_run.id;
        update public.daily_pick_portfolios
        set release_revision = next_release_revision, updated_at = now()
        where portfolio_date = requested_portfolio_date;
    end if;

    if exists (
        select 1 from public.daily_pick_entries as entry
        where entry.portfolio_date = requested_portfolio_date
          and entry.active
          and entry.released_revision is null
    ) then
        raise exception 'daily release did not persist every delta entry';
    end if;

    insert into public.daily_pick_releases (
        run_id, portfolio_date, batch_id, revision, feed_eligible
    ) values (
        created_run.id,
        requested_portfolio_date,
        active_batch,
        next_release_revision,
        next_release_revision = 1
    );

    select coalesce(
        jsonb_agg(public.daily_returned_pick(persisted) order by persisted.id),
        '[]'::jsonb
    )
    into full_picks
    from public.picks as persisted
    where persisted.batch_id = active_batch
      and persisted.active;

    select coalesce(
        jsonb_agg(public.daily_returned_pick(persisted) order by persisted.id),
        '[]'::jsonb
    )
    into delivery_picks
    from public.daily_pick_entries as entries
    join public.picks as persisted on persisted.id = entries.pick_id
    where entries.portfolio_date = requested_portfolio_date
      and entries.active
      and entries.released_revision = next_release_revision;

    return jsonb_build_object(
        'run_id', created_run.id,
        'batch_id', active_batch,
        'created', true,
        'delivery_status', coalesce(created_run.delivery_status, '{}'::jsonb),
        'portfolio_date', requested_portfolio_date,
        'revision', next_release_revision,
        'feed_eligible', next_release_revision = 1,
        'picks', full_picks,
        'delivery_picks', delivery_picks
    );
end;
$$;

create or replace function public.resume_daily_pick_release(
    requested_run_key text
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    selected_run public.scraper_runs%rowtype;
    selected_release public.daily_pick_releases%rowtype;
    full_picks jsonb;
    delivery_picks jsonb;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be blank';
    end if;

    select runs.*
    into selected_run
    from public.scraper_runs as runs
    where runs.run_key = requested_run_key
      and runs.status in ('published', 'partial');
    if not found then
        return null;
    end if;

    select releases.*
    into selected_release
    from public.daily_pick_releases as releases
    where releases.run_id = selected_run.id;
    if not found then
        return null;
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('rey-taco-daily:' || selected_release.portfolio_date::text, 0)
    );
    perform pg_advisory_xact_lock(20260820233000);

    select coalesce(
        jsonb_agg(public.daily_returned_pick(persisted) order by persisted.id),
        '[]'::jsonb
    )
    into full_picks
    from public.picks as persisted
    where persisted.batch_id = selected_release.batch_id
      and persisted.active;

    select coalesce(
        jsonb_agg(public.daily_returned_pick(persisted) order by persisted.id),
        '[]'::jsonb
    )
    into delivery_picks
    from public.daily_pick_entries as entries
    join public.picks as persisted on persisted.id = entries.pick_id
    where entries.portfolio_date = selected_release.portfolio_date
      and entries.active
      and entries.released_revision = selected_release.revision;

    if jsonb_array_length(full_picks) not between 1 and 6
       or jsonb_array_length(delivery_picks) = 0 then
        raise exception 'daily release resume integrity error';
    end if;

    return jsonb_build_object(
        'run_id', selected_run.id,
        'batch_id', selected_release.batch_id,
        'created', false,
        'delivery_status', selected_run.delivery_status,
        'portfolio_date', selected_release.portfolio_date,
        'revision', selected_release.revision,
        'feed_eligible', selected_release.feed_eligible,
        'picks', full_picks,
        'delivery_picks', delivery_picks
    );
end;
$$;

-- The first revision receives one feed asset per destination. Later revisions
-- remain available to Telegram and future story publishing without duplicating
-- the main Facebook or Instagram feed.
create or replace function public.get_meta_social_batch(
    requested_run_key text
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    selected_run public.scraper_runs%rowtype;
    selected_batch public.pick_batches%rowtype;
    selected_release public.daily_pick_releases%rowtype;
    selected_pick public.picks%rowtype;
    eligible_pick_count bigint;
    public_pick_count bigint;
    expected_public_count integer;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be blank';
    end if;
    perform pg_advisory_xact_lock(20260820233000);

    select runs.*
    into selected_run
    from public.scraper_runs as runs
    where runs.run_key = requested_run_key
      and runs.status in ('published', 'partial');
    if not found then
        return null;
    end if;

    select releases.*
    into selected_release
    from public.daily_pick_releases as releases
    where releases.run_id = selected_run.id;
    if found then
        if selected_release.feed_eligible is false then
            return null;
        end if;
        select batches.*
        into selected_batch
        from public.pick_batches as batches
        where batches.id = selected_release.batch_id and batches.active;
    else
        select batches.*
        into selected_batch
        from public.pick_batches as batches
        where batches.run_id = selected_run.id and batches.active;
    end if;
    if not found then
        return null;
    end if;

    select
        count(*),
        count(*) filter (
            where picks.visibility = 'public'
              and picks.es_parlay = false
        )
    into eligible_pick_count, public_pick_count
    from public.picks as picks
    where picks.batch_id = selected_batch.id
      and picks.active
      and picks.estado = 'pendiente';

    expected_public_count := case when eligible_pick_count = 6 then 2 else 1 end;
    if eligible_pick_count not between 1 and 6
       or public_pick_count <> expected_public_count then
        raise exception 'meta social pick integrity error';
    end if;

    select picks.*
    into selected_pick
    from public.picks as picks
    where picks.batch_id = selected_batch.id
      and picks.active
      and picks.estado = 'pendiente'
      and picks.visibility = 'public'
      and picks.es_parlay = false
    order by picks.id
    limit 1;

    if selected_pick.source_audit_version is distinct from 1
       or nullif(btrim(selected_pick.source), '') is null
       or nullif(btrim(selected_pick.source_event_id), '') is null
       or nullif(btrim(selected_pick.source_market_key), '') is null
       or nullif(btrim(selected_pick.source_selection_key), '') is null
       or selected_pick.source_observed_at > clock_timestamp()
       or selected_pick.source_starts_at <= selected_pick.source_observed_at
       or selected_pick.source_starts_at <= clock_timestamp() then
        return null;
    end if;

    return jsonb_build_object(
        'run_id', selected_run.id,
        'batch_id', selected_batch.id,
        'delivery_status', selected_run.delivery_status,
        'public_pick', jsonb_build_object(
            'id', selected_pick.id,
            'categoria', selected_pick.categoria,
            'partido', selected_pick.partido,
            'pick', selected_pick.pick,
            'cuota', selected_pick.cuota,
            'confianza', selected_pick.confianza,
            'estado', selected_pick.estado,
            'es_parlay', selected_pick.es_parlay,
            'liga', selected_pick.liga,
            'mercado', selected_pick.mercado,
            'riesgo', selected_pick.riesgo,
            'fecha_generacion', selected_pick.fecha_generacion,
            'fecha_evento', selected_pick.fecha_evento,
            'horario', selected_pick.horario,
            'tiene_valor', selected_pick.tiene_valor,
            'visibility', selected_pick.visibility,
            'source', selected_pick.source,
            'source_event_id', selected_pick.source_event_id,
            'source_market_key', selected_pick.source_market_key,
            'source_selection_key', selected_pick.source_selection_key,
            'source_observed_at', selected_pick.source_observed_at,
            'source_starts_at', selected_pick.source_starts_at
        )
    );
end;
$$;

create or replace function public.daily_pick_schema_status()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select
        to_regclass('public.daily_pick_portfolios') is not null
        and to_regclass('public.daily_pick_scans') is not null
        and to_regclass('public.daily_pick_entries') is not null
        and to_regclass('public.daily_pick_releases') is not null
        and to_regprocedure('public.stage_daily_pick_portfolio(text,date,text,jsonb)') is not null
        and to_regprocedure('public.release_daily_pick_portfolio(text,date)') is not null
        and to_regprocedure('public.resume_daily_pick_release(text)') is not null
        and to_regprocedure('public.get_meta_social_batch(text)') is not null
        and (
            select count(*) = 4 and bool_and(classes.relrowsecurity)
            from pg_catalog.pg_class as classes
            join pg_catalog.pg_namespace as namespaces
              on namespaces.oid = classes.relnamespace
            where namespaces.nspname = 'public'
              and classes.relname in (
                  'daily_pick_portfolios',
                  'daily_pick_scans',
                  'daily_pick_entries',
                  'daily_pick_releases'
              )
        )
        and not exists (
            select 1
            from unnest(array[
                'public.daily_pick_portfolios',
                'public.daily_pick_scans',
                'public.daily_pick_entries',
                'public.daily_pick_releases'
            ]) as required_table(name)
            cross join unnest(array[
                'select', 'insert', 'update', 'delete'
            ]) as required_privilege(name)
            where has_table_privilege(
                    'anon', required_table.name,
                    required_privilege.name
                  )
               or has_table_privilege(
                    'authenticated', required_table.name,
                    required_privilege.name
                  )
               or not has_table_privilege(
                    'service_role', required_table.name,
                    required_privilege.name
                  )
        )
        and (
            select count(*) = 11
            from information_schema.columns as columns
            where columns.table_schema = 'public'
              and (columns.table_name, columns.column_name) in (
                  ('daily_pick_portfolios', 'portfolio_date'),
                  ('daily_pick_portfolios', 'revision'),
                  ('daily_pick_scans', 'run_key'),
                  ('daily_pick_scans', 'source_hash'),
                  ('daily_pick_scans', 'revision'),
                  ('daily_pick_entries', 'physical_event_key'),
                  ('daily_pick_entries', 'released_revision'),
                  ('daily_pick_entries', 'pick_id'),
                  ('daily_pick_entries', 'payload'),
                  ('daily_pick_entries', 'visibility'),
                  ('daily_pick_releases', 'feed_eligible')
              )
        )
        and exists (
            select 1
            from pg_catalog.pg_constraint as constraints
            where constraints.conrelid = 'public.daily_pick_entries'::regclass
              and constraints.contype = 'u'
              and pg_get_constraintdef(constraints.oid) =
                  'UNIQUE (portfolio_date, physical_event_key)'
        )
        and not exists (
            select 1
            from unnest(array[
                'public.stage_daily_pick_portfolio(text,date,text,jsonb)',
                'public.release_daily_pick_portfolio(text,date)',
                'public.resume_daily_pick_release(text)',
                'public.get_meta_social_batch(text)'
            ]) as required_function(signature)
            where not exists (
                    select 1
                    from pg_catalog.pg_proc as procedures
                    where procedures.oid =
                        to_regprocedure(required_function.signature)
                      and procedures.prosecdef
                      and procedures.prorettype = 'jsonb'::regtype
                  )
               or has_function_privilege(
                    'anon', required_function.signature, 'execute'
                  )
               or has_function_privilege(
                    'authenticated', required_function.signature, 'execute'
                  )
               or not has_function_privilege(
                    'service_role', required_function.signature, 'execute'
                  )
        );
$$;

revoke all on function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    from public, anon, authenticated;
grant execute on function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    to service_role;
revoke all on function public.release_daily_pick_portfolio(text, date)
    from public, anon, authenticated;
grant execute on function public.release_daily_pick_portfolio(text, date)
    to service_role;
revoke all on function public.resume_daily_pick_release(text)
    from public, anon, authenticated;
grant execute on function public.resume_daily_pick_release(text)
    to service_role;
revoke all on function public.get_meta_social_batch(text)
    from public, anon, authenticated;
grant execute on function public.get_meta_social_batch(text)
    to service_role;
revoke all on function public.daily_pick_schema_status()
    from public, anon, authenticated;
grant execute on function public.daily_pick_schema_status()
    to service_role;

commit;
