begin;

alter table public.picks
    add column if not exists source text,
    add column if not exists source_event_id text,
    add column if not exists source_market_key text,
    add column if not exists source_selection_key text,
    add column if not exists source_observed_at timestamptz,
    add column if not exists source_audit_version smallint;

-- Existing rows predate the audit contract. Keep settled history intact, but
-- fail closed for any unaudited pending row that could still be displayed.
with retired_batches as (
    update public.pick_batches as legacy_batches
    set active = false
    where legacy_batches.active
      and exists (
          select 1
          from public.picks as legacy_picks
          where legacy_picks.batch_id = legacy_batches.id
            and legacy_picks.active
            and (
                nullif(btrim(legacy_picks.source), '') is null
                or nullif(btrim(legacy_picks.source_event_id), '') is null
                or nullif(btrim(legacy_picks.source_market_key), '') is null
                or nullif(btrim(legacy_picks.source_selection_key), '') is null
                or legacy_picks.source_observed_at is null
                or length(btrim(legacy_picks.source)) not between 1 and 100
                or length(btrim(legacy_picks.source_event_id)) not between 1 and 500
                or length(btrim(legacy_picks.source_market_key)) not between 1 and 1000
                or length(btrim(legacy_picks.source_selection_key)) not between 1 and 500
                or legacy_picks.source_observed_at > now()
            )
      )
    returning legacy_batches.id
)
update public.picks as retired_batch_picks
set active = false,
    visibility = case
        when retired_batch_picks.estado = 'pendiente' then 'premium'
        else retired_batch_picks.visibility
    end
where retired_batch_picks.batch_id in (select id from retired_batches);

update public.picks as legacy_picks
set active = false,
    visibility = case
        when legacy_picks.estado = 'pendiente' then 'premium'
        else legacy_picks.visibility
    end
where (
        legacy_picks.active
        or (
            legacy_picks.estado = 'pendiente'
            and legacy_picks.visibility = 'public'
        )
    )
  and (
      nullif(btrim(legacy_picks.source), '') is null
      or nullif(btrim(legacy_picks.source_event_id), '') is null
      or nullif(btrim(legacy_picks.source_market_key), '') is null
      or nullif(btrim(legacy_picks.source_selection_key), '') is null
      or legacy_picks.source_observed_at is null
      or length(btrim(legacy_picks.source)) not between 1 and 100
      or length(btrim(legacy_picks.source_event_id)) not between 1 and 500
      or length(btrim(legacy_picks.source_market_key)) not between 1 and 1000
      or length(btrim(legacy_picks.source_selection_key)) not between 1 and 500
      or legacy_picks.source_observed_at > now()
  );

update public.picks
set razonamiento = null
where visibility = 'public'
  and razonamiento is not null;

alter table public.picks
    alter column source_audit_version set default 1;

create index if not exists picks_source_event_idx
    on public.picks (source, source_event_id);

do $$
begin
    if not exists (
        select 1
        from pg_index as audit_index
        join pg_class as audit_index_class
          on audit_index_class.oid = audit_index.indexrelid
        join pg_namespace as audit_index_schema
          on audit_index_schema.oid = audit_index_class.relnamespace
        where audit_index.indrelid = 'public.picks'::regclass
          and audit_index.indisvalid
          and audit_index.indisready
          and not audit_index.indisunique
          and audit_index_class.relname = 'picks_source_event_idx'
          and audit_index_schema.nspname = 'public'
          and regexp_replace(
              lower(pg_get_indexdef(audit_index.indexrelid)),
              '[[:space:]]+',
              ' ',
              'g'
          ) = 'create index picks_source_event_idx on public.picks using btree (source, source_event_id)'
    ) then
        raise exception 'picks_source_event_idx has unexpected definition';
    end if;
end
$$;

create or replace function public.enforce_pick_source_audit_version()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    if new.visibility = 'public' then
        new.razonamiento := null;
    end if;
    if tg_op = 'INSERT' then
        new.source_audit_version := 1;
    elsif new.estado = 'pendiente' and new.active then
        new.source_audit_version := 1;
    elsif old.source_audit_version = 1 then
        new.source_audit_version := 1;
    elsif new.source_audit_version is distinct from old.source_audit_version
       or new.source is distinct from old.source
       or new.source_event_id is distinct from old.source_event_id
       or new.source_market_key is distinct from old.source_market_key
       or new.source_selection_key is distinct from old.source_selection_key
       or new.source_observed_at is distinct from old.source_observed_at then
        new.source_audit_version := 1;
    end if;
    return new;
