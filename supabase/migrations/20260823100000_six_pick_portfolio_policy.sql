begin;

-- The original invariant allowed one global public pending pick. The current
-- batch contract allows two only when the complete portfolio contains six.
drop index if exists public.picks_one_public_pending_idx;

create or replace function public.enforce_two_public_pending_picks()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    public_pick_count bigint;
begin
    if new.visibility <> 'public'
       or new.estado <> 'pendiente'
       or new.active is not true
       or new.batch_id is null then
        return new;
    end if;

    -- Serialize direct table mutations with publish_pick_batch so concurrent
    -- writers cannot both observe one free pick and create a third.
    perform pg_advisory_xact_lock(20260820233000);

    select count(*)
    into public_pick_count
    from public.picks as persisted_row
    where persisted_row.visibility = 'public'
      and persisted_row.estado = 'pendiente'
      and persisted_row.active is true
      and persisted_row.batch_id = new.batch_id;

    if public_pick_count > 2 then
        raise exception 'at most two public pending picks are allowed';
    end if;
    return new;
end;
$$;

revoke all on function public.enforce_two_public_pending_picks() from public;

drop trigger if exists picks_at_most_two_public_pending on public.picks;
create constraint trigger picks_at_most_two_public_pending
after insert or update on public.picks
deferrable initially immediate
for each row
execute function public.enforce_two_public_pending_picks();

-- Preserve the fully audited implementation from the latest deployed
-- migration. The wrapper below validates the new portfolio contract, adapts
-- the second free pick for the historical implementation, then promotes it in
-- the same locked transaction.
alter function public.publish_pick_batch(text, text, jsonb)
    rename to publish_pick_batch_one_public_v2;

revoke all on function public.publish_pick_batch_one_public_v2(text, text, jsonb)
    from public, anon, authenticated, service_role;

