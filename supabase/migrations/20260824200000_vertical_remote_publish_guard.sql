begin;

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

  if requested_content_kind = 'daily_results_reel' then
    update public.vertical_media_deliveries
      set batch_id = requested_batch_id,
          content_digest = requested_content_digest,
          template_version = requested_template_version
      where id = selected.id;
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

create or replace function public.begin_vertical_remote_delivery(
  requested_batch_id uuid,
  requested_content_kind text,
  requested_destination text,
  requested_content_digest text,
  requested_template_version integer,
  requested_attempt_id uuid
) returns table(started boolean)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  selected public.vertical_media_deliveries%rowtype;
begin
  if requested_batch_id is null
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
  then
    raise exception 'invalid vertical remote transition';
  end if;

  select * into selected
    from public.vertical_media_deliveries
    where batch_id = requested_batch_id
      and content_kind = requested_content_kind
      and destination = requested_destination
      and content_digest = requested_content_digest
      and template_version = requested_template_version
    for update;

  if selected.id is null then
    return query select false;
    return;
  end if;
  if selected.state = 'pending_review'
     and selected.attempt_id = requested_attempt_id
  then
    return query select true;
    return;
  end if;
  if selected.state <> 'claimed'
     or selected.attempt_id <> requested_attempt_id
  then
    return query select false;
    return;
  end if;

  update public.vertical_media_deliveries
    set state = 'pending_review',
        lease_expires_at = null,
        receipt = '',
        error = '',
        updated_at = now()
    where id = selected.id
      and state = 'claimed'
      and attempt_id = requested_attempt_id;

  if not found then
    return query select false;
    return;
  end if;
  return query select true;
end
$$;

create or replace function public.complete_vertical_media_delivery(
  requested_batch_id uuid,
  requested_content_kind text,
  requested_destination text,
  requested_content_digest text,
  requested_template_version integer,
  requested_attempt_id uuid,
  requested_success boolean,
  requested_receipt text,
  requested_error text
) returns table(completed boolean)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  selected public.vertical_media_deliveries%rowtype;
begin
  if requested_batch_id is null
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
     or requested_success is null
     or requested_receipt is null
     or requested_error is null
     or (
       requested_success and (
         requested_error <> ''
         or char_length(requested_receipt) not between 1 and 256
         or requested_receipt !~ '^[A-Za-z0-9_:-]+$'
       )
     )
     or (
       not requested_success and (
         requested_receipt <> ''
         or requested_error not in (
           'not_configured','token_invalid','delivery_failed','media_invalid'
         )
       )
     )
  then
    raise exception 'invalid vertical completion';
  end if;

  select * into selected
    from public.vertical_media_deliveries
    where batch_id = requested_batch_id
      and content_kind = requested_content_kind
      and destination = requested_destination
      and content_digest = requested_content_digest
      and template_version = requested_template_version
    for update;

  if selected.id is null then
    return query select false;
    return;
  end if;
  if selected.state = 'complete' then
    return query select (
      requested_success
      and selected.attempt_id = requested_attempt_id
      and selected.receipt = requested_receipt
      and selected.error = ''
    );
    return;
  end if;
  if selected.state = 'failed' then
    return query select (
      not requested_success
      and selected.attempt_id = requested_attempt_id
      and selected.receipt = ''
      and selected.error = requested_error
    );
    return;
  end if;
  if selected.state not in ('claimed', 'pending_review')
     or selected.attempt_id <> requested_attempt_id
  then
    return query select false;
    return;
  end if;

  update public.vertical_media_deliveries
    set state = case when requested_success then 'complete' else 'failed' end,
        receipt = case when requested_success then requested_receipt else '' end,
        error = case when requested_success then '' else requested_error end,
        attempt_id = requested_attempt_id,
        lease_expires_at = null,
        updated_at = now()
    where id = selected.id
      and state in ('claimed', 'pending_review')
      and attempt_id = requested_attempt_id;

  if not found then
    return query select false;
    return;
  end if;
  return query select true;
end
$$;

revoke all on function public.claim_vertical_media_delivery(uuid, date, text, text, text, integer, uuid, timestamptz) from public, anon, authenticated, service_role;
grant execute on function public.claim_vertical_media_delivery(uuid, date, text, text, text, integer, uuid, timestamptz) to service_role;

revoke all on function public.begin_vertical_remote_delivery(uuid, text, text, text, integer, uuid) from public, anon, authenticated, service_role;
grant execute on function public.begin_vertical_remote_delivery(uuid, text, text, text, integer, uuid) to service_role;

revoke all on function public.complete_vertical_media_delivery(uuid, text, text, text, integer, uuid, boolean, text, text) from public, anon, authenticated, service_role;
grant execute on function public.complete_vertical_media_delivery(uuid, text, text, text, integer, uuid, boolean, text, text) to service_role;

commit;
