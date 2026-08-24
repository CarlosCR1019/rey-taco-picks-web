begin;

alter table public.daily_pick_portfolios
    add column if not exists round_number integer not null default 1
        check (round_number > 0);
alter table public.daily_pick_releases
    add column if not exists round_number integer not null default 1
        check (round_number > 0);

alter function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    rename to stage_daily_pick_portfolio_one_round_v1;
alter function public.release_daily_pick_portfolio(text, date)
    rename to release_daily_pick_portfolio_one_round_v1;

revoke all on function public.stage_daily_pick_portfolio_one_round_v1(text, date, text, jsonb)
    from public, anon, authenticated, service_role;
revoke all on function public.release_daily_pick_portfolio_one_round_v1(text, date)
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
    locked_portfolio public.daily_pick_portfolios%rowtype;
    released_pick_count integer := 0;
    verified_final_count integer := 0;
    draft_pick_count integer := 0;
begin
    if requested_portfolio_date is null then
        raise exception 'requested_portfolio_date must not be null';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended(
            'rey-taco-daily:' || requested_portfolio_date::text,
            0
        )
    );

    select portfolios.*
    into locked_portfolio
    from public.daily_pick_portfolios as portfolios
    where portfolios.portfolio_date = requested_portfolio_date
    for update;

    if found and locked_portfolio.batch_id is not null then
        select
            count(*) filter (
                where entries.released_revision is not null
                  and picks.batch_id = locked_portfolio.batch_id
            ),
            count(*) filter (
                where entries.released_revision is not null
                  and picks.batch_id = locked_portfolio.batch_id
                  and picks.estado in ('ganado', 'perdido', 'void')
                  and picks.resultado_verificado_at is not null
            ),
            count(*) filter (where entries.released_revision is null)
        into released_pick_count, verified_final_count, draft_pick_count
        from public.daily_pick_entries as entries
        left join public.picks as picks on picks.id = entries.pick_id
        where entries.portfolio_date = requested_portfolio_date
          and entries.active;

        if released_pick_count between 1 and 6
           and verified_final_count = released_pick_count
           and draft_pick_count = 0 then
            delete from public.daily_pick_entries
            where portfolio_date = requested_portfolio_date;

            update public.daily_pick_portfolios
            set batch_id = null,
                round_number = round_number + 1,
                updated_at = clock_timestamp()
            where portfolio_date = requested_portfolio_date;
        end if;
    end if;

    return public.stage_daily_pick_portfolio_one_round_v1(
        requested_run_key,
        requested_portfolio_date,
        requested_source_hash,
        requested_picks
    );
end;
$$;

create or replace function public.release_daily_pick_portfolio(
    requested_run_key text,
    requested_portfolio_date date
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, extensions, public, pg_temp
as $$
declare
    existing_release public.daily_pick_releases%rowtype;
    current_round integer;
    legacy_result jsonb;
    returned_run_id uuid;
    first_release_in_round boolean;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be blank';
    end if;
    if requested_portfolio_date is null then
        raise exception 'requested_portfolio_date must not be null';
    end if;

    select releases.*
    into existing_release
    from public.scraper_runs as runs
    join public.daily_pick_releases as releases on releases.run_id = runs.id
    where runs.run_key = requested_run_key;

    if found then
        legacy_result := public.release_daily_pick_portfolio_one_round_v1(
            requested_run_key,
            requested_portfolio_date
        );
        if legacy_result is null then
            return null;
        end if;
        return jsonb_set(
            legacy_result,
            '{feed_eligible}',
            to_jsonb(existing_release.feed_eligible),
            true
        );
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended(
            'rey-taco-daily:' || requested_portfolio_date::text,
            0
        )
    );

    select portfolios.round_number
    into current_round
    from public.daily_pick_portfolios as portfolios
    where portfolios.portfolio_date = requested_portfolio_date
    for update;
    if not found then
        return null;
    end if;

    first_release_in_round := not exists (
        select 1
        from public.daily_pick_releases as releases
        where releases.portfolio_date = requested_portfolio_date
          and releases.round_number = current_round
    );

    legacy_result := public.release_daily_pick_portfolio_one_round_v1(
        requested_run_key,
        requested_portfolio_date
    );
    if legacy_result is null then
        return null;
    end if;

    returned_run_id := (legacy_result->>'run_id')::uuid;
    update public.daily_pick_releases
    set round_number = current_round,
        feed_eligible = first_release_in_round
    where run_id = returned_run_id;
    if not found then
        raise exception 'daily round release ledger is missing';
    end if;

    return jsonb_set(
        legacy_result,
        '{feed_eligible}',
        to_jsonb(first_release_in_round),
        true
    );
end;
$$;

create or replace function public.get_result_report_batches()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    server_mexico_date date :=
        (clock_timestamp() at time zone 'America/Mexico_City')::date;
    result jsonb;
