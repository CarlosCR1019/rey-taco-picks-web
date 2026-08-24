begin;

create table public.result_report_deliveries (
    batch_id uuid not null references public.pick_batches(id),
    portfolio_date date not null references public.daily_pick_portfolios(portfolio_date),
    report_kind text not null check (report_kind in ('evening', 'final')),
    destination text not null check (
        destination in ('admin', 'vip', 'free', 'facebook', 'instagram')
    ),
    report_digest text not null check (report_digest ~ '^[0-9a-f]{64}$'),
    state text not null check (state in ('in_progress', 'success', 'failed')),
    attempt_id uuid not null,
    error text not null default '',
    receipt text not null default '',
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    primary key (batch_id, report_kind, destination)
);

alter table public.result_report_deliveries enable row level security;

create or replace function public.get_result_report_batches()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    server_mexico_date date := (clock_timestamp() at time zone 'America/Mexico_City')::date;
    result jsonb;
begin
    select coalesce(
        jsonb_agg(
            jsonb_build_object('picks', selected.picks)
            order by selected.portfolio_date
        ),
        '[]'::jsonb
    )
    into result
    from (
        select
            entries.portfolio_date,
            jsonb_agg(
                jsonb_build_object(
                    'id', picks.id,
                    'batch_id', picks.batch_id,
                    'portfolio_date', entries.portfolio_date,
                    'partido', picks.partido,
                    'pick', picks.pick,
                    'cuota', picks.cuota,
                    'estado', picks.estado,
                    'resultado_fuente', picks.resultado_fuente,
                    'resultado_evento_id', picks.resultado_evento_id,
                    'resultado_marcador', picks.resultado_marcador,
                    'resultado_verificado_at', picks.resultado_verificado_at
                )
                order by entries.position
            ) as picks
        from public.daily_pick_entries as entries
        join public.picks as picks on picks.id = entries.pick_id
        where entries.portfolio_date between server_mexico_date - 1 and server_mexico_date
          and entries.active
          and entries.released_revision is not null
        group by entries.portfolio_date
        having count(*) = 6
           and count(distinct picks.id) = 6
           and count(distinct picks.batch_id) = 1
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
    if requested_destination not in ('admin', 'vip', 'free', 'facebook', 'instagram') then
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
    from public.daily_pick_entries as entries
    join public.picks as picks on picks.id = entries.pick_id
    where entries.portfolio_date = requested_portfolio_date
      and entries.active
      and entries.released_revision is not null
      and picks.batch_id = requested_batch_id;
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

create or replace function public.complete_result_report_delivery(
    requested_batch_id uuid,
    requested_report_kind text,
    requested_destination text,
    requested_report_digest text,
    requested_attempt_id uuid,
    requested_success boolean,
    requested_error text,
    requested_receipt text
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if requested_batch_id is null
       or requested_attempt_id is null
       or requested_success is null then
        raise exception 'result report completion values must not be null';
    end if;
    if requested_report_kind not in ('evening', 'final') then
        raise exception 'invalid result report kind';
    end if;
    if requested_destination not in ('admin', 'vip', 'free', 'facebook', 'instagram') then
        raise exception 'invalid result report destination';
    end if;
    if requested_report_digest is null
       or requested_report_digest !~ '^[0-9a-f]{64}$' then
        raise exception 'invalid result report digest';
    end if;
    if requested_error is null or requested_receipt is null then
        raise exception 'result report completion strings must not be null';
    end if;
    if requested_success then
        if requested_error <> ''
           or requested_receipt !~ '^[A-Za-z0-9_:-]{1,256}$' then
            raise exception 'successful result report completion is invalid';
        end if;
    elsif requested_receipt <> ''
       or requested_error !~ '^[a-z_]{1,64}$' then
        raise exception 'failed result report completion is invalid';
    end if;

    update public.result_report_deliveries as deliveries
    set state = case when requested_success then 'success' else 'failed' end,
        error = requested_error,
        receipt = requested_receipt,
        updated_at = clock_timestamp()
    where deliveries.batch_id = requested_batch_id
      and deliveries.report_kind = requested_report_kind
      and deliveries.destination = requested_destination
      and deliveries.report_digest = requested_report_digest
      and deliveries.attempt_id = requested_attempt_id
      and deliveries.state = 'in_progress';

    if not found then
        raise exception 'result report completion did not match an active claim';
    end if;
    return jsonb_build_object('completed', true);
end;
$$;

revoke all on table public.result_report_deliveries
    from public, anon, authenticated;
grant select, insert, update, delete on table public.result_report_deliveries
    to service_role;

revoke all on function public.get_result_report_batches()
    from public, anon, authenticated;
revoke all on function public.claim_result_report_delivery(uuid, date, text, text, text, uuid)
    from public, anon, authenticated;
revoke all on function public.complete_result_report_delivery(uuid, text, text, text, uuid, boolean, text, text)
    from public, anon, authenticated;

grant execute on function public.get_result_report_batches()
    to service_role;
grant execute on function public.claim_result_report_delivery(uuid, date, text, text, text, uuid)
    to service_role;
grant execute on function public.complete_result_report_delivery(uuid, text, text, text, uuid, boolean, text, text)
    to service_role;

commit;
