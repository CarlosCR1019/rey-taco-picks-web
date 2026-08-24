begin;

-- The six-pick migration deliberately wraps the audited one-public-pick RPC.
-- The v2 probe inspects the public wrapper as if it were still the monolithic
-- implementation, so it reports false even though the audited implementation
-- remains installed under its private name. Verify both layers independently
-- instead of weakening the original probe.
create or replace function public.six_pick_publish_schema_status()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select coalesce((
        select
            wrapper.prosecdef
            and wrapper.prorettype = 'jsonb'::regtype
            and wrapper_language.lanname = 'plpgsql'
            and coalesce(wrapper.proconfig, '{}'::text[])
                @> array['search_path=public, pg_temp']
            and legacy.prosecdef
            and legacy.prorettype = 'jsonb'::regtype
            and legacy_language.lanname = 'plpgsql'
            and coalesce(legacy.proconfig, '{}'::text[])
                @> array['search_path=public, pg_temp']

            -- The public wrapper is executable only by its owner and the
            -- service role. The renamed implementation is private even from
            -- service_role so callers cannot bypass the two-public policy.
            and not exists (
                select 1
                from aclexplode(
                    coalesce(
                        wrapper.proacl,
                        acldefault('f', wrapper.proowner)
                    )
                ) as wrapper_acl
                left join pg_roles as wrapper_role
                  on wrapper_role.oid = wrapper_acl.grantee
                where wrapper_acl.privilege_type = 'EXECUTE'
                  and (
                      wrapper_acl.grantee = 0
                      or (
                          wrapper_acl.grantee <> wrapper.proowner
                          and wrapper_role.rolname <> 'service_role'
                      )
                  )
            )
            and exists (
                select 1
                from aclexplode(
                    coalesce(
                        wrapper.proacl,
                        acldefault('f', wrapper.proowner)
                    )
                ) as service_acl
                join pg_roles as service_role
                  on service_role.oid = service_acl.grantee
                where service_acl.privilege_type = 'EXECUTE'
                  and service_role.rolname = 'service_role'
            )
            and not exists (
                select 1
                from pg_roles as executable_role
                where not executable_role.rolsuper
                  and executable_role.oid <> wrapper.proowner
                  and executable_role.rolname <> 'service_role'
                  and has_function_privilege(
                      executable_role.oid,
                      wrapper.oid,
                      'EXECUTE'
                  )
            )
            and not exists (
                select 1
                from pg_roles as legacy_executable_role
                where not legacy_executable_role.rolsuper
                  and legacy_executable_role.oid <> legacy.proowner
                  and has_function_privilege(
                      legacy_executable_role.oid,
                      legacy.oid,
                      'EXECUTE'
                  )
            )

            -- The wrapper accepts at most six audited identities, permits the
            -- second public pick only for a complete six-pick portfolio, and
            -- requires both free picks to come from different physical games.
            and position(
                'jsonb_array_length(requested_picks) not between 1 and 6'
                in wrapper_definition
            ) > 0
            and position(
                'when jsonb_array_length(requested_picks) = 6 then 2'
                in wrapper_definition
            ) > 0
            and position(
                'public_pick_count <> expected_public_count'
                in wrapper_definition
            ) > 0
            and position(
                'public_parlay_count <> 0'
                in wrapper_definition
            ) > 0
            and position(
                'public picks must come from distinct source events'
                in wrapper_definition
            ) > 0
            and position(
                'requested picks must have unique source audit identities'
                in wrapper_definition
            ) > 0
            and position(
                'public.publish_pick_batch_one_public_v2('
                in wrapper_definition
            ) > 0
            and position(
                'persisted_run.source_hash = requested_source_hash'
                in wrapper_definition
            ) > 0
            and position(
                'returned_match_count <> requested_pick_count'
                in wrapper_definition
            ) > 0
            and position(
                'returned_requested_public_count <> expected_public_count'
                in wrapper_definition
            ) > 0
            and position(
                'set visibility = ''public'', razonamiento = null'
                in wrapper_definition
            ) > 0
            and position(
                'source = second_public->>''source'''
                in wrapper_definition
            ) > 0
            and position(
                'source_event_id = second_public->>''source_event_id'''
                in wrapper_definition
            ) > 0
            and position(
                'source_market_key = second_public->>''source_market_key'''
                in wrapper_definition
            ) > 0
            and position(
                'source_selection_key = second_public->>''source_selection_key'''
                in wrapper_definition
            ) > 0
            and position('if updated_rows <> 1' in wrapper_definition) > 0
            and position(
                'jsonb_set(legacy_result, ''{picks}'''
                in wrapper_definition
            ) > 0

            -- The private implementation must retain the complete source
            -- audit, lock, stale-event and redaction guarantees checked by the
            -- original v2 probe.
            and position(
                'pg_advisory_xact_lock'
                in legacy_definition
            ) > 0
            and position(
                'source_observed_at'
                in legacy_definition
            ) > 0
            and position(
                'source_starts_at must be utc, after source_observed_at, and in the future'
                in legacy_definition
            ) > 0
            and position(
                'source_starts_at expired while waiting for publication lock'
                in legacy_definition
            ) > 0
            and position(
                'source_starts_at expired during batch persistence'
                in legacy_definition
            ) > 0
            and position(
                'where persisted_row.batch_id = created_batch and persisted_row.source_starts_at <= clock_timestamp()'
                in legacy_definition
            ) > 0
            and position(
                'persisted_row.source_starts_at <= clock_timestamp()'
                in legacy_definition
            ) > 0
            and position(
                'not resumed_batch.active'
                in legacy_definition
            ) > 0
            and position(
                'scraper run batch is inactive or superseded'
                in legacy_definition
            ) > 0
            and position(
                'visibility = ''public'' then null'
                in legacy_definition
            ) > 0
            and position(
                'insert into public.picks'
                in legacy_definition
            ) > 0

            -- The deferred trigger is the database-level backstop against a
            -- third public pending pick in the same active batch.
            and trigger_function.prosecdef
            and trigger_function.prorettype = 'trigger'::regtype
            and position(
                'pg_advisory_xact_lock(20260820233000)'
                in trigger_definition
            ) > 0
            and position(
                'persisted_row.batch_id = new.batch_id'
                in trigger_definition
            ) > 0
            and position(
                'public_pick_count > 2'
                in trigger_definition
            ) > 0
            and exists (
                select 1
                from pg_trigger as policy_trigger
                where policy_trigger.tgrelid = 'public.picks'::regclass
                  and not policy_trigger.tgisinternal
                  and policy_trigger.tgenabled in ('O', 'A')
                  and policy_trigger.tgname =
                      'picks_at_most_two_public_pending'
                  and policy_trigger.tgfoid = trigger_function.oid
                  and policy_trigger.tgconstraint <> 0
                  and position(
                      'after insert or update'
                      in lower(pg_get_triggerdef(policy_trigger.oid))
                  ) > 0
            )
        from pg_proc as wrapper
        join pg_language as wrapper_language
          on wrapper_language.oid = wrapper.prolang
        cross join pg_proc as legacy
        join pg_language as legacy_language
          on legacy_language.oid = legacy.prolang
        cross join pg_proc as trigger_function
        cross join lateral (
            select regexp_replace(
                lower(pg_get_functiondef(wrapper.oid)),
                '[[:space:]]+',
                ' ',
                'g'
            ) as wrapper_definition
        ) as wrapper_source
        cross join lateral (
            select regexp_replace(
                lower(pg_get_functiondef(legacy.oid)),
                '[[:space:]]+',
                ' ',
                'g'
            ) as legacy_definition
        ) as legacy_source
        cross join lateral (
            select regexp_replace(
                lower(pg_get_functiondef(trigger_function.oid)),
                '[[:space:]]+',
                ' ',
                'g'
            ) as trigger_definition
        ) as trigger_source
        where wrapper.oid = to_regprocedure(
                'public.publish_pick_batch(text,text,jsonb)'
              )
          and legacy.oid = to_regprocedure(
                'public.publish_pick_batch_one_public_v2(text,text,jsonb)'
              )
          and trigger_function.oid = to_regprocedure(
                'public.enforce_two_public_pending_picks()'
              )
    ), false);
$$;

revoke all on function public.six_pick_publish_schema_status()
    from public, anon, authenticated;
grant execute on function public.six_pick_publish_schema_status()
    to service_role;

commit;
