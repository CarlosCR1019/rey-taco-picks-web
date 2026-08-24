begin;

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
    if requested_destination not in (
        'admin', 'vip', 'free', 'facebook', 'instagram'
    ) then
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
           or char_length(requested_receipt) not between 1 and 256
           or requested_receipt !~ '^[A-Za-z0-9_:-]+$' then
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

revoke all on function public.complete_result_report_delivery(uuid, text, text, text, uuid, boolean, text, text)
    from public, anon, authenticated;
grant execute on function public.complete_result_report_delivery(uuid, text, text, text, uuid, boolean, text, text)
    to service_role;

commit;