end;
$$;

drop trigger if exists picks_enforce_source_audit_version on public.picks;
create trigger picks_enforce_source_audit_version
    before insert or update on public.picks
    for each row execute function public.enforce_pick_source_audit_version();

revoke all on function public.enforce_pick_source_audit_version()
    from public, anon, authenticated;
grant execute on function public.enforce_pick_source_audit_version()
    to service_role;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'picks_source_audit_complete_check'
          and conrelid = 'public.picks'::regclass
    ) then
        -- The trigger keeps the NULL marker exclusive to unchanged historical
        -- rows. Inserts and audit-changing updates are always version 1.
        alter table public.picks
            add constraint picks_source_audit_complete_check
            check (
                source_audit_version is null
                or (
                    source_audit_version = 1
                    and source is not null
                    and source_event_id is not null
                    and source_market_key is not null
                    and source_selection_key is not null
                    and source_observed_at is not null
                    and length(btrim(source)) between 1 and 100
                    and length(btrim(source_event_id)) between 1 and 500
                    and length(btrim(source_market_key)) between 1 and 1000
                    and length(btrim(source_selection_key)) between 1 and 500
                )
            ) not valid;
    end if;
end
$$;

do $$
declare
    definitions_match boolean;
begin
    if exists (
        select 1
        from pg_constraint
        where conrelid = 'public.picks'::regclass
          and conname = 'picks_source_audit_expected_20260820234500_check'
    ) then
        raise exception 'temporary source audit definition constraint already exists';
    end if;

    -- Compare PostgreSQL's parsed expression trees, not formatted SQL text.
    -- This rejects a homonymous constraint with an extra TRUE/NULL bypass.
    alter table public.picks
        add constraint picks_source_audit_expected_20260820234500_check
        check (
            source_audit_version is null
            or (
                source_audit_version = 1
                and source is not null
                and source_event_id is not null
                and source_market_key is not null
                and source_selection_key is not null
                and source_observed_at is not null
                and length(btrim(source)) between 1 and 100
                and length(btrim(source_event_id)) between 1 and 500
                and length(btrim(source_market_key)) between 1 and 1000
                and length(btrim(source_selection_key)) between 1 and 500
            )
        ) not valid;

    select installed_audit_constraint.conbin::text =
           expected_audit_constraint.conbin::text
    into definitions_match
    from pg_constraint as installed_audit_constraint
    join pg_constraint as expected_audit_constraint
      on expected_audit_constraint.conrelid = installed_audit_constraint.conrelid
     and expected_audit_constraint.conname =
         'picks_source_audit_expected_20260820234500_check'
    where installed_audit_constraint.conrelid = 'public.picks'::regclass
      and installed_audit_constraint.contype = 'c'
      and installed_audit_constraint.conname = 'picks_source_audit_complete_check';

    alter table public.picks
        drop constraint picks_source_audit_expected_20260820234500_check;

    if not exists (
        select 1
        from pg_constraint as installed_audit_constraint
        where installed_audit_constraint.conrelid = 'public.picks'::regclass
          and installed_audit_constraint.contype = 'c'
          and installed_audit_constraint.conname = 'picks_source_audit_complete_check'
          and position(
              'source_audit_version is null'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'source_audit_version = 1'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'source is not null'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'source_event_id is not null'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'source_market_key is not null'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'source_selection_key is not null'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'source_observed_at is not null'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'length(btrim(source)) >= 1'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
          and position(
              'length(btrim(source)) <= 100'
              in lower(pg_get_constraintdef(installed_audit_constraint.oid))
          ) > 0
    ) or definitions_match is distinct from true then
        raise exception 'picks_source_audit_complete_check has unexpected definition';
    end if;
end
$$;

-- CREATE OR REPLACE VIEW cannot remove an existing output column during an
-- upgrade, so replace the legacy view transactionally before dropping rationale.
drop view if exists public.public_picks;

create or replace view public.public_picks
with (security_invoker = true)
as
select
    id,
    categoria,
    partido,
    pick,
    cuota,
    confianza,
    fecha_generacion,
    fecha_evento,
    horario,
    tiene_valor,
    es_parlay,
    estado,
    visibility,
    resultado_unidades,
    resultado_fuente,
    resultado_marcador,
    resultado_verificado_at,
    source,
    source_event_id,
    source_market_key,
    source_selection_key,
    source_observed_at
from public.picks
where visibility = 'public';

revoke all on public.public_picks from public, anon, authenticated;
grant select on public.public_picks to anon, authenticated;

alter table public.picks enable row level security;

-- Replace the RPC after the columns exist so upgrades and fresh installations
-- both deserialize and insert the same complete source-audit contract.
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
    claimed_run public.scraper_runs%rowtype;
    created_batch uuid;
    first_pick_id bigint;
    public_pick_count bigint;
    public_parlay_count bigint;
    audit_entry jsonb;
    observed_at_value timestamptz;
begin
    if requested_run_key is null or btrim(requested_run_key) = '' then
        raise exception 'requested_run_key must not be empty';
    end if;

    if requested_source_hash is null or btrim(requested_source_hash) = '' then
        raise exception 'requested_source_hash must not be empty';
    end if;

    if requested_picks is null
       or jsonb_typeof(requested_picks) <> 'array'
       or jsonb_array_length(requested_picks) = 0 then
        raise exception 'requested_picks must be a non-empty array';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where coalesce(value->>'visibility', '') not in ('public', 'premium')
    ) then
        raise exception 'each requested pick must have public or premium visibility';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(requested_picks) as entry(value)
        where jsonb_typeof(value) <> 'object'
           or nullif(btrim(value->>'source'), '') is null
           or nullif(btrim(value->>'source_event_id'), '') is null
           or nullif(btrim(value->>'source_market_key'), '') is null
           or nullif(btrim(value->>'source_selection_key'), '') is null
           or nullif(btrim(value->>'source_observed_at'), '') is null
           or length(btrim(value->>'source')) not between 1 and 100
           or length(btrim(value->>'source_event_id')) not between 1 and 500
           or length(btrim(value->>'source_market_key')) not between 1 and 1000
           or length(btrim(value->>'source_selection_key')) not between 1 and 500
    ) then
        raise exception 'each requested pick must have complete source audit fields';
    end if;

    for audit_entry in
        select value from jsonb_array_elements(requested_picks) as entry(value)
    loop
        if (audit_entry->>'source_observed_at') !~
           '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$' then
            raise exception 'source_observed_at must be UTC and not in the future';
        end if;
        begin
            observed_at_value := (audit_entry->>'source_observed_at')::timestamptz;
        exception
            when invalid_datetime_format or datetime_field_overflow then
                raise exception 'source_observed_at must be UTC and not in the future';
        end;
        if observed_at_value > now() then
            raise exception 'source_observed_at must be UTC and not in the future';
        end if;
    end loop;

    select
        count(*) filter (where value->>'visibility' = 'public'),
        count(*) filter (
            where value->>'visibility' = 'public'
              and coalesce((value->>'es_parlay')::boolean, false)
        )
    into public_pick_count, public_parlay_count
    from jsonb_array_elements(requested_picks) as entry(value);

    if public_pick_count <> 1 or public_parlay_count <> 0 then
        raise exception 'requested_picks must contain exactly one public non-parlay pick';
    end if;

    perform pg_advisory_xact_lock(20260820233000);

    insert into public.scraper_runs (run_key, source_hash)
    values (requested_run_key, requested_source_hash)
    on conflict (run_key) do nothing;

    select *
    into claimed_run
    from public.scraper_runs
    where run_key = requested_run_key
    for update;

    if claimed_run.source_hash <> requested_source_hash then
        raise exception 'run key % already belongs to a different source hash', requested_run_key;
    end if;

    if claimed_run.status in ('published', 'partial') then
        return jsonb_build_object(
            'run_id', claimed_run.id,
            'batch_id', (
                select id
                from public.pick_batches
                where run_id = claimed_run.id
            ),
            'created', false,
            'delivery_status', claimed_run.delivery_status
        );
    end if;

    update public.picks
    set visibility = 'premium'
    where estado = 'pendiente' and visibility = 'public';

    update public.pick_batches set active = false where active;
    update public.picks set active = false where active;

    insert into public.pick_batches (run_id, active)
    values (claimed_run.id, true)
    returning id into created_batch;

    select greatest(
        coalesce(max(id), 0) + 1,
        floor(extract(epoch from clock_timestamp()) * 1000000)::bigint
    )
    into first_pick_id
    from public.picks;

    with requested_rows as (
        select
            jsonb_populate_record(null::public.picks, item.value) as populated,
            item.ordinality
        from jsonb_array_elements(requested_picks)
            with ordinality as item(value, ordinality)
    )
    insert into public.picks (
        id,
        categoria,
        partido,
        pick,
        cuota,
        confianza,
        razonamiento,
        marcador,
        estado,
        es_parlay,
        liga,
        mercado,
        riesgo,
        resultado_apuesta,
        ganancia_simulada,
        fecha_generacion,
        fecha_evento,
        horario,
        odds_mercado,
        tiene_valor,
        visibility,
        source,
        source_event_id,
        source_market_key,
        source_selection_key,
        source_observed_at,
        batch_id,
        active
    )
    select
        first_pick_id + requested_rows.ordinality - 1,
        (requested_rows.populated).categoria,
        (requested_rows.populated).partido,
        (requested_rows.populated).pick,
        (requested_rows.populated).cuota,
        (requested_rows.populated).confianza,
        case
            when (requested_rows.populated).visibility = 'public' then null
            else (requested_rows.populated).razonamiento
        end,
        (requested_rows.populated).marcador,
        'pendiente',
        coalesce((requested_rows.populated).es_parlay, false),
        (requested_rows.populated).liga,
        (requested_rows.populated).mercado,
        (requested_rows.populated).riesgo,
        (requested_rows.populated).resultado_apuesta,
        coalesce((requested_rows.populated).ganancia_simulada, 0),
        (requested_rows.populated).fecha_generacion,
        (requested_rows.populated).fecha_evento,
        (requested_rows.populated).horario,
        (requested_rows.populated).odds_mercado,
        coalesce((requested_rows.populated).tiene_valor, false),
        (requested_rows.populated).visibility,
        (requested_rows.populated).source,
        (requested_rows.populated).source_event_id,
        (requested_rows.populated).source_market_key,
        (requested_rows.populated).source_selection_key,
        (requested_rows.populated).source_observed_at,
        created_batch,
        true
    from requested_rows;

    update public.scraper_runs
    set status = 'published', finished_at = now()
    where id = claimed_run.id;

    return jsonb_build_object(
        'run_id', claimed_run.id,
        'batch_id', created_batch,
        'created', true,
        'delivery_status', claimed_run.delivery_status
    );
