begin;

create table public.residential_event_watch (
    id uuid primary key default gen_random_uuid(),
    source text not null check (length(btrim(source)) between 1 and 100),
    source_event_id text not null check (
        length(btrim(source_event_id)) between 1 and 500
    ),
    sport text not null check (length(btrim(sport)) between 1 and 200),
    source_observed_at timestamptz not null,
    source_starts_at timestamptz not null,
    last_checked_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (source, source_event_id),
    check (source_starts_at > source_observed_at)
);

create index residential_event_watch_due_idx
    on public.residential_event_watch (source_starts_at, last_checked_at);

alter table public.residential_event_watch enable row level security;
revoke all on table public.residential_event_watch
    from public, anon, authenticated, service_role;

create or replace function public.record_residential_event_watch(
    requested_events jsonb
) returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    checked_at timestamptz := clock_timestamp();
    event_entry jsonb;
    observed_at timestamptz;
    starts_at timestamptz;
    recorded_count integer := 0;
begin
    if requested_events is null
       or jsonb_typeof(requested_events) <> 'array'
       or jsonb_array_length(requested_events) not between 1 and 5000 then
        raise exception 'requested_events must contain between one and 5000 events';
    end if;

    delete from public.residential_event_watch
    where source_starts_at < checked_at - interval '6 hours';

    for event_entry in
        select value
        from jsonb_array_elements(requested_events) as events(value)
    loop
        if jsonb_typeof(event_entry) <> 'object'
           or length(btrim(coalesce(event_entry->>'source', ''))) not between 1 and 100
           or length(btrim(coalesce(event_entry->>'source_event_id', ''))) not between 1 and 500
           or length(btrim(coalesce(event_entry->>'sport', ''))) not between 1 and 200
           or coalesce(event_entry->>'source_observed_at', '') !~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$'
           or coalesce(event_entry->>'source_starts_at', '') !~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$' then
            raise exception 'requested event watch row is invalid';
        end if;
        begin
            observed_at := (event_entry->>'source_observed_at')::timestamptz;
            starts_at := (event_entry->>'source_starts_at')::timestamptz;
        exception
            when invalid_datetime_format or datetime_field_overflow then
                raise exception 'requested event watch row is invalid';
        end;
        if observed_at > checked_at or starts_at <= observed_at then
            raise exception 'requested event watch timestamps are invalid';
        end if;

        insert into public.residential_event_watch (
            source,
            source_event_id,
            sport,
            source_observed_at,
            source_starts_at,
            last_checked_at,
            updated_at
        ) values (
            btrim(event_entry->>'source'),
            btrim(event_entry->>'source_event_id'),
            btrim(event_entry->>'sport'),
            observed_at,
            starts_at,
            checked_at,
            checked_at
        )
        on conflict (source, source_event_id) do update
        set sport = excluded.sport,
            source_observed_at = excluded.source_observed_at,
            source_starts_at = excluded.source_starts_at,
            last_checked_at = excluded.last_checked_at,
            updated_at = excluded.updated_at;
        recorded_count := recorded_count + 1;
    end loop;

    return recorded_count;
end;
$$;

create or replace function public.residential_adaptive_work_status(
    requested_portfolio_date date
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    checked_at timestamptz := clock_timestamp();
    server_mexico_date date;
    lineup_due boolean;
    quote_due boolean;
    recoverable_due boolean;
begin
    server_mexico_date := (checked_at at time zone 'America/Mexico_City')::date;
    if requested_portfolio_date is null
       or requested_portfolio_date <> server_mexico_date then
        raise exception 'requested portfolio date is not current in Mexico City';
    end if;

    select exists (
        select 1
        from public.residential_event_watch as watches
        where watches.source_starts_at between
                  checked_at + interval '15 minutes'
              and checked_at + interval '70 minutes'
          and watches.last_checked_at <= checked_at - interval '20 minutes'
          and (
              lower(watches.sport) like '%soccer%'
              or lower(watches.sport) like '%football%'
              or lower(watches.sport) like '%futbol%'
              or lower(watches.sport) like '%fútbol%'
          )
    ) into lineup_due;

    select exists (
        select 1
        from public.daily_pick_entries as entries
        where entries.portfolio_date = requested_portfolio_date
          and entries.active
          and entries.released_revision is null
          and (entries.payload->>'source_starts_at')::timestamptz between
                  checked_at + interval '10 minutes'
              and checked_at + interval '90 minutes'
          and (entries.payload->>'source_observed_at')::timestamptz <=
                checked_at - interval '15 minutes'
    ) into quote_due;

    select exists (
        select 1
        from public.scraper_runs as runs
        where runs.status = 'running'
          and runs.created_at between
                  checked_at - interval '6 hours'
              and checked_at - interval '30 minutes'
    ) into recoverable_due;

    return jsonb_build_object(
        'needs_collection', lineup_due or quote_due or recoverable_due,
        'lineup_due', lineup_due,
        'quote_due', quote_due,
        'recoverable_due', recoverable_due
    );
end;
$$;

revoke all on function public.record_residential_event_watch(jsonb)
    from public, anon, authenticated;
grant execute on function public.record_residential_event_watch(jsonb)
    to service_role;
revoke all on function public.residential_adaptive_work_status(date)
    from public, anon, authenticated;
grant execute on function public.residential_adaptive_work_status(date)
    to service_role;

commit;
