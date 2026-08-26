begin;

alter function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    rename to stage_daily_pick_portfolio_unbounded_windows_v1;

revoke all on function public.stage_daily_pick_portfolio_unbounded_windows_v1(text, date, text, jsonb)
    from public, anon, authenticated, service_role;

create or replace function public.stage_daily_pick_portfolio(
    requested_run_key text,
    requested_portfolio_date date,
    requested_source_hash text,
    requested_picks jsonb
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    existing_scan public.daily_pick_scans%rowtype;
    latest_scan public.daily_pick_scans%rowtype;
    locked_portfolio public.daily_pick_portfolios%rowtype;
    released_pick_count integer := 0;
    verified_final_count integer := 0;
    draft_pick_count integer := 0;
    starts_new_round boolean := false;
    filtered_picks jsonb := '[]'::jsonb;
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

    perform pg_advisory_xact_lock(
        hashtextextended(
            'rey-taco-daily:' || requested_portfolio_date::text,
            0
        )
    );

    select scans.*
    into existing_scan
    from public.daily_pick_scans as scans
    where scans.run_key = requested_run_key;
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

    select portfolios.*
    into locked_portfolio
    from public.daily_pick_portfolios as portfolios
    where portfolios.portfolio_date = requested_portfolio_date
    for update;

    if found and locked_portfolio.batch_id is not null then
        select
            count(*) filter (
                where released.released_revision is not null
                  and picks.batch_id = locked_portfolio.batch_id
            ),
            count(*) filter (
                where released.released_revision is not null
                  and picks.batch_id = locked_portfolio.batch_id
                  and picks.estado in ('ganado', 'perdido', 'void')
                  and picks.resultado_verificado_at is not null
            ),
            count(*) filter (where released.released_revision is null)
        into released_pick_count, verified_final_count, draft_pick_count
        from public.daily_pick_entries as released
        left join public.picks as picks on picks.id = released.pick_id
        where released.portfolio_date = requested_portfolio_date
          and released.active;

        starts_new_round := released_pick_count between 1 and 6
            and verified_final_count = released_pick_count
            and draft_pick_count = 0;
    end if;

    with released_blocks as (
        select
            (
                extract(
                    hour from (
                        (released.payload->>'source_starts_at')::timestamptz
                        at time zone 'America/Mexico_City'
                    )
                )::integer / 6
            ) as time_block,
            count(*)::integer as released_count
        from public.daily_pick_entries as released
        where released.portfolio_date = requested_portfolio_date
          and released.active
          and released.released_revision is not null
          and not starts_new_round
        group by 1
    ), candidate_blocks as (
        select
            candidate.value,
            candidate.ordinality,
            (
                extract(
                    hour from (
                        (candidate.value->>'source_starts_at')::timestamptz
                        at time zone 'America/Mexico_City'
                    )
                )::integer / 6
            ) as time_block
        from jsonb_array_elements(requested_picks)
            with ordinality as candidate(value, ordinality)
    ), ranked_candidates as (
        select
            candidate.value,
            candidate.ordinality,
            candidate.time_block,
            row_number() over (
                partition by candidate.time_block
                order by candidate.ordinality
            ) as block_position
        from candidate_blocks as candidate
    ), allowed_candidates as (
        select candidate.value, candidate.ordinality
        from ranked_candidates as candidate
        left join released_blocks as released
            on released.time_block = candidate.time_block
        where candidate.block_position <= greatest(
            0,
            2 - coalesce(released.released_count, 0)
        )
        order by candidate.ordinality
    )
    select coalesce(
        jsonb_agg(allowed.value order by allowed.ordinality),
        '[]'::jsonb
    )
    into filtered_picks
    from allowed_candidates as allowed;

    if filtered_picks is null or jsonb_array_length(filtered_picks) = 0 then
        select scans.*
        into latest_scan
        from public.daily_pick_scans as scans
        where scans.portfolio_date = requested_portfolio_date
        order by scans.revision desc, scans.created_at desc
        limit 1;
        if not found then
            raise exception 'daily time blocks produced no eligible candidates';
        end if;
        return jsonb_build_object(
            'scan_id', latest_scan.id,
            'portfolio_date', latest_scan.portfolio_date,
            'revision', latest_scan.revision,
            'created', false
        );
    end if;

    return public.stage_daily_pick_portfolio_unbounded_windows_v1(
        requested_run_key,
        requested_portfolio_date,
        requested_source_hash,
        filtered_picks
    );
end;
$$;

revoke all on function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    from public, anon, authenticated;
grant execute on function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    to service_role;

commit;
