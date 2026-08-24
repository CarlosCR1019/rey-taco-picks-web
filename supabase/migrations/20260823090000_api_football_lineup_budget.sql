begin;

create table if not exists public.api_football_request_budget (
  quota_day date primary key,
  requests_used integer not null default 0
    check (requests_used between 0 and 40),
  updated_at timestamptz not null default now()
);

create table if not exists public.api_football_cache (
  cache_key text primary key check (length(btrim(cache_key)) between 1 and 200),
  payload jsonb not null,
  expires_at timestamptz not null,
  updated_at timestamptz not null default now()
);

alter table public.api_football_request_budget enable row level security;
alter table public.api_football_cache enable row level security;

revoke all on table public.api_football_request_budget
  from public, anon, authenticated;
revoke all on table public.api_football_cache
  from public, anon, authenticated;
grant all on table public.api_football_request_budget to service_role;
grant all on table public.api_football_cache to service_role;

create or replace function public.claim_api_football_request(
  requested_quota_day date,
  requested_limit integer default 40
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  current_count integer;
  effective_limit integer;
  server_quota_day date;
begin
  if requested_quota_day is null then
    raise exception 'quota day is required';
  end if;
  server_quota_day := (now() at time zone 'utc')::date;
  if requested_quota_day <> server_quota_day then
    return false;
  end if;
  effective_limit := least(requested_limit, 40);
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
  )
  on conflict (quota_day) do nothing;

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

create or replace function public.get_api_football_cache(
  requested_cache_key text
)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
  select payload
  from public.api_football_cache
  where cache_key = btrim(requested_cache_key)
    and expires_at > now();
$$;

create or replace function public.put_api_football_cache(
  requested_cache_key text,
  requested_payload jsonb,
  requested_expires_at timestamptz
)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if length(btrim(coalesce(requested_cache_key, ''))) not between 1 and 200 then
    raise exception 'invalid cache key';
  end if;
  if requested_payload is null or requested_expires_at <= now() then
    raise exception 'invalid cache value';
  end if;

  insert into public.api_football_cache (
    cache_key,
    payload,
    expires_at,
    updated_at
  ) values (
    btrim(requested_cache_key),
    requested_payload,
    requested_expires_at,
    now()
  )
  on conflict (cache_key) do update
  set payload = excluded.payload,
      expires_at = excluded.expires_at,
      updated_at = now();
end;
$$;

revoke all on function public.claim_api_football_request(date, integer)
  from public, anon, authenticated;
revoke all on function public.get_api_football_cache(text)
  from public, anon, authenticated;
revoke all on function public.put_api_football_cache(text, jsonb, timestamptz)
  from public, anon, authenticated;
grant execute on function public.claim_api_football_request(date, integer)
  to service_role;
grant execute on function public.get_api_football_cache(text)
  to service_role;
grant execute on function public.put_api_football_cache(text, jsonb, timestamptz)
  to service_role;

commit;
