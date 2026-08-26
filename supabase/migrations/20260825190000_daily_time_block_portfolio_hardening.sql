begin;

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
    created_scan public.daily_pick_scans%rowtype;
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
    ), released_public_blocks as (
        select distinct
            (
                extract(
                    hour from (
                        (released.payload->>'source_starts_at')::timestamptz
                        at time zone 'America/Mexico_City'
                    )
                )::integer / 6
            ) as time_block
        from public.daily_pick_entries as released
        where released.portfolio_date = requested_portfolio_date
          and released.active
          and released.released_revision is not null
          and released.visibility = 'public'
          and not starts_new_round
    ), raw_candidates as (
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
            ) as time_block,
            row_number() over (
                partition by btrim(candidate.value->>'physical_event_key')
                order by candidate.ordinality
            ) as event_position,
            row_number() over (
                partition by
                    lower(btrim(candidate.value->>'source')),
                    btrim(candidate.value->>'source_event_id'),
                    btrim(candidate.value->>'source_market_key'),
                    btrim(candidate.value->>'source_selection_key')
                order by candidate.ordinality
            ) as audit_position
        from jsonb_array_elements(requested_picks)
            with ordinality as candidate(value, ordinality)
    ), deduplicated_candidates as (
        select candidate.value, candidate.ordinality, candidate.time_block
        from raw_candidates as candidate
        where candidate.event_position = 1
          and candidate.audit_position = 1
          and (
              starts_new_round
              or (
                  not exists (
                      select 1
                      from public.daily_pick_entries as released
                      where released.portfolio_date = requested_portfolio_date
                        and released.active
                        and released.released_revision is not null
                        and released.physical_event_key =
                            btrim(candidate.value->>'physical_event_key')
                  )
                  and not exists (
                      select 1
                      from public.daily_pick_entries as released
                      where released.portfolio_date = requested_portfolio_date
                        and released.active
                        and released.released_revision is not null
                        and lower(released.source) =
                            lower(btrim(candidate.value->>'source'))
                        and released.source_event_id =
                            btrim(candidate.value->>'source_event_id')
                        and released.source_market_key =
                            btrim(candidate.value->>'source_market_key')
                        and released.source_selection_key =
                            btrim(candidate.value->>'source_selection_key')
                  )
              )
          )
    ), ranked_candidates as (
        select
            candidate.value,
            candidate.ordinality,
            candidate.time_block,
            row_number() over (
                partition by candidate.time_block
                order by candidate.ordinality
            ) as block_position
        from deduplicated_candidates as candidate
    ), allowed_candidates as (
        select
            candidate.value,
            candidate.ordinality,
            candidate.time_block,
            case
                when released_pick_count between 1 and 5
                 and (candidate.value->>'es_parlay')::boolean is false
                 and not exists (
                     select 1
                     from released_public_blocks as public_block
                     where public_block.time_block = candidate.time_block
                 ) then 0
                else 1
            end as public_block_priority
        from ranked_candidates as candidate
        left join released_blocks as released
            on released.time_block = candidate.time_block
        where candidate.block_position <= greatest(
            0,
            2 - coalesce(released.released_count, 0)
        )
    )
    select coalesce(
        jsonb_agg(
            allowed.value
            order by allowed.public_block_priority, allowed.ordinality
        ),
        '[]'::jsonb
    )
    into filtered_picks
    from allowed_candidates as allowed;

    if filtered_picks is null or jsonb_array_length(filtered_picks) = 0 then
        if locked_portfolio.portfolio_date is null
           or locked_portfolio.revision <= 0 then
            raise exception 'daily time blocks produced no eligible candidates';
        end if;
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
