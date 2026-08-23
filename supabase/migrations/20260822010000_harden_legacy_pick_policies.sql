begin;

alter table public.picks enable row level security;

-- PostgreSQL OR-composes permissive policies. An upgrade must therefore remove
-- every policy left by an older installation before installing the audited
-- allowlist; dropping only policies whose current names are known is unsafe.
do $$
declare
    installed_policy record;
begin
    for installed_policy in
        select policyname
        from pg_policies
        where schemaname = 'public'
          and tablename = 'picks'
    loop
        execute format(
            'drop policy %I on public.picks',
            installed_policy.policyname
        );
    end loop;
end;
$$;

revoke all on table public.picks from public;
revoke insert, update, delete, truncate, references, trigger
    on table public.picks from anon;
grant select on table public.picks to anon;
grant select, insert, update, delete on table public.picks to authenticated;
grant all on table public.picks to service_role;

create policy picks_public_read on public.picks
    for select to anon
    using (
        (estado = 'pendiente' and active and visibility = 'public')
        or (estado <> 'pendiente' and visibility = 'public')
    );

create policy picks_member_read on public.picks
    for select to authenticated
    using (
        (
            estado = 'pendiente'
            and active
            and (
                visibility = 'public'
                or public.is_active_subscriber(auth.uid())
            )
        )
        or (estado <> 'pendiente' and visibility = 'public')
    );

create policy picks_admin_select on public.picks
    for select to authenticated
    using (public.is_admin(auth.uid()));

create policy picks_admin_insert on public.picks
    for insert to authenticated
    with check (public.is_admin(auth.uid()));

create policy picks_admin_update on public.picks
    for update to authenticated
    using (public.is_admin(auth.uid()))
    with check (public.is_admin(auth.uid()));

create policy picks_admin_delete on public.picks
    for delete to authenticated
    using (public.is_admin(auth.uid()));

create or replace function public.picks_policy_allowlist_status()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select
        (
            select picks_table.relrowsecurity
            from pg_class as picks_table
            join pg_namespace as picks_schema
              on picks_schema.oid = picks_table.relnamespace
            where picks_schema.nspname = 'public'
              and picks_table.relname = 'picks'
              and picks_table.relkind = 'r'
        )
        and (
            select count(*) = 6
               and count(*) filter (
                    where policyname in (
                        'picks_public_read',
                        'picks_member_read',
                        'picks_admin_select',
                        'picks_admin_insert',
                        'picks_admin_update',
                        'picks_admin_delete'
                    )
                ) = 6
            from pg_policies
            where schemaname = 'public'
              and tablename = 'picks'
        )
        and has_table_privilege(
            'anon', 'public.picks', 'select'
        )
        and not has_table_privilege(
            'anon', 'public.picks', 'insert'
        )
        and not has_table_privilege(
            'anon', 'public.picks', 'update'
        )
        and not has_table_privilege(
            'anon', 'public.picks', 'delete'
        )
        and not has_table_privilege(
            'anon', 'public.picks', 'truncate'
        )
        and not has_table_privilege(
            'anon', 'public.picks', 'references'
        )
        and not has_table_privilege(
            'anon', 'public.picks', 'trigger'
        );
$$;

revoke all on function public.picks_policy_allowlist_status()
    from public, anon, authenticated;
grant execute on function public.picks_policy_allowlist_status()
    to service_role;

commit;