begin
    select coalesce(
        jsonb_agg(
            jsonb_build_object('picks', selected.picks)
            order by selected.portfolio_date, selected.round_number
        ),
        '[]'::jsonb
    )
    into result
    from (
        select
            batches.portfolio_date,
            batches.round_number,
            jsonb_agg(
                jsonb_build_object(
                    'id', picks.id,
                    'batch_id', picks.batch_id,
                    'portfolio_date', batches.portfolio_date,
                    'partido', picks.partido,
                    'pick', picks.pick,
                    'cuota', picks.cuota,
                    'estado', picks.estado,
                    'resultado_fuente', picks.resultado_fuente,
                    'resultado_evento_id', picks.resultado_evento_id,
                    'resultado_marcador', picks.resultado_marcador,
                    'resultado_verificado_at', picks.resultado_verificado_at
                )
                order by picks.id
            ) as picks
        from (
            select distinct
                releases.portfolio_date,
                releases.batch_id,
                releases.round_number
            from public.daily_pick_releases as releases
            where releases.portfolio_date between
                server_mexico_date - 1 and server_mexico_date
        ) as batches
        join public.picks as picks on picks.batch_id = batches.batch_id
        group by
            batches.portfolio_date,
            batches.round_number,
            batches.batch_id
        having count(*) = 6
           and count(distinct picks.id) = 6
    ) as selected;

    return result;
end;
$$;

create or replace function public.claim_result_report_delivery(
    requested_batch_id uuid,
    requested_portfolio_date date,
    requested_report_kind text,
    requested_destination text,
    requested_report_digest text,
    requested_attempt_id uuid
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    existing_delivery public.result_report_deliveries%rowtype;
    portfolio_pick_count integer;
begin
    if requested_batch_id is null
       or requested_portfolio_date is null
       or requested_attempt_id is null then
        raise exception 'result report claim identifiers must not be null';
    end if;
    if requested_report_kind not in ('evening', 'final') then
        raise exception 'invalid result report kind';
    end if;
    if requested_destination not in (
        'admin', 'vip', 'free', 'facebook', 'instagram'
    ) then
        raise exception 'invalid result report destination';
    end if;
    if requested_report_digest is null
       or requested_report_digest !~ '^[0-9a-f]{64}$' then
        raise exception 'invalid result report digest';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended(
            'result-report:' || requested_batch_id::text || ':' ||
            requested_report_kind || ':' || requested_destination,
            0
        )
    );

    select count(*)
    into portfolio_pick_count
    from public.picks as picks
    where picks.batch_id = requested_batch_id
      and exists (
          select 1
          from public.daily_pick_releases as releases
          where releases.portfolio_date = requested_portfolio_date
            and releases.batch_id = requested_batch_id
      );
    if portfolio_pick_count <> 6 then
        raise exception 'result report claim requires one six-pick portfolio';
    end if;

    select deliveries.*
    into existing_delivery
    from public.result_report_deliveries as deliveries
    where deliveries.batch_id = requested_batch_id
      and deliveries.report_kind = requested_report_kind
      and deliveries.destination = requested_destination
    for update;

    if not found then
        insert into public.result_report_deliveries (
            batch_id,
            portfolio_date,
            report_kind,
            destination,
            report_digest,
            state,
            attempt_id
        ) values (
            requested_batch_id,
            requested_portfolio_date,
            requested_report_kind,
            requested_destination,
            requested_report_digest,
            'in_progress',
            requested_attempt_id
        );
        return jsonb_build_object(
            'state', 'claimed',
            'attempt_id', requested_attempt_id
        );
    end if;

    if existing_delivery.state = 'success' then
        return jsonb_build_object('state', 'complete', 'attempt_id', null);
    end if;
    if existing_delivery.state = 'in_progress' then
        return jsonb_build_object('state', 'ambiguous', 'attempt_id', null);
    end if;
    if existing_delivery.state = 'failed' then
        update public.result_report_deliveries as deliveries
        set portfolio_date = requested_portfolio_date,
            report_digest = requested_report_digest,
            state = 'in_progress',
            attempt_id = requested_attempt_id,
            error = '',
            receipt = '',
            updated_at = clock_timestamp()
        where deliveries.batch_id = requested_batch_id
          and deliveries.report_kind = requested_report_kind
          and deliveries.destination = requested_destination;
        return jsonb_build_object(
            'state', 'claimed',
            'attempt_id', requested_attempt_id
        );
    end if;

    raise exception 'invalid persisted result report state';
end;
$$;

revoke all on function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    from public, anon, authenticated;
grant execute on function public.stage_daily_pick_portfolio(text, date, text, jsonb)
    to service_role;
revoke all on function public.release_daily_pick_portfolio(text, date)
    from public, anon, authenticated;
grant execute on function public.release_daily_pick_portfolio(text, date)
    to service_role;
revoke all on function public.get_result_report_batches()
    from public, anon, authenticated;
grant execute on function public.get_result_report_batches()
    to service_role;
revoke all on function public.claim_result_report_delivery(uuid, date, text, text, text, uuid)
    from public, anon, authenticated;
grant execute on function public.claim_result_report_delivery(uuid, date, text, text, text, uuid)
    to service_role;

commit;
