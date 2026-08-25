begin;

drop index if exists public.vertical_one_reel_per_day_destination;

create unique index vertical_one_reel_per_day_destination
  on public.vertical_media_deliveries(portfolio_date, destination, template_version)
  where content_kind = 'daily_results_reel';

create or replace function public.get_result_report_batches()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  server_mexico_date date := (
    clock_timestamp() at time zone 'America/Mexico_City'
  )::date;
  result jsonb;
begin
  with released_batches as (
    select distinct releases.portfolio_date, releases.batch_id
    from public.daily_pick_releases as releases
    where releases.portfolio_date
      between server_mexico_date - 1 and server_mexico_date
  )
  select coalesce(
    jsonb_agg(
      jsonb_build_object('picks', selected.picks)
      order by selected.portfolio_date, selected.batch_id
    ),
    '[]'::jsonb
  )
  into result
  from (
    select
      released_batches.portfolio_date,
      released_batches.batch_id,
      jsonb_agg(
        jsonb_build_object(
          'id', picks.id,
          'batch_id', picks.batch_id,
          'portfolio_date', released_batches.portfolio_date,
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
    from released_batches
    join public.picks as picks on picks.batch_id = released_batches.batch_id
    group by released_batches.portfolio_date, released_batches.batch_id
    having count(*) = 6 and count(distinct picks.id) = 6
  ) as selected;

  return result;
end
$$;

create or replace function public.claim_vertical_media_delivery(
  requested_batch_id uuid,
  requested_portfolio_date date,
  requested_content_kind text,
  requested_destination text,
  requested_content_digest text,
  requested_template_version integer,
  requested_attempt_id uuid,
  requested_lease_expires_at timestamptz
) returns table(state text, attempt_id uuid)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  selected public.vertical_media_deliveries%rowtype;
begin
  if requested_batch_id is null
     or requested_portfolio_date is null
     or requested_content_kind not in (
       'public_pick_story','vip_teaser_story','final_results_story',
       'verified_result_story','ticket_evidence_story','reel_cta_story',
       'daily_results_reel'
     )
     or requested_destination not in (
       'instagram_story','instagram_reel','facebook_reel'
     )
     or requested_content_digest !~ '^[0-9a-f]{64}$'
     or requested_template_version <= 0
     or requested_attempt_id is null
     or requested_lease_expires_at <= now()
     or requested_lease_expires_at > now() + interval '10 minutes'
  then
    raise exception 'invalid vertical claim';
  end if;

  insert into public.vertical_media_deliveries (
    batch_id, portfolio_date, content_kind, destination,
    content_digest, template_version
  ) values (
    requested_batch_id, requested_portfolio_date, requested_content_kind,
    requested_destination, requested_content_digest, requested_template_version
  ) on conflict do nothing;

  if requested_content_kind = 'daily_results_reel' then
    select * into selected
      from public.vertical_media_deliveries
      where portfolio_date = requested_portfolio_date
        and content_kind = 'daily_results_reel'
        and destination = requested_destination
        and template_version = requested_template_version
      for update;
  else
    select * into selected
      from public.vertical_media_deliveries
      where batch_id = requested_batch_id
        and content_kind = requested_content_kind
        and destination = requested_destination
        and content_digest = requested_content_digest
        and template_version = requested_template_version
      for update;
  end if;

  if selected.id is null then
    raise exception 'vertical claim row unavailable';
  end if;
  if selected.state = 'complete' then
    return query select 'complete'::text, null::uuid;
    return;
  end if;
  if selected.state = 'pending_review' then
    return query select 'ambiguous'::text, null::uuid;
    return;
  end if;
  if selected.state = 'claimed' and selected.lease_expires_at > now() then
    return query select 'ambiguous'::text, null::uuid;
    return;
  end if;

  update public.vertical_media_deliveries
    set state = 'claimed',
        attempt_id = requested_attempt_id,
        lease_expires_at = requested_lease_expires_at,
        updated_at = now(),
        receipt = '',
        error = ''
    where id = selected.id;

  return query select 'claimed'::text, requested_attempt_id;
end
$$;

revoke all on function public.claim_vertical_media_delivery(uuid, date, text, text, text, integer, uuid, timestamptz)
  from public, anon, authenticated, service_role;
grant execute on function public.claim_vertical_media_delivery(uuid, date, text, text, text, integer, uuid, timestamptz)
  to service_role;

-- The settled ticket and an independent result page both show 4-0.  Keep this
-- correction narrowly optimistic so a fresh database or changed row is untouched.
update public.picks
set resultado_marcador = '4-0',
    resultado_fuente = 'playdoit_ticket+checklive',
    resultado_evento_id =
      'https://checklive.com/event-hougang-united-fc-ii-tampines-rovers-ii',
    resultado_verificado_at = clock_timestamp(),
    updated_at = clock_timestamp()
where id = 1787559629973070
  and batch_id = '8e13c40d-b4a7-4a9b-b3b6-9b7d662ac49d'::uuid
  and estado = 'ganado'
  and resultado_marcador = '2-0';

commit;
