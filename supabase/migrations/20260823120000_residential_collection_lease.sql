begin;

create table public.residential_collection_leases (
    window_key text primary key check (
        length(btrim(window_key)) between 1 and 200
    ),
    owner_run_key text not null check (
        length(btrim(owner_run_key)) between 1 and 200
    ),
    lease_expires_at timestamptz not null,
    acquired_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.residential_collection_leases enable row level security;
revoke all on table public.residential_collection_leases
    from public, anon, authenticated;
revoke all on table public.residential_collection_leases from service_role;

create or replace function public.claim_residential_collection_lease(
    requested_window_key text,
    requested_owner_run_key text,
    requested_lease_minutes integer
) returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    checked_at timestamptz;
    requested_expiration timestamptz;
    existing_lease public.residential_collection_leases%rowtype;
begin
    if requested_window_key is null
       or length(btrim(requested_window_key)) not between 1 and 200
       or requested_window_key !~ '^[A-Za-z0-9*|: _-]+$' then
        raise exception 'requested_window_key is invalid';
    end if;
    if requested_owner_run_key is null
       or length(btrim(requested_owner_run_key)) not between 1 and 200
       or requested_owner_run_key !~ '^[A-Za-z0-9|:._ -]+$' then
        raise exception 'requested_owner_run_key is invalid';
    end if;
    if requested_lease_minutes is null
       or requested_lease_minutes not between 5 and 60 then
        raise exception 'requested lease duration is invalid';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended(
            'rey-taco-residential:' || btrim(requested_window_key), 0
        )
    );
    checked_at := clock_timestamp();
    requested_expiration := checked_at
        + make_interval(mins => requested_lease_minutes);

    select leases.*
    into existing_lease
    from public.residential_collection_leases as leases
    where leases.window_key = btrim(requested_window_key)
    for update;

    if found then
        if existing_lease.owner_run_key = btrim(requested_owner_run_key)
           or existing_lease.lease_expires_at <= checked_at then
            null;
        else
            return false;
        end if;
    end if;

    insert into public.residential_collection_leases (
        window_key,
        owner_run_key,
        lease_expires_at,
        acquired_at,
        updated_at
    ) values (
        btrim(requested_window_key),
        btrim(requested_owner_run_key),
        requested_expiration,
        checked_at,
        checked_at
    )
    on conflict (window_key) do update
    set owner_run_key = excluded.owner_run_key,
        lease_expires_at = excluded.lease_expires_at,
        acquired_at = case
            when public.residential_collection_leases.owner_run_key =
                    excluded.owner_run_key
                then public.residential_collection_leases.acquired_at
            else excluded.acquired_at
        end,
        updated_at = excluded.updated_at;

    return true;
end;
$$;

create or replace function public.release_residential_collection_lease(
    requested_window_key text,
    requested_owner_run_key text
) returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if requested_window_key is null
       or length(btrim(requested_window_key)) not between 1 and 200
       or requested_owner_run_key is null
       or length(btrim(requested_owner_run_key)) not between 1 and 200 then
        raise exception 'requested lease identity is invalid';
    end if;
    perform pg_advisory_xact_lock(
        hashtextextended(
            'rey-taco-residential:' || btrim(requested_window_key), 0
        )
    );
    delete from public.residential_collection_leases as leases
    where leases.window_key = btrim(requested_window_key)
      and leases.owner_run_key = btrim(requested_owner_run_key);
    return found;
end;
$$;

revoke all on function public.claim_residential_collection_lease(text, text, integer)
    from public, anon, authenticated;
grant execute on function public.claim_residential_collection_lease(text, text, integer)
    to service_role;
revoke all on function public.release_residential_collection_lease(text, text)
    from public, anon, authenticated;
grant execute on function public.release_residential_collection_lease(text, text)
    to service_role;

commit;
