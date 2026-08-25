begin;

-- Keep the deployed round-aware implementation intact and add one final
-- persistence boundary.  Incremental revisions can reuse a batch whose
-- historical public allocation differs from the active portfolio entries;
-- callers must receive the allocation that is actually authoritative today.
alter function public.release_daily_pick_portfolio(text, date)
    rename to release_daily_pick_portfolio_visibility_unsynced_v1;

revoke all on function public.release_daily_pick_portfolio_visibility_unsynced_v1(text, date)
    from public, anon, authenticated, service_role;

create or replace function public.release_daily_pick_portfolio(
    requested_run_key text,
    requested_portfolio_date date
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, extensions, public, pg_temp
as $$
declare
    legacy_result jsonb;
    synchronized_result jsonb;
    released_batch_id uuid;
    active_entry_count integer;
    active_batch_pick_count integer;
    synchronized_pick_count integer;
begin
    legacy_result := public.release_daily_pick_portfolio_visibility_unsynced_v1(
        requested_run_key,
        requested_portfolio_date
    );
    if legacy_result is null then
        return null;
    end if;

    released_batch_id := (legacy_result->>'batch_id')::uuid;

    select count(*)
    into active_entry_count
    from public.daily_pick_entries as entries
    where entries.portfolio_date = requested_portfolio_date
      and entries.active;

    select count(*)
    into active_batch_pick_count
    from public.picks as persisted
    where persisted.batch_id = released_batch_id
      and persisted.active;

    if active_entry_count not between 1 and 6
       or active_batch_pick_count <> active_entry_count then
        raise exception 'daily release visibility sync found an incomplete active batch';
    end if;

    update public.picks as persisted
    set visibility = entries.visibility,
        razonamiento = case
            when entries.visibility = 'public' then null
            else persisted.razonamiento
        end
    from public.daily_pick_entries as entries
    where persisted.id = entries.pick_id
      and persisted.batch_id = released_batch_id
      and persisted.active
      and entries.portfolio_date = requested_portfolio_date
      and entries.active;

    get diagnostics synchronized_pick_count = row_count;
    if synchronized_pick_count <> active_entry_count then
        raise exception 'daily release visibility sync could not map every active entry';
    end if;

    -- Re-read instead of patching the already-built JSON.  This makes create
    -- and replay return the same persisted rows after visibility is repaired.
    synchronized_result := public.resume_daily_pick_release(requested_run_key);
    if synchronized_result is null then
        raise exception 'daily release visibility sync could not resume release';
    end if;
    if synchronized_result->'feed_eligible'
       is distinct from legacy_result->'feed_eligible' then
        raise exception 'daily release visibility sync changed feed eligibility';
    end if;

    return jsonb_set(
        synchronized_result,
        '{created}',
        legacy_result->'created',
        true
    );
end;
$$;

revoke all on function public.release_daily_pick_portfolio(text, date)
    from public, anon, authenticated;
grant execute on function public.release_daily_pick_portfolio(text, date)
    to service_role;

commit;
