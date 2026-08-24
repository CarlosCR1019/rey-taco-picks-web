begin;

alter table public.api_football_request_budget
    drop constraint if exists api_football_request_budget_requests_used_check;
alter table public.api_football_request_budget
    add constraint api_football_request_budget_requests_used_check
    check (requests_used between 0 and 80);

create or replace function public.claim_api_football_request(
    requested_quota_day date,
    requested_limit integer default 80
) returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    current_count integer;
    effective_limit integer;
    server_quota_day date;
begin
    if requested_quota_day is null or requested_limit is null then
        raise exception 'quota day and request limit are required';
    end if;
    server_quota_day := (now() at time zone 'utc')::date;
    if requested_quota_day <> server_quota_day then
        return false;
    end if;
    effective_limit := least(requested_limit, 80);
    if effective_limit < 1 then
        raise exception 'request limit must be positive';
    end if;

    insert into public.api_football_request_budget (
        quota_day,
        requests_used,
        updated_at
    ) values (
        server_quota_day,
        0,
        now()
    ) on conflict (quota_day) do nothing;

    select requests_used
    into current_count
    from public.api_football_request_budget
    where quota_day = server_quota_day
    for update;

    if current_count >= effective_limit then
        return false;
    end if;

    update public.api_football_request_budget
    set requests_used = requests_used + 1,
        updated_at = now()
    where quota_day = server_quota_day;
    return true;
end;
$$;

revoke all on function public.claim_api_football_request(date, integer)
    from public, anon, authenticated;
grant execute on function public.claim_api_football_request(date, integer)
    to service_role;

commit;
