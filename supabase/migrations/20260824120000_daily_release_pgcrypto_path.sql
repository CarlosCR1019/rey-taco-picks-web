begin;

do $guard$
begin
    if to_regprocedure(
        'public.release_daily_pick_portfolio(text,date)'
    ) is null then
        raise exception 'daily portfolio release function is not installed';
    end if;
    if to_regprocedure('extensions.digest(text,text)') is null then
        raise exception 'pgcrypto digest function is not installed';
    end if;
end;
$guard$;

alter function public.release_daily_pick_portfolio(text, date)
    set search_path = pg_catalog, extensions, public, pg_temp;

commit;
