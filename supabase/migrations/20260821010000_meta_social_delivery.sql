begin;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('social-media', 'social-media', true, 5242880, array['image/jpeg'])
on conflict (id) do update
set name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

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
    selected_pick public.picks%rowtype;
    active_batch_count bigint;
    eligible_pick_count bigint;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be blank';
    end if;

    -- Serialize against the publisher so every invariant below is evaluated
    -- from one completed batch lifecycle rather than a transition in progress.
    perform pg_advisory_xact_lock(20260820233000);

    select runs.*
    into selected_run
    from public.scraper_runs as runs
    where runs.run_key = requested_run_key
      and runs.status in ('published', 'partial');

    if not found then
        return null;
    end if;

    select count(*)
    into active_batch_count
    from public.pick_batches as batches
    where batches.run_id = selected_run.id
      and batches.active;

    if active_batch_count <> 1 then
        raise exception 'meta social batch integrity error';
    end if;

    select batches.*
    into selected_batch
    from public.pick_batches as batches
    where batches.run_id = selected_run.id
      and batches.active;

    select count(*)
    into eligible_pick_count
    from public.picks as picks
    where picks.batch_id = selected_batch.id
      and picks.active
      and picks.estado = 'pendiente'
      and picks.visibility = 'public'
      and not coalesce(picks.es_parlay, false);

    if eligible_pick_count <> 1 then
        raise exception 'meta social pick integrity error';
    end if;

    select picks.*
    into selected_pick
    from public.picks as picks
    where picks.batch_id = selected_batch.id
      and picks.active
      and picks.estado = 'pendiente'
      and picks.visibility = 'public'
      and not coalesce(picks.es_parlay, false);

    if selected_pick.source_audit_version is distinct from 1
       or nullif(btrim(selected_pick.source), '') is null
       or length(btrim(selected_pick.source)) not between 1 and 100
       or nullif(btrim(selected_pick.source_event_id), '') is null
       or length(btrim(selected_pick.source_event_id)) not between 1 and 500
       or nullif(btrim(selected_pick.source_market_key), '') is null
       or length(btrim(selected_pick.source_market_key)) not between 1 and 1000
       or nullif(btrim(selected_pick.source_selection_key), '') is null
       or length(btrim(selected_pick.source_selection_key)) not between 1 and 500
       or selected_pick.source_observed_at is null
       or selected_pick.source_starts_at is null
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

create or replace function public.record_meta_social_delivery(
    requested_run_id uuid,
    requested_destination text,
    requested_success boolean,
    requested_receipt text default '',
    requested_error text default ''
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    selected_run public.scraper_runs%rowtype;
    normalized_destination text := lower(btrim(coalesce(requested_destination, '')));
    normalized_receipt text := btrim(coalesce(requested_receipt, ''));
    normalized_error text := btrim(coalesce(requested_error, ''));
    next_delivery_status jsonb;
begin
    if requested_run_id is null then
        raise exception 'requested_run_id must not be null';
    end if;

    if requested_success is null then
        raise exception 'requested_success must not be null';
    end if;

    if normalized_destination not in ('facebook', 'instagram') then
        raise exception 'requested_destination must be facebook or instagram';
    end if;

    if requested_success then
        if normalized_receipt !~ '^[A-Za-z0-9_:-]{1,200}$'
           or normalized_error <> '' then
            raise exception 'successful Meta delivery requires a safe receipt and no error';
        end if;
    elsif normalized_receipt <> ''
       or normalized_error not in ('token_invalid', 'delivery_failed', 'not_configured') then
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

    next_delivery_status := jsonb_set(
        selected_run.delivery_status,
        array[normalized_destination],
        jsonb_build_object(
            'success', requested_success,
            'receipt', normalized_receipt,
            'error', normalized_error,
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

revoke all on function public.get_meta_social_batch(text)
    from public, anon, authenticated;
revoke all on function public.record_meta_social_delivery(uuid, text, boolean, text, text)
    from public, anon, authenticated;

grant execute on function public.get_meta_social_batch(text)
    to service_role;
grant execute on function public.record_meta_social_delivery(uuid, text, boolean, text, text)
    to service_role;

commit;