create or replace function public.publish_pick_batch(
    requested_run_key text,
    requested_source_hash text,
    requested_picks jsonb
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    requested_pick_count integer;
    expected_public_count integer;
    public_pick_count bigint;
    public_parlay_count bigint;
    public_event_count bigint;
    distinct_audit_count bigint;
    legacy_picks jsonb;
    legacy_result jsonb;
    second_public jsonb;
    rewritten_picks jsonb;
    updated_rows bigint;
    returned_pick_count bigint;
    returned_match_count bigint;
    returned_public_count bigint;
    returned_requested_public_count bigint;
begin
    if requested_picks is null or jsonb_typeof(requested_picks) <> 'array' then
        raise exception 'requested_picks must be an array of one to six picks';
    end if;

    requested_pick_count := jsonb_array_length(requested_picks);
    if jsonb_array_length(requested_picks) not between 1 and 6 then
        raise exception 'requested_picks must contain between one and six picks';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where jsonb_typeof(value) <> 'object'
           or coalesce(value->>'visibility', '') not in ('public', 'premium')
    ) then
        raise exception 'each requested pick must have public or premium visibility';
    end if;

    expected_public_count := case
        when jsonb_array_length(requested_picks) = 6 then 2
        else 1
    end;

    select
        count(*) filter (where value->>'visibility' = 'public'),
        count(*) filter (
            where value->>'visibility' = 'public'
              and coalesce(value->>'es_parlay', 'false') <> 'false'
        ),
        count(distinct jsonb_build_array(
            value->>'source',
            value->>'source_event_id'
        )) filter (where value->>'visibility' = 'public'),
        count(distinct jsonb_build_array(
            value->>'source',
            value->>'source_event_id',
            value->>'source_market_key',
            value->>'source_selection_key'
        ))
    into
        public_pick_count,
        public_parlay_count,
        public_event_count,
        distinct_audit_count
    from jsonb_array_elements(requested_picks) as entry(value);

    if public_pick_count <> expected_public_count or public_parlay_count <> 0 then
        raise exception 'requested_picks contain an invalid public pick policy';
    end if;
    if public_event_count <> public_pick_count then
        raise exception 'public picks must come from distinct source events';
    end if;
    if distinct_audit_count <> requested_pick_count then
        raise exception 'requested picks must have unique source audit identities';
    end if;

    with ordered_rows as (
        select
            entry.value,
            entry.ordinality,
            count(*) filter (
                where entry.value->>'visibility' = 'public'
            ) over (
                order by entry.ordinality
                rows between unbounded preceding and current row
            ) as public_position
        from jsonb_array_elements(requested_picks)
            with ordinality as entry(value, ordinality)
    )
    select jsonb_agg(
        case
            when value->>'visibility' = 'public' and public_position > 1
                then jsonb_set(
                    value,
                    '{visibility}',
                    to_jsonb('premium'::text),
                    false
                )
            else value
        end
        order by ordinality
    )
    into legacy_picks
    from ordered_rows;

    if expected_public_count = 2 then
        select entry.value
        into second_public
        from jsonb_array_elements(requested_picks)
            with ordinality as entry(value, ordinality)
        where entry.value->>'visibility' = 'public'
        order by entry.ordinality
        offset 1 limit 1;
    end if;

    legacy_result := public.publish_pick_batch_one_public_v2(
        requested_run_key,
        requested_source_hash,
        legacy_picks
    );

    if not exists (
        select 1
        from public.scraper_runs as persisted_run
        where persisted_run.id = (legacy_result->>'run_id')::uuid
          and persisted_run.run_key = requested_run_key
          and persisted_run.source_hash = requested_source_hash
    ) then
        raise exception 'persisted run source hash does not match request';
    end if;

    select
        count(*),
        count(*) filter (where persisted.value->>'visibility' = 'public'),
        count(*) filter (
            where persisted.value->>'visibility' = 'public'
              and exists (
                  select 1
                  from jsonb_array_elements(requested_picks) as requested(value)
                  where requested.value->>'visibility' = 'public'
                    and requested.value->>'source' = persisted.value->>'source'
                    and requested.value->>'source_event_id' = persisted.value->>'source_event_id'
                    and requested.value->>'source_market_key' = persisted.value->>'source_market_key'
                    and requested.value->>'source_selection_key' = persisted.value->>'source_selection_key'
              )
        )
    into
        returned_pick_count,
        returned_public_count,
        returned_requested_public_count
    from jsonb_array_elements(legacy_result->'picks') as persisted(value);

    select count(*)
    into returned_match_count
    from jsonb_array_elements(legacy_result->'picks') as persisted(value)
    where exists (
        select 1
        from jsonb_array_elements(requested_picks) as requested(value)
        where requested.value->>'source' = persisted.value->>'source'
          and requested.value->>'source_event_id' = persisted.value->>'source_event_id'
          and requested.value->>'source_market_key' = persisted.value->>'source_market_key'
          and requested.value->>'source_selection_key' = persisted.value->>'source_selection_key'
    );

    if returned_pick_count <> requested_pick_count
       or returned_match_count <> requested_pick_count then
        raise exception 'persisted batch does not match the requested source identities';
    end if;

    if legacy_result->>'created' = 'false' then
        if returned_public_count <> expected_public_count
           or returned_requested_public_count <> expected_public_count then
            raise exception 'persisted batch does not match the requested public policy';
        end if;
        return legacy_result;
    end if;

    if expected_public_count = 1 then
        if returned_public_count <> 1 or returned_requested_public_count <> 1 then
            raise exception 'created batch does not match the requested public policy';
        end if;
        return legacy_result;
    end if;

    if returned_public_count <> 1 or returned_requested_public_count <> 1 then
        raise exception 'legacy batch adaptation did not preserve the first public pick';
    end if;

    update public.picks
    set visibility = 'public', razonamiento = null
    where batch_id = (legacy_result->>'batch_id')::uuid
      and source = second_public->>'source'
      and source_event_id = second_public->>'source_event_id'
      and source_market_key = second_public->>'source_market_key'
      and source_selection_key = second_public->>'source_selection_key';

    get diagnostics updated_rows = row_count;
    if updated_rows <> 1 then
        raise exception 'second public pick could not be identified exactly';
    end if;

    select jsonb_agg(
        case
            when entry.value->>'source' = second_public->>'source'
             and entry.value->>'source_event_id' = second_public->>'source_event_id'
             and entry.value->>'source_market_key' = second_public->>'source_market_key'
             and entry.value->>'source_selection_key' = second_public->>'source_selection_key'
                then jsonb_set(
                    jsonb_set(
                        entry.value,
                        '{visibility}',
                        to_jsonb('public'::text),
                        false
                    ),
                    '{razonamiento}',
                    'null'::jsonb,
                    true
                )
            else entry.value
        end
        order by entry.ordinality
    )
    into rewritten_picks
    from jsonb_array_elements(legacy_result->'picks')
        with ordinality as entry(value, ordinality);

    return jsonb_set(legacy_result, '{picks}', rewritten_picks, false);
end;
$$;

revoke all on function public.publish_pick_batch(text, text, jsonb)
    from public, anon, authenticated;
grant execute on function public.publish_pick_batch(text, text, jsonb)
    to service_role;

commit;