end;
$$;

revoke all on function public.publish_pick_batch(text, text, jsonb)
    from public, anon, authenticated;
grant execute on function public.publish_pick_batch(text, text, jsonb)
    to service_role;

create or replace function public.scraper_schema_status()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'version', 2,
        'public_picks',
            exists (
                select 1
                from pg_class as public_view
                join pg_namespace as public_view_schema
                  on public_view_schema.oid = public_view.relnamespace
                where public_view_schema.nspname = 'public'
                  and public_view.relname = 'public_picks'
                  and public_view.relkind = 'v'
                  and coalesce(public_view.reloptions, '{}'::text[])
                      @> array['security_invoker=true']
                  and position(
                      'visibility = ''public'''
                      in lower(pg_get_viewdef(public_view.oid, true))
                  ) > 0
                  and position(
                      ' or '
                      in lower(pg_get_viewdef(public_view.oid, true))
                  ) = 0
                  and position(
                      ' union '
                      in lower(pg_get_viewdef(public_view.oid, true))
                  ) = 0
                  and position(
                      'razonamiento'
                      in lower(pg_get_viewdef(public_view.oid, true))
                  ) = 0
            )
            and has_table_privilege(
                'anon', 'public.public_picks', 'SELECT'
            )
            and has_table_privilege(
                'authenticated', 'public.public_picks', 'SELECT'
            ),
        'publish_pick_batch',
            exists (
                select 1
                from pg_proc as publish_rpc
                join pg_namespace as publish_schema
                  on publish_schema.oid = publish_rpc.pronamespace
                join pg_language as publish_language
                  on publish_language.oid = publish_rpc.prolang
                where publish_rpc.oid = to_regprocedure(
                    'public.publish_pick_batch(text,text,jsonb)'
                )
                  and publish_schema.nspname = 'public'
                  and publish_rpc.prosecdef
                  and publish_rpc.prorettype = 'jsonb'::regtype
                  and publish_language.lanname = 'plpgsql'
                  and coalesce(publish_rpc.proconfig, '{}'::text[])
                      @> array['search_path=public, pg_temp']
                  and not exists (
                      select 1
                      from aclexplode(
                          coalesce(
                              publish_rpc.proacl,
                              acldefault('f', publish_rpc.proowner)
                          )
                      ) as publish_acl
                      left join pg_roles as publish_role
                        on publish_role.oid = publish_acl.grantee
                      where publish_acl.privilege_type = 'EXECUTE'
                        and (
                            publish_acl.grantee = 0
                            or (
                                publish_acl.grantee <> publish_rpc.proowner
                                and publish_role.rolname <> 'service_role'
                            )
                        )
                  )
                  and not exists (
                      select 1
                      from pg_roles as executable_role
                      where not executable_role.rolsuper
                        and executable_role.oid <> publish_rpc.proowner
                        and executable_role.rolname <> 'service_role'
                        and has_function_privilege(
                            executable_role.oid,
                            publish_rpc.oid,
                            'EXECUTE'
                        )
                  )
                  and exists (
                      select 1
                      from aclexplode(
                          coalesce(
                              publish_rpc.proacl,
                              acldefault('f', publish_rpc.proowner)
                          )
                      ) as service_acl
                      join pg_roles as service_role
                        on service_role.oid = service_acl.grantee
                      where service_acl.privilege_type = 'EXECUTE'
                        and service_role.rolname = 'service_role'
                  )
                  and position(
                      'pg_advisory_xact_lock'
                      in lower(pg_get_functiondef(publish_rpc.oid))
                  ) > 0
                  and position(
                      'source_observed_at'
                      in lower(pg_get_functiondef(publish_rpc.oid))
                  ) > 0
                  and position(
                      'visibility = ''public'' then null'
                      in regexp_replace(
                          lower(pg_get_functiondef(publish_rpc.oid)),
                          '[[:space:]]+',
                          ' ',
                          'g'
                      )
                  ) > 0
                  and position(
                      'insert into public.picks'
                      in lower(pg_get_functiondef(publish_rpc.oid))
                  ) > 0
            ),
        'source_audit',
            exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source' and data_type = 'text'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_event_id' and data_type = 'text'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_market_key' and data_type = 'text'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_selection_key' and data_type = 'text'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_observed_at'
                  and data_type = 'timestamp with time zone'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public' and table_name = 'picks'
                  and column_name = 'source_audit_version'
                  and data_type = 'smallint'
            )
            and exists (
                select 1
                from pg_index as audit_index
                join pg_class as audit_index_class
                  on audit_index_class.oid = audit_index.indexrelid
                join pg_namespace as audit_index_schema
                  on audit_index_schema.oid = audit_index_class.relnamespace
                where audit_index.indrelid = 'public.picks'::regclass
                  and audit_index.indisvalid
                  and audit_index.indisready
                  and not audit_index.indisunique
                  and audit_index_class.relname = 'picks_source_event_idx'
                  and audit_index_schema.nspname = 'public'
                  and regexp_replace(
                      lower(pg_get_indexdef(audit_index.indexrelid)),
                      '[[:space:]]+',
                      ' ',
                      'g'
                  ) = 'create index picks_source_event_idx on public.picks using btree (source, source_event_id)'
            )
            and exists (
                select 1
                from pg_trigger as audit_trigger
                where audit_trigger.tgrelid = 'public.picks'::regclass
                  and not audit_trigger.tgisinternal
                  and audit_trigger.tgenabled in ('O', 'A')
                  and audit_trigger.tgname = 'picks_enforce_source_audit_version'
                  and position(
                      'before insert or update'
                      in lower(pg_get_triggerdef(audit_trigger.oid))
                  ) > 0
                  and position(
                      'new.source_audit_version := 1'
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
                  and position(
                      'elsif new.estado = ''pendiente'' and new.active then'
                      in regexp_replace(
                          lower(pg_get_functiondef(audit_trigger.tgfoid)),
                          '[[:space:]]+',
                          ' ',
                          'g'
                      )
                  ) > 0
                  and position(
                      'new.source is distinct from old.source'
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
                  and position(
                      'new.source_event_id is distinct from old.source_event_id'
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
                  and position(
                      'new.source_market_key is distinct from old.source_market_key'
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
                  and position(
                      'new.source_selection_key is distinct from old.source_selection_key'
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
                  and position(
                      'new.source_observed_at is distinct from old.source_observed_at'
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
                  and position(
                      'new.visibility = ''public'''
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
                  and position(
                      'new.razonamiento := null'
                      in lower(pg_get_functiondef(audit_trigger.tgfoid))
                  ) > 0
            )
            and exists (
                select 1
                from pg_constraint as audit_constraint
                where audit_constraint.conrelid = 'public.picks'::regclass
                  and audit_constraint.contype = 'c'
                  and audit_constraint.conname = 'picks_source_audit_complete_check'
                  and position(
                      'source_audit_version is null'
                      in lower(pg_get_constraintdef(audit_constraint.oid))
                  ) > 0
                  and position(
                      'source_audit_version = 1'
                      in lower(pg_get_constraintdef(audit_constraint.oid))
                  ) > 0
                  and position(
                      'source is not null'
                      in lower(pg_get_constraintdef(audit_constraint.oid))
                  ) > 0
                  and position(
                      'source_event_id is not null'
                      in lower(pg_get_constraintdef(audit_constraint.oid))
                  ) > 0
                  and position(
                      'source_market_key is not null'
                      in lower(pg_get_constraintdef(audit_constraint.oid))
                  ) > 0
                  and position(
                      'source_selection_key is not null'
                      in lower(pg_get_constraintdef(audit_constraint.oid))
                  ) > 0
                  and position(
                      'source_observed_at is not null'
                      in lower(pg_get_constraintdef(audit_constraint.oid))
                  ) > 0
            )
            and exists (
                select 1
                from pg_class as picks_table
                join pg_namespace as picks_schema
                  on picks_schema.oid = picks_table.relnamespace
                where picks_schema.nspname = 'public'
                  and picks_table.relname = 'picks'
                  and picks_table.relkind = 'r'
                  and picks_table.relrowsecurity
            )
            and exists (
                select 1
                from pg_policies
                where schemaname = 'public'
                  and tablename = 'picks'
                  and policyname = 'picks_public_read'
                  and cmd = 'SELECT'
                  and 'anon' = any(roles)
                  and position('active' in lower(qual)) > 0
                  and position('visibility' in lower(qual)) > 0
            )
            and exists (
                select 1
                from pg_policies
                where schemaname = 'public'
                  and tablename = 'picks'
                  and policyname = 'picks_member_read'
                  and cmd = 'SELECT'
                  and 'authenticated' = any(roles)
                  and position('active' in lower(qual)) > 0
                  and position('is_active_subscriber' in lower(qual)) > 0
            )
            and exists (
                select 1
                from pg_policies
                where schemaname = 'public'
                  and tablename = 'picks'
                  and policyname = 'picks_admin_select'
                  and cmd = 'SELECT'
                  and 'authenticated' = any(roles)
                  and position('is_admin' in lower(qual)) > 0
            )
            and exists (
                select 1
                from pg_policies
                where schemaname = 'public'
                  and tablename = 'picks'
                  and policyname = 'picks_admin_insert'
                  and cmd = 'INSERT'
                  and 'authenticated' = any(roles)
                  and position('is_admin' in lower(with_check)) > 0
            )
            and exists (
                select 1
                from pg_policies
                where schemaname = 'public'
                  and tablename = 'picks'
                  and policyname = 'picks_admin_update'
                  and cmd = 'UPDATE'
                  and 'authenticated' = any(roles)
                  and position('is_admin' in lower(qual)) > 0
                  and position('is_admin' in lower(with_check)) > 0
            )
            and exists (
                select 1
                from pg_policies
                where schemaname = 'public'
                  and tablename = 'picks'
                  and policyname = 'picks_admin_delete'
                  and cmd = 'DELETE'
                  and 'authenticated' = any(roles)
                  and position('is_admin' in lower(qual)) > 0
            )
            and (
                select count(*)
                from pg_class as ledger_table
                join pg_namespace as ledger_schema
                  on ledger_schema.oid = ledger_table.relnamespace
                where ledger_schema.nspname = 'public'
                  and ledger_table.relname in (
                      'scraper_runs', 'pick_batches'
                  )
                  and ledger_table.relkind = 'r'
                  and ledger_table.relrowsecurity
            ) = 2
            and not has_table_privilege(
                'anon', 'public.scraper_runs', 'SELECT'
            )
            and not has_table_privilege(
                'authenticated', 'public.scraper_runs', 'SELECT'
            )
            and not has_table_privilege(
                'anon', 'public.pick_batches', 'SELECT'
            )
            and not has_table_privilege(
                'authenticated', 'public.pick_batches', 'SELECT'
            )
    );
$$;

revoke all on function public.scraper_schema_status()
    from public, anon, authenticated;
grant execute on function public.scraper_schema_status()
    to service_role;

commit;
