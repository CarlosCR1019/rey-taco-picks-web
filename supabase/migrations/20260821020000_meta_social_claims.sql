begin;

drop function if exists public.record_meta_social_delivery(uuid, text, boolean, text, text);

create or replace function public.claim_meta_social_destination(
    requested_run_id uuid,
    requested_destination text,
    requested_attempt_id uuid,
    requested_lease_expires_at timestamptz
) returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    selected_run public.scraper_runs%rowtype;
    destination_entry jsonb;
    next_delivery_status jsonb;
    checked_at timestamptz := clock_timestamp();
begin
    if requested_run_id is null then
        raise exception 'requested_run_id must not be null';
    end if;

    if requested_attempt_id is null then
        raise exception 'requested_attempt_id must not be null';
    end if;

    if requested_destination is null
       or requested_destination not in ('facebook', 'instagram') then
        raise exception 'requested_destination must be facebook or instagram';
    end if;

    if requested_lease_expires_at is null
       or requested_lease_expires_at <= checked_at
       or requested_lease_expires_at > checked_at + interval '10 minutes' then
        raise exception 'requested_lease_expires_at must be future and at most ten minutes';
    end if;

    select runs.*
    into selected_run
    from public.scraper_runs as runs
    where runs.id = requested_run_id
      and runs.status in ('published', 'partial')
    for update;

    if not found then
        raise exception 'unknown or unpublished scraper run %', requested_run_id;
    end if;

    destination_entry := coalesce(
        selected_run.delivery_status->requested_destination,
        '{}'::jsonb
    );

    if destination_entry->>'success' = 'true' then
        return false;
    end if;

    if destination_entry->>'state' = 'in_progress'
       and destination_entry->>'lease_expires_at' is not null
       and (destination_entry->>'lease_expires_at')::timestamptz > checked_at then
        return false;
    end if;

    next_delivery_status := jsonb_set(
        selected_run.delivery_status,
        array[requested_destination],
        jsonb_build_object(
            'state', 'in_progress',
            'success', false,
            'receipt', '',
            'error', '',
            'attempt_id', requested_attempt_id::text,
            'lease_expires_at', requested_lease_expires_at,
            'updated_at', now()
        ),
        true
    );

    update public.scraper_runs as runs
    set delivery_status = next_delivery_status,
        status = 'partial'
    where runs.id = selected_run.id
      and runs.status in ('published', 'partial');

    return true;
end;
$$;

create or replace function public.record_meta_social_delivery(
    requested_run_id uuid,
    requested_destination text,
    requested_success boolean,
    requested_receipt text,
    requested_error text,
    requested_attempt_id uuid
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    selected_run public.scraper_runs%rowtype;
    destination_entry jsonb;
    next_delivery_status jsonb;
begin
    if requested_run_id is null then
        raise exception 'requested_run_id must not be null';
    end if;

    if requested_attempt_id is null then
        raise exception 'requested_attempt_id must not be null';
    end if;

    if requested_success is null then
        raise exception 'requested_success must not be null';
    end if;

    if requested_destination is null
       or requested_destination not in ('facebook', 'instagram') then
        raise exception 'requested_destination must be facebook or instagram';
    end if;

    if requested_receipt is null then
        raise exception 'requested_receipt must not be null';
    end if;

    if requested_error is null then
        raise exception 'requested_error must not be null';
    end if;

    if requested_success then
        if requested_receipt !~ '^[A-Za-z0-9_:-]{1,200}$'
           or requested_error <> '' then
            raise exception 'successful Meta delivery requires a safe receipt and no error';
        end if;
    elsif requested_receipt <> ''
       or requested_error not in ('token_invalid', 'delivery_failed', 'not_configured') then
        raise exception 'failed Meta delivery requires an allowed error and no receipt';
    end if;

    select runs.*
    into selected_run
    from public.scraper_runs as runs
    where runs.id = requested_run_id
      and runs.status in ('published', 'partial')
    for update;

    if not found then
        raise exception 'unknown or unpublished scraper run %', requested_run_id;
    end if;

    destination_entry := coalesce(
        selected_run.delivery_status->requested_destination,
        '{}'::jsonb
    );

    -- A successful receipt is terminal and cannot be replaced by a stale worker.
    if destination_entry->>'success' = 'true' then
        return;
    end if;

    if destination_entry->>'state' is distinct from 'in_progress'
       or destination_entry->>'attempt_id'
            is distinct from requested_attempt_id::text then
        raise exception 'meta social claim ownership error';
    end if;

    next_delivery_status := jsonb_set(
        selected_run.delivery_status,
        array[requested_destination],
        jsonb_build_object(
            'state', case when requested_success then 'success' else 'failed' end,
            'success', requested_success,
            'receipt', requested_receipt,
            'error', requested_error,
            'attempt_id', requested_attempt_id::text,
            'updated_at', now()
        ),
        true
    );

    update public.scraper_runs as runs
    set delivery_status = next_delivery_status,
        status = case
            when not exists (
                select 1
                from jsonb_each(next_delivery_status)
                    as delivery(destination, details)
                where details->>'success' is distinct from 'true'
            ) then 'published' else 'partial'
        end
    where runs.id = selected_run.id
      and runs.status in ('published', 'partial');
end;
$$;

comment on function public.claim_meta_social_destination(uuid, text, uuid, timestamptz)
is 'Leases serialize active Meta delivery attempts but do not provide exactly-once delivery.';

comment on function public.record_meta_social_delivery(uuid, text, boolean, text, text, uuid)
is 'A crash after a request is accepted by Meta but before the receipt is persisted leaves an unavoidable ambiguity; a later retry can create a duplicate.';

revoke all on function public.claim_meta_social_destination(uuid, text, uuid, timestamptz)
    from public, anon, authenticated;
revoke all on function public.record_meta_social_delivery(uuid, text, boolean, text, text, uuid)
    from public, anon, authenticated;

grant execute on function public.claim_meta_social_destination(uuid, text, uuid, timestamptz)
    to service_role;
grant execute on function public.record_meta_social_delivery(uuid, text, boolean, text, text, uuid)
    to service_role;

commit;
