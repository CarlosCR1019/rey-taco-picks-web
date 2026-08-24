from pathlib import Path
import re
import unittest


SQL = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260820220000_secure_membership.sql"
)
RUN_LEDGER_SQL = SQL.parent / "20260820233000_scraper_run_ledger.sql"
SOURCE_AUDIT_SQL = SQL.parent / "20260820234500_pick_source_audit.sql"
META_SOCIAL_SQL = SQL.parent / "20260821010000_meta_social_delivery.sql"
META_SOCIAL_CLAIMS_SQL = SQL.parent / "20260821020000_meta_social_claims.sql"
BASE_SCHEMA_SQL = SQL.parent / "20260820210000_base_profiles_picks.sql"
LEGACY_POLICY_HARDENING_SQL = (
    SQL.parent / "20260822010000_harden_legacy_pick_policies.sql"
)
LINEUP_BUDGET_SQL = (
    SQL.parent / "20260823090000_api_football_lineup_budget.sql"
)
SIX_PICK_PORTFOLIO_SQL = (
    SQL.parent / "20260823100000_six_pick_portfolio_policy.sql"
)
DAILY_PORTFOLIO_SQL = (
    SQL.parent / "20260823110000_daily_pick_portfolio_revisions.sql"
)


def function_body(path: Path, signature: str) -> str:
    text = " ".join(path.read_text(encoding="utf-8").lower().split())
    start = text.index(f"create or replace function {signature}")
    body_start = text.index("as $$", start) + len("as $$")
    body_end = text.index("$$;", body_start)
    return text[body_start:body_end].strip()


def sql_call_arguments(text: str, call: str, start: int = 0) -> tuple[list[str], int]:
    call_start = text.index(call, start)
    opening = text.index("(", call_start + len(call))
    arguments: list[str] = []
    argument_start = opening + 1
    depth = 1
    quoted = False
    index = opening + 1

    while index < len(text):
        character = text[index]
        if quoted:
            if character == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                quoted = False
        elif character == "'":
            quoted = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                arguments.append(text[argument_start:index].strip())
                return arguments, index + 1
        elif character == "," and depth == 1:
            arguments.append(text[argument_start:index].strip())
            argument_start = index + 1
        index += 1

    raise ValueError(f"unterminated SQL call: {call}")


def function_signature_pattern(signature: str) -> str:
    function_name, parameter_list = signature.rstrip(")").split("(", 1)
    parameter_patterns = []
    for parameter in parameter_list.split(","):
        words = parameter.strip().split()
        parameter_patterns.append(r"\s+".join(re.escape(word) for word in words))
    return (
        rf"{re.escape(function_name)}\s*\(\s*"
        + r"\s*,\s*".join(parameter_patterns)
        + r"\s*\)"
    )


class SupabaseContractTests(unittest.TestCase):
    def test_six_pick_portfolio_migration_replaces_exact_one_policy_safely(self):
        self.assertTrue(SIX_PICK_PORTFOLIO_SQL.exists())
        text = " ".join(
            SIX_PICK_PORTFOLIO_SQL.read_text(encoding="utf-8")
            .lower()
            .split()
        )
        signature = (
            "public.publish_pick_batch( requested_run_key text, "
            "requested_source_hash text, requested_picks jsonb ) returns jsonb"
        )
        body = function_body(SIX_PICK_PORTFOLIO_SQL, signature)

        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))
        self.assertIn(
            "drop index if exists public.picks_one_public_pending_idx", text
        )
        self.assertIn(
            "alter function public.publish_pick_batch(text, text, jsonb) "
            "rename to publish_pick_batch_one_public_v2",
            text,
        )
        self.assertIn("jsonb_array_length(requested_picks) not between 1 and 6", body)
        self.assertIn(
            "case when jsonb_array_length(requested_picks) = 6 then 2 else 1 end",
            body,
        )
        self.assertIn("public_pick_count <> expected_public_count", body)
        self.assertIn("public_parlay_count <> 0", body)
        self.assertIn("count(distinct jsonb_build_array", body)
        self.assertIn("public.publish_pick_batch_one_public_v2(", body)
        self.assertIn("returned_match_count <> requested_pick_count", body)
        self.assertIn("persisted_run.source_hash = requested_source_hash", body)
        self.assertIn("persisted run source hash does not match request", body)
        self.assertIn("legacy_result->>'created' = 'false'", body)
        self.assertIn(
            "returned_requested_public_count <> expected_public_count", body
        )
        self.assertIn("return legacy_result", body)
        self.assertIn("set visibility = 'public', razonamiento = null", body)
        self.assertIn("jsonb_set(legacy_result, '{picks}'", body)

        self.assertIn(
            "create or replace function public.enforce_two_public_pending_picks()",
            text,
        )
        trigger_body = function_body(
            SIX_PICK_PORTFOLIO_SQL,
            "public.enforce_two_public_pending_picks() returns trigger",
        )
        self.assertIn("pg_advisory_xact_lock(20260820233000)", trigger_body)
        self.assertIn("persisted_row.batch_id = new.batch_id", trigger_body)
        self.assertIn("persisted_row.active is true", trigger_body)
        self.assertIn("new.active is not true", trigger_body)
        self.assertIn("public_pick_count > 2", trigger_body)
        self.assertIn("raise exception 'at most two public pending picks are allowed'", trigger_body)
        self.assertIn(
            "create constraint trigger picks_at_most_two_public_pending", text
        )
        self.assertIn("after insert or update on public.picks", text)
        self.assertIn("deferrable initially immediate", text)

        self.assertIn(
            "revoke all on function public.publish_pick_batch(text, text, jsonb) "
            "from public, anon, authenticated",
            text,
        )
        self.assertIn(
            "grant execute on function public.publish_pick_batch(text, text, jsonb) "
            "to service_role",
            text,
        )

    def test_api_football_budget_and_cache_are_service_role_only(self):
        self.assertTrue(LINEUP_BUDGET_SQL.exists())
        text = " ".join(
            LINEUP_BUDGET_SQL.read_text(encoding="utf-8").lower().split()
        )
        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))
        self.assertIn(
            "create table if not exists public.api_football_request_budget",
            text,
        )
        self.assertIn("quota_day date primary key", text)
        self.assertIn("requests_used between 0 and 40", text)
        self.assertIn(
            "create table if not exists public.api_football_cache", text
        )
        self.assertGreaterEqual(
            text.count("enable row level security"), 2
        )
        self.assertIn(
            "create or replace function public.claim_api_football_request",
            text,
        )
        self.assertIn("for update", text)
        self.assertIn("least(requested_limit, 40)", text)
        self.assertIn(
            "server_quota_day := (now() at time zone 'utc')::date", text
        )
        self.assertIn(
            "if requested_quota_day <> server_quota_day then return false",
            text,
        )
        self.assertIn(
            "create or replace function public.get_api_football_cache", text
        )
        self.assertIn(
            "create or replace function public.put_api_football_cache", text
        )
        self.assertIn("security definer", text)
        self.assertIn("set search_path = pg_catalog, public", text)
        self.assertIn(
            "revoke all on table public.api_football_request_budget from public, anon, authenticated",
            text,
        )
        self.assertIn(
            "revoke all on table public.api_football_cache from public, anon, authenticated",
            text,
        )
        self.assertIn(
            "grant execute on function public.claim_api_football_request(date, integer) to service_role",
            text,
        )
    def test_legacy_pick_policies_are_replaced_by_a_strict_allowlist(self):
        self.assertTrue(
            LEGACY_POLICY_HARDENING_SQL.exists(),
            "a follow-up migration must remove unknown legacy picks policies",
        )
        text = " ".join(
            LEGACY_POLICY_HARDENING_SQL.read_text(encoding="utf-8")
            .lower()
            .split()
        )
        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))
        self.assertIn("from pg_policies", text)
        self.assertIn("schemaname = 'public'", text)
        self.assertIn("tablename = 'picks'", text)
        self.assertIn("drop policy %i on public.picks", text)
        self.assertIn(
            "revoke insert, update, delete, truncate, references, trigger on table public.picks from anon",
            text,
        )
        self.assertIn("grant select on table public.picks to anon", text)
        self.assertIn(
            "create or replace function public.picks_policy_allowlist_status()",
            text,
        )
        self.assertIn("returns boolean", text)
        self.assertIn("security definer", text)
        self.assertIn("count(*) = 6", text)
        self.assertIn("not has_table_privilege( 'anon', 'public.picks', 'insert' )", text)
        self.assertIn(
            "revoke all on function public.picks_policy_allowlist_status() from public, anon, authenticated",
            text,
        )
        self.assertIn(
            "grant execute on function public.picks_policy_allowlist_status() to service_role",
            text,
        )
        for policy in (
            "picks_public_read",
            "picks_member_read",
            "picks_admin_select",
            "picks_admin_insert",
            "picks_admin_update",
            "picks_admin_delete",
        ):
            self.assertIn(f"create policy {policy} on public.picks", text)

    def test_base_profiles_and_picks_schema_precedes_membership_and_is_upgrade_safe(self):
        migrations = sorted(path.name for path in SQL.parent.glob("*.sql"))
        self.assertLess(
            migrations.index(BASE_SCHEMA_SQL.name),
            migrations.index(SQL.name),
        )
        text = " ".join(BASE_SCHEMA_SQL.read_text(encoding="utf-8").lower().split())
        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))
        self.assertIn("create table if not exists public.profiles", text)
        self.assertIn("references auth.users(id) on delete cascade", text)
        self.assertIn("create table if not exists public.picks", text)
        self.assertIn("id bigint generated by default as identity primary key", text)
        self.assertIn("alter table public.profiles add column if not exists role", text)
        self.assertIn("alter table public.picks add column if not exists categoria", text)
        self.assertIn(
            "add column if not exists source_starts_at timestamptz",
            text,
        )
        for column in (
            "partido",
            "pick",
            "cuota",
            "confianza",
            "razonamiento",
            "marcador",
            "estado",
            "es_parlay",
            "liga",
            "mercado",
            "riesgo",
            "resultado_apuesta",
            "ganancia_simulada",
            "fecha_generacion",
            "odds_mercado",
            "tiene_valor",
        ):
            self.assertIn(f"add column if not exists {column}", text)
        self.assertNotIn("drop table", text)
        self.assertNotIn("truncate", text)

    def test_migration_enables_rls_and_public_contracts(self):
        text = SQL.read_text(encoding="utf-8").lower()
        self.assertGreaterEqual(text.count("enable row level security"), 4)
        self.assertIn("public_picks", text)
        self.assertIn("is_active_subscriber", text)
        self.assertIn("get_visible_picks", text)
        normalized = " ".join(text.split())
        self.assertIn(
            "create policy picks_public_read on public.picks for select to anon, authenticated using (visibility = 'public');",
            normalized,
        )
        self.assertNotIn("using (true)", text)

    def test_premium_access_requires_an_unexpired_subscription(self):
        text = SQL.read_text(encoding="utf-8").lower()
        self.assertIn("status in ('active', 'trialing')", text)
        self.assertIn("current_period_end > now()", text)

    def test_existing_settled_rows_are_explicitly_made_public(self):
        text = SQL.read_text(encoding="utf-8").lower()
        self.assertIn("set visibility = 'public'", text)
        self.assertIn("estado in ('ganado', 'perdido', 'void', 'revision_pendiente')", text)

    def test_database_enforces_at_most_one_public_pending_pick(self):
        text = " ".join(SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("create unique index if not exists picks_one_public_pending_idx", text)
        self.assertIn("where visibility = 'public' and estado = 'pendiente'", text)

    def test_customer_linking_promo_and_spei_flows_are_server_controlled(self):
        text = SQL.read_text(encoding="utf-8").lower()
        self.assertIn("create_telegram_link_token", text)
        self.assertIn("consume_telegram_link_token", text)
        self.assertIn("redeem_promo_code", text)
        self.assertIn("create_promo_code", text)
        self.assertIn("approve_spei_review", text)
        self.assertIn("reject_spei_review", text)
        self.assertIn("reviewed_by", text)
        self.assertIn("reviewed_at", text)
        self.assertIn("for update", text)
        self.assertIn("profiles_telegram_id_unique", text)
        self.assertIn("linked_user is not null and linked_user <> review_user", text)

    def test_stripe_events_are_applied_atomically_in_created_order(self):
        text = SQL.read_text(encoding="utf-8").lower()
        webhook = (SQL.parents[1] / "functions" / "stripe-webhook" / "index.ts").read_text(encoding="utf-8")
        self.assertIn("stripe_webhook_events", text)
        self.assertIn(
            "revoke all on table public.stripe_webhook_events from anon, authenticated",
            text,
        )
        self.assertIn("provider_event_created", text)
        self.assertIn("apply_stripe_subscription_event", text)
        self.assertIn('rpc("apply_stripe_subscription_event"', webhook)

    def test_scraper_run_ledger_has_batch_and_pick_invariants(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("create table if not exists public.scraper_runs", text)
        self.assertIn("run_key text not null unique", text)
        self.assertIn("status in ('running', 'published', 'partial', 'failed')", text)
        self.assertIn("source_hash text not null", text)
        self.assertIn("delivery_status jsonb not null default '{}'::jsonb", text)
        self.assertIn("error_message text", text)
        self.assertIn("created_at timestamptz not null default now()", text)
        self.assertIn("finished_at timestamptz", text)
        self.assertIn("create table if not exists public.pick_batches", text)
        self.assertIn("run_id uuid not null unique references public.scraper_runs(id)", text)
        self.assertIn("create unique index if not exists pick_batches_one_active_idx", text)
        self.assertIn("where active", text)
        self.assertIn("add column if not exists batch_id uuid references public.pick_batches(id)", text)
        self.assertIn("add column if not exists active boolean not null default false", text)
        self.assertIn("alter column id type bigint using id::bigint", text)
        self.assertIn("drop view if exists public.public_picks", text)
        self.assertIn("create or replace view public.public_picks", text)
        self.assertLess(
            text.index("alter column id type bigint using id::bigint"),
            text.index("floor(extract(epoch from clock_timestamp()) * 1000000)"),
        )
        self.assertIn("create index if not exists picks_active_batch_idx", text)

    def test_publishing_rpc_is_atomic_idempotent_and_validates_visibility(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("create or replace function public.publish_pick_batch", text)
        self.assertIn("security definer", text)
        self.assertIn("jsonb_typeof(requested_picks) <> 'array'", text)
        self.assertIn("jsonb_array_length(requested_picks) = 0", text)
        self.assertIn("count(*) filter (where value->>'visibility' = 'public')", text)
        self.assertIn("public_pick_count <> 1", text)
        self.assertIn("public_parlay_count <> 0", text)
        self.assertIn("value->>'visibility' = 'public'", text)
        self.assertIn("coalesce((value->>'es_parlay')::boolean, false)", text)
        self.assertIn("on conflict (run_key) do nothing", text)
        self.assertIn("for update", text)
        lock_position = text.index("for update")
        hash_check_position = text.index(
            "if claimed_run.source_hash <> requested_source_hash"
        )
        replay_position = text.index("if claimed_run.status in ('published', 'partial')")
        self.assertLess(lock_position, replay_position)
        self.assertLess(replay_position, hash_check_position)
        self.assertIn("claimed_run.status in ('published', 'partial')", text)
        self.assertIn("'run_id', claimed_run.id", text)
        self.assertIn("select * into resumed_batch from public.pick_batches", text)
        self.assertIn("created_batch := resumed_batch.id", text)
        self.assertIn("where run_id = claimed_run.id", text)
        self.assertIn("'delivery_status', claimed_run.delivery_status", text)
        self.assertIn("'created', false", text)
        self.assertIn("'picks', persisted_picks", text)

    def test_publishing_rpcs_return_exact_persisted_rows_for_create_and_replay(self):
        expected_fields = {
            "id",
            "categoria",
            "partido",
            "pick",
            "cuota",
            "confianza",
            "razonamiento",
            "marcador",
            "estado",
            "es_parlay",
            "liga",
            "mercado",
            "riesgo",
            "resultado_apuesta",
            "ganancia_simulada",
            "fecha_generacion",
            "fecha_evento",
            "horario",
            "odds_mercado",
            "tiene_valor",
            "visibility",
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
            "source_observed_at",
            "source_starts_at",
        }
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            start = text.index("create or replace function public.publish_pick_batch")
            end = text.index(
                "create or replace function public.resume_pick_batch",
                start,
            )
            function = text[start:end]
            replay = function.index("if claimed_run.status in ('published', 'partial')")
            hash_guard = function.index(
                "if claimed_run.source_hash <> requested_source_hash"
            )
            self.assertLess(replay, hash_guard)
            self.assertGreaterEqual(function.count("into persisted_picks"), 2)
            self.assertGreaterEqual(function.count("'picks', persisted_picks"), 2)
            self.assertIn("jsonb_agg(jsonb_build_object(", function)
            for field in expected_fields:
                self.assertIn(f"'{field}', persisted_row.{field}", function)
            self.assertNotIn("to_jsonb(persisted_row)", function)

    def test_publishing_rpc_replaces_the_active_pending_lifecycle(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("update public.picks set visibility = 'premium'", text)
        self.assertIn("where estado = 'pendiente' and visibility = 'public'", text)
        self.assertIn("update public.pick_batches set active = false where active", text)
        self.assertIn("update public.picks set active = false where active", text)
        self.assertIn("jsonb_populate_record(null::public.picks", text)
        self.assertIn("set status = 'published', finished_at = now()", text)
        self.assertIn("'created', true", text)

    def test_resume_rpc_is_service_only_and_returns_exact_active_persisted_rows(self):
        expected_fields = (
            "id", "categoria", "partido", "pick", "cuota", "confianza",
            "razonamiento", "marcador", "estado", "es_parlay", "liga",
            "mercado", "riesgo", "resultado_apuesta", "ganancia_simulada",
            "fecha_generacion", "fecha_evento", "horario", "odds_mercado",
            "tiene_valor", "visibility", "source", "source_event_id",
            "source_market_key", "source_selection_key", "source_observed_at",
            "source_starts_at",
        )
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            start = text.index("create or replace function public.resume_pick_batch")
            end = text.index("$$;", start)
            function = text[start:end]

            self.assertIn("resume_pick_batch( requested_run_key text ) returns jsonb", function)
            self.assertIn("language plpgsql security definer", function)
            self.assertIn("set search_path = public, pg_temp", function)
            self.assertIn("perform pg_advisory_xact_lock(20260820233000)", function)
            self.assertIn("claimed_run.status not in ('published', 'partial')", function)
            self.assertIn("return null", function)
            self.assertIn("resumed_batch.active", function)
            self.assertIn("scraper run batch is inactive or superseded", function)
            self.assertIn("for update", function)
            self.assertIn("'created', false", function)
            self.assertNotIn("to_jsonb(persisted_row)", function)
            for field in expected_fields:
                self.assertIn(f"'{field}', persisted_row.{field}", function)

            signature = "public.resume_pick_batch(text)"
            self.assertIn(
                f"revoke all on function {signature} from public, anon, authenticated",
                text,
            )
            self.assertIn(
                f"grant execute on function {signature} to service_role",
                text,
            )

    def test_publish_replay_requires_the_original_batch_to_still_be_active(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            start = text.index("create or replace function public.publish_pick_batch")
            replay_start = text.index("if claimed_run.status in ('published', 'partial')", start)
            replay_end = text.index(
                "if claimed_run.source_hash <> requested_source_hash",
                replay_start,
            )
            replay = text[replay_start:replay_end]

            self.assertIn("resumed_batch.active", replay)
            self.assertIn("scraper run batch is inactive or superseded", replay)
            self.assertLess(
                replay.index("scraper run batch is inactive or superseded"),
                replay.index("return jsonb_build_object"),
            )

    def test_visible_picks_only_exposes_active_pending_or_settled_public_rows(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("create or replace function public.get_visible_picks()", text)
        self.assertIn("p.estado = 'pendiente' and p.active", text)
        self.assertIn("p.visibility = 'public' or public.is_active_subscriber(auth.uid())", text)
        self.assertIn("p.estado <> 'pendiente' and p.visibility = 'public'", text)
        self.assertIn("grant execute on function public.get_visible_picks() to anon, authenticated", text)

    def test_delivery_rpc_and_ledger_tables_are_server_only(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("create or replace function public.record_scraper_delivery", text)
        self.assertIn("jsonb_set", text)
        self.assertIn("array[requested_destination]", text)
        self.assertIn("'success', requested_success", text)
        self.assertIn("'error', left(coalesce(requested_error, ''), 200)", text)
        self.assertIn("'updated_at', now()", text)
        self.assertIn("if requested_success is null then", text)
        self.assertIn("next_delivery_status", text)
        self.assertIn("jsonb_each(updated.next_delivery_status)", text)
        self.assertIn("details->>'success' is distinct from 'true'", text)
        self.assertIn("then 'published' else 'partial'", text)
        self.assertIn(
            "where id = requested_run_id and status in ('published', 'partial') for update",
            text,
        )
        self.assertIn("unknown or unpublished scraper run %", text)
        self.assertIn("alter table public.scraper_runs enable row level security", text)
        self.assertIn("alter table public.pick_batches enable row level security", text)
        for table in ("scraper_runs", "pick_batches"):
            self.assertIn(f"revoke all on table public.{table} from public, anon, authenticated", text)
            self.assertIn(f"grant all on table public.{table} to service_role", text)
        for signature in (
            "public.publish_pick_batch(text, text, jsonb)",
            "public.record_scraper_delivery(uuid, text, boolean, text)",
        ):
            self.assertIn(f"revoke all on function {signature} from public, anon, authenticated", text)
            self.assertIn(f"grant execute on function {signature} to service_role", text)
        self.assertNotIn("grant select on table public.scraper_runs to anon", text)
        self.assertNotIn("grant select on table public.pick_batches to authenticated", text)

    def test_scraper_schema_probe_rpc_is_read_only_and_service_role_only(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        signature = "public.scraper_schema_status()"
        self.assertIn(f"create or replace function {signature}", text)
        self.assertIn("to_regclass('public.public_picks') is not null", text)
        self.assertIn(
            "to_regprocedure('public.publish_pick_batch(text,text,jsonb)') is not null",
            text,
        )
        self.assertIn(
            "to_regprocedure('public.resume_pick_batch(text)') is not null",
            text,
        )
        self.assertIn("'version', 1", text)
        self.assertIn("'source_audit', false", text)
        self.assertIn(f"revoke all on function {signature} from public, anon, authenticated", text)
        self.assertIn(f"grant execute on function {signature} to service_role", text)
        probe_start = text.index(f"create or replace function {signature}")
        probe_end = text.index(f"revoke all on function {signature}", probe_start)
        probe = text[probe_start:probe_end]
        self.assertNotIn("insert into", probe)
        self.assertNotIn("update public.", probe)
        self.assertNotIn("delete from", probe)

    def test_direct_pick_reads_enforce_the_active_batch_lifecycle(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("drop policy if exists picks_public_read on public.picks", text)
        self.assertIn("drop policy if exists picks_member_read on public.picks", text)
        self.assertIn("drop policy if exists picks_subscriber_read on public.picks", text)

        public_start = text.index("create policy picks_public_read on public.picks")
        member_start = text.index("create policy picks_member_read on public.picks")
        public_policy = text[public_start:member_start]
        member_policy = text[member_start:]
        self.assertIn("for select to anon", public_policy)
        self.assertIn("for select to authenticated", member_policy)
        for policy in (public_policy, member_policy):
            self.assertIn("estado = 'pendiente' and active", policy)
            self.assertIn("estado <> 'pendiente' and visibility = 'public'", policy)
        self.assertIn("visibility = 'public'", public_policy)
        self.assertIn("public.is_active_subscriber(auth.uid())", member_policy)
        self.assertNotIn("using (visibility = 'public')", text)
        self.assertNotIn("create policy picks_subscriber_read", text)

        self.assertIn("drop policy if exists picks_admin_write on public.picks", text)
        self.assertNotIn("create policy picks_admin_write", text)
        self.assertIn("drop policy if exists picks_admin_select on public.picks", text)
        self.assertIn("create policy picks_admin_select", text)
        self.assertIn(
            "create policy picks_admin_select on public.picks for select to authenticated using (public.is_admin(auth.uid()))",
            text,
        )
        self.assertIn("create policy picks_admin_insert", text)
        self.assertIn("create policy picks_admin_update", text)
        self.assertIn("create policy picks_admin_delete", text)

    def test_scraper_run_ledger_migration_is_transactional(self):
        text = RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().strip()
        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))

    def test_picks_store_source_market_audit_fields_idempotently(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))
        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
            "source_observed_at",
            "source_starts_at",
        ):
            self.assertIn(f"add column if not exists {field}", text)
        self.assertIn(
            "create index if not exists picks_source_event_idx on public.picks (source, source_event_id)",
            text,
        )
        self.assertIn("source is not null", text)
        self.assertIn("source_event_id is not null", text)
        self.assertIn("picks_source_audit_complete_check", text)

    def test_every_publishing_rpc_version_validates_audit_before_mutation(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            function_start = text.index("create or replace function public.publish_pick_batch")
            function = text[function_start:]
            audit_validation = function.index("each requested pick must have complete source audit fields")
            first_mutation = min(
                function.index("insert into public.scraper_runs"),
                function.index("update public.picks"),
            )
            self.assertLess(audit_validation, first_mutation)
            self.assertIn("length(btrim(value->>'source')) not between 1 and 100", function)
            self.assertIn("observed_at_value :=", function)
            for field in (
                "source",
                "source_event_id",
                "source_market_key",
                "source_selection_key",
                "source_observed_at",
                "source_starts_at",
            ):
                self.assertIn(f"(requested_rows.populated).{field}", function)
            self.assertIn("(source, source_event_id)", text)

    def test_source_audit_upgrade_replaces_rpc_after_columns_exist(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        columns = text.index("add column if not exists source text")
        function = text.index("create or replace function public.publish_pick_batch")
        self.assertLess(columns, function)
        self.assertIn("jsonb_populate_record(null::public.picks", text)
        self.assertIn("revoke all on function public.publish_pick_batch", text)
        self.assertIn("grant execute on function public.publish_pick_batch", text)

    def test_source_audit_constraint_uses_only_a_protected_legacy_marker(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        start = text.index("add constraint picks_source_audit_complete_check")
        end = text.index(") not valid;", start) + len(") not valid;")
        constraint = text[start:end]

        # No local PostgreSQL server is available in this test environment. The
        # nullable version marker is reserved for pre-migration rows; a trigger
        # forces every insert and any audit-changing update to version 1.
        self.assertIn(") not valid;", constraint)
        self.assertIn("source_audit_version is null", constraint)
        self.assertIn("source_audit_version = 1", constraint)
        self.assertNotIn("source is null", constraint)
        self.assertNotIn("source_event_id is null", constraint)
        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
            "source_observed_at",
            "source_starts_at",
        ):
            self.assertIn(f"{field} is not null", constraint)
        self.assertIn("source_starts_at > source_observed_at", constraint)
        self.assertIn("length(btrim(source)) between 1 and 100", constraint)

    def test_audit_version_trigger_preserves_legacy_updates_without_new_row_bypass(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())

        self.assertIn("add column if not exists source_audit_version smallint", text)
        self.assertIn("alter column source_audit_version set default 1", text)
        self.assertIn(
            "create trigger picks_enforce_source_audit_version before insert or update on public.picks",
            text,
        )
        self.assertIn(
            "revoke all on function public.enforce_pick_source_audit_version() from public, anon, authenticated",
            text,
        )
        self.assertIn(
            "grant execute on function public.enforce_pick_source_audit_version() to service_role",
            text,
        )
        self.assertIn("if tg_op = 'insert' then new.source_audit_version := 1", text)
        self.assertIn(
            "elsif new.estado = 'pendiente' and new.active then new.source_audit_version := 1",
            text,
        )
        self.assertIn("old.source_audit_version = 1", text)
        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
            "source_observed_at",
            "source_starts_at",
        ):
            self.assertIn(
                f"new.{field} is distinct from old.{field}",
                text,
            )

    def test_audited_source_identity_is_immutable_after_publication(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        trigger_start = text.index(
            "create or replace function public.enforce_pick_source_audit_version"
        )
        trigger_end = text.index("$$;", trigger_start)
        trigger = text[trigger_start:trigger_end]
        guard = trigger.index("if old.source_audit_version = 1")
        failure = trigger.index("raise exception 'published source audit is immutable'")
        self.assertLess(guard, failure)
        self.assertIn("new.source_audit_version is distinct from 1", trigger)
        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
            "source_observed_at",
            "source_starts_at",
        ):
            self.assertIn(f"new.{field} is distinct from old.{field}", trigger)

    def test_intermediate_ledger_probe_never_announces_source_audit_ready(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        start = text.index("create or replace function public.scraper_schema_status()")
        end = text.index("$$;", start)
        probe = text[start:end]

        self.assertIn("'version', 1", probe)
        self.assertIn("'source_audit', false", probe)
        self.assertNotIn("'version', 2", probe)

    def test_final_probe_requires_columns_strict_constraint_and_source_index(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        start = text.index("create or replace function public.scraper_schema_status()")
        end = text.index("$$;", start)
        probe = text[start:end]

        self.assertIn("'version', 2", probe)
        self.assertIn("from pg_index as audit_index", probe)
        self.assertIn("audit_index.indrelid = 'public.picks'::regclass", probe)
        self.assertIn("audit_index.indisvalid", probe)
        self.assertIn("audit_index.indisready", probe)
        self.assertIn("pg_get_indexdef(audit_index.indexrelid)", probe)
        self.assertIn(
            "create index picks_source_event_idx on public.picks using btree (source, source_event_id)",
            probe,
        )
        self.assertNotIn(
            "to_regclass('public.picks_source_event_idx') is not null",
            probe,
        )
        self.assertIn("conname = 'picks_source_audit_complete_check'", probe)
        self.assertIn("column_name = 'source_audit_version'", probe)
        self.assertIn("tgname = 'picks_enforce_source_audit_version'", probe)
        self.assertIn("pg_get_triggerdef", probe)
        self.assertIn("pg_get_functiondef", probe)
        self.assertIn("new.source_audit_version := 1", probe)
        self.assertIn("pg_get_constraintdef", probe)
        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
            "source_observed_at",
        ):
            self.assertIn(f"'{field} is not null'", probe)
        self.assertIn("'source_audit_version is null'", probe)
        self.assertIn("'source_audit_version = 1'", probe)
        self.assertIn("'source_starts_at > source_observed_at'", probe)

    def test_final_probe_rejects_replica_only_or_disabled_audit_triggers(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        start = text.index("create or replace function public.scraper_schema_status()")
        end = text.index("$$;", start)
        probe = text[start:end]

        self.assertIn("audit_trigger.tgenabled in ('o', 'a')", probe)
        self.assertNotIn("audit_trigger.tgenabled <> 'd'", probe)
        self.assertNotIn("audit_trigger.tgenabled = 'r'", probe)

    def test_audit_migration_fails_closed_on_a_wrong_homonymous_source_index(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        create_position = text.index("create index if not exists picks_source_event_idx")
        validation_position = text.index("from pg_index as audit_index")
        failure_position = text.index(
            "raise exception 'picks_source_event_idx has unexpected definition'"
        )
        function_position = text.index(
            "create or replace function public.enforce_pick_source_audit_version"
        )

        self.assertLess(create_position, validation_position)
        self.assertLess(validation_position, failure_position)
        self.assertLess(failure_position, function_position)
        validation = text[validation_position:failure_position]
        self.assertIn("audit_index.indrelid = 'public.picks'::regclass", validation)
        self.assertIn("audit_index.indisvalid", validation)
        self.assertIn("audit_index.indisready", validation)
        self.assertIn("pg_get_indexdef(audit_index.indexrelid)", validation)

    def test_publishing_rpcs_require_utc_non_future_observations_before_mutation(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            start = text.index("create or replace function public.publish_pick_batch")
            function = text[start:]
            utc_validation = function.index("source_observed_at must be utc and not in the future")
            first_mutation = min(
                function.index("insert into public.scraper_runs"),
                function.index("update public.picks"),
            )

            self.assertLess(utc_validation, first_mutation)
            self.assertIn("(z|[+]00:00)$", function)
            self.assertIn("observed_at_value > now()", function)
            self.assertIn(
                "exception when invalid_datetime_format or datetime_field_overflow",
                function,
            )
            self.assertNotIn("[+-][0-9]{2}:[0-9]{2}", function[:first_mutation])
            pattern_match = re.search(
                r"source_observed_at'\) !~ '([^']+)'",
                function[:first_mutation],
            )
            self.assertIsNotNone(pattern_match)
            pattern = pattern_match.group(1)
            self.assertIsNotNone(
                re.fullmatch(pattern, "2026-08-20T16:05:00Z", re.IGNORECASE)
            )
            self.assertIsNotNone(
                re.fullmatch(
                    pattern,
                    "2026-08-20T16:05:00+00:00",
                    re.IGNORECASE,
                )
            )
            self.assertIsNone(
                re.fullmatch(
                    pattern,
                    "2026-08-20T10:05:00-06:00",
                    re.IGNORECASE,
                )
            )

    def test_publishing_rpcs_require_future_utc_source_start_before_mutation(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            start = text.index("create or replace function public.publish_pick_batch")
            function = text[start:]
            first_mutation = min(
                function.index("insert into public.scraper_runs"),
                function.index("update public.picks"),
            )
            validation = function[:first_mutation]

            self.assertIn("value->>'source_starts_at'", validation)
            self.assertIn("starts_at_value := (audit_entry->>'source_starts_at')::timestamptz", validation)
            self.assertIn("starts_at_value <= observed_at_value", validation)
            self.assertIn("starts_at_value <= now()", validation)
            self.assertIn("source_starts_at must be utc, after source_observed_at, and in the future", validation)
            pattern_match = re.search(
                r"source_starts_at'\) !~ '([^']+)'",
                validation,
            )
            self.assertIsNotNone(pattern_match)
            pattern = pattern_match.group(1)
            self.assertIsNotNone(
                re.fullmatch(pattern, "2026-08-21T02:00:00Z", re.IGNORECASE)
            )
            self.assertIsNotNone(
                re.fullmatch(pattern, "2026-08-21T02:00:00+00:00", re.IGNORECASE)
            )
            self.assertIsNone(
                re.fullmatch(pattern, "2026-08-20T20:00:00-06:00", re.IGNORECASE)
            )

    def test_replay_and_resume_reject_stale_persisted_starts_before_return(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            publish_start = text.index("create or replace function public.publish_pick_batch")
            resume_start = text.index("create or replace function public.resume_pick_batch", publish_start)
            publish = text[publish_start:resume_start]
            replay_start = publish.index("if claimed_run.status in ('published', 'partial')")
            replay_end = publish.index("if claimed_run.source_hash <> requested_source_hash", replay_start)
            replay = publish[replay_start:replay_end]
            resume_end = text.index("$$;", resume_start)
            resume = text[resume_start:resume_end]

            for function in (replay, resume):
                self.assertIn("persisted_row.source_starts_at is null", function)
                self.assertIn("persisted_row.source_starts_at <= clock_timestamp()", function)
                self.assertIn("persisted pick event is stale", function)
                self.assertLess(
                    function.index("persisted pick event is stale"),
                    function.index("return jsonb_build_object"),
                )

    def test_create_revalidates_start_after_waiting_for_publication_lock(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            start = text.index("create or replace function public.publish_pick_batch")
            function = text[start:]
            lock = function.index("perform pg_advisory_xact_lock(20260820233000)")
            first_mutation = function.index("insert into public.scraper_runs", lock)
            post_lock = function[lock:first_mutation]

            self.assertIn("(value->>'source_starts_at')::timestamptz <= clock_timestamp()", post_lock)
            self.assertIn("source_starts_at expired while waiting for publication lock", post_lock)

    def test_create_rolls_back_if_start_expires_during_pick_insert(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            start = text.index("create or replace function public.publish_pick_batch")
            function = text[start:]
            pick_insert = function.index("insert into public.picks")
            publish_status = function.index("update public.scraper_runs", pick_insert)
            post_insert = function[pick_insert:publish_status]

            self.assertIn("persisted_row.batch_id = created_batch", post_insert)
            self.assertIn("persisted_row.source_starts_at <= clock_timestamp()", post_insert)
            self.assertIn("source_starts_at expired during batch persistence", post_insert)

    def test_source_audit_upgrade_hides_active_unaudited_legacy_rows_before_v2(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        batch_demotion = text.index("with retired_batches as (")
        pick_demotion = text.index("update public.picks as legacy_picks")
        version_default = text.index("alter column source_audit_version set default 1")
        probe = text.index("create or replace function public.scraper_schema_status()")

        self.assertLess(batch_demotion, pick_demotion)
        self.assertLess(pick_demotion, version_default)
        self.assertLess(pick_demotion, probe)
        demotion = text[batch_demotion:version_default]
        self.assertIn("legacy_batches.active", demotion)
        self.assertIn("update public.picks as legacy_picks set active = false", demotion)
        self.assertIn("then 'premium'", demotion)
        self.assertIn("estado = 'pendiente'", demotion)
        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
            "source_observed_at",
        ):
            self.assertIn(f"legacy_picks.{field}", demotion)
        self.assertIn(
            "length(btrim(legacy_picks.source_market_key)) not between 1 and 1000",
            demotion,
        )
        self.assertIn("legacy_picks.source_observed_at > now()", demotion)
        self.assertIn("with retired_batches as ( update public.pick_batches", demotion)
        self.assertIn("returning legacy_batches.id", demotion)
        self.assertIn("update public.picks as retired_batch_picks", demotion)
        self.assertIn(
            "update public.picks as retired_batch_picks set active = false",
            demotion,
        )
        self.assertIn(
            "retired_batch_picks.batch_id in (select id from retired_batches)",
            demotion,
        )

    def test_source_audit_upgrade_backfills_public_reasoning_before_v2(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        backfill = text.index(
            "update public.picks set razonamiento = null "
            "where visibility = 'public' and razonamiento is not null"
        )
        trigger = text.index(
            "create or replace function public.enforce_pick_source_audit_version"
        )
        probe = text.index("create or replace function public.scraper_schema_status()")

        self.assertLess(backfill, trigger)
        self.assertLess(backfill, probe)

    def test_database_redacts_public_reasoning_in_every_rpc_and_view(self):
        for migration in (RUN_LEDGER_SQL, SOURCE_AUDIT_SQL):
            text = " ".join(migration.read_text(encoding="utf-8").lower().split())
            view_start = text.index("create or replace view public.public_picks")
            function_start = text.index(
                "create or replace function public.publish_pick_batch", view_start
            )
            view = text[view_start:function_start]
            function = text[function_start:]

            self.assertNotIn("razonamiento", view)
            self.assertIn(
                "case when (requested_rows.populated).visibility = 'public' "
                "then null else (requested_rows.populated).razonamiento end",
                function,
            )

        final = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("if new.visibility = 'public' then new.razonamiento := null", final)

    def test_final_probe_checks_exact_types_secure_view_rpc_rls_and_acl(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        start = text.index("create or replace function public.scraper_schema_status()")
        end = text.index("$$;", start)
        probe = text[start:end]

        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
        ):
            self.assertIn(f"column_name = '{field}' and data_type = 'text'", probe)
        self.assertIn(
            "column_name = 'source_observed_at' and data_type = 'timestamp with time zone'",
            probe,
        )
        self.assertIn(
            "column_name = 'source_starts_at' and data_type = 'timestamp with time zone'",
            probe,
        )
        self.assertIn(
            "column_name = 'source_audit_version' and data_type = 'smallint'",
            probe,
        )

        self.assertIn("public_view.relkind = 'v'", probe)
        self.assertIn("security_invoker=true", probe)
        self.assertIn("pg_get_viewdef", probe)
        self.assertIn("visibility = ''public''", probe)
        self.assertIn("' or '", probe)
        self.assertIn("' union '", probe)
        self.assertIn("position( 'razonamiento'", probe)
        self.assertIn("= 0", probe)
        self.assertIn("has_table_privilege( 'anon'", probe)
        self.assertIn("has_table_privilege( 'authenticated'", probe)

        self.assertIn("publish_rpc.prosecdef", probe)
        self.assertIn("publish_rpc.prorettype = 'jsonb'::regtype", probe)
        self.assertIn("publish_language.lanname = 'plpgsql'", probe)
        self.assertIn("search_path=public, pg_temp", probe)
        self.assertIn("from aclexplode", probe)
        self.assertIn("publish_acl.grantee = 0", probe)
        self.assertIn("publish_acl.grantee <> publish_rpc.proowner", probe)
        self.assertIn("publish_role.rolname <> 'service_role'", probe)
        self.assertIn("from pg_roles as executable_role", probe)
        self.assertIn("not executable_role.rolsuper", probe)
        self.assertIn(
            "has_function_privilege( executable_role.oid, publish_rpc.oid, 'execute' )",
            probe,
        )
        self.assertNotIn(
            "publish_role.rolname in ( 'anon', 'authenticated' )",
            probe,
        )
        self.assertIn("service_role.rolname = 'service_role'", probe)
        self.assertIn("pg_get_functiondef", probe)
        self.assertIn("'not resumed_batch.active'", probe)
        self.assertEqual(probe.count("'not resumed_batch.active'"), 2)
        self.assertIn("'scraper run batch is inactive or superseded'", probe)
        self.assertIn(
            "'source_starts_at expired while waiting for publication lock'",
            probe,
        )
        self.assertIn(
            "'source_starts_at expired during batch persistence'",
            probe,
        )
        self.assertIn(
            "'where persisted_row.batch_id = created_batch and persisted_row.source_starts_at <= clock_timestamp()'",
            probe,
        )
        self.assertEqual(
            probe.count("'persisted_row.source_starts_at <= clock_timestamp()'"),
            2,
        )

        self.assertIn("'resume_pick_batch'", probe)
        self.assertIn("resume_rpc.prosecdef", probe)
        self.assertIn("resume_rpc.prorettype = 'jsonb'::regtype", probe)
        self.assertIn("resume_language.lanname = 'plpgsql'", probe)
        self.assertIn("resume_acl.grantee = 0", probe)
        self.assertIn("resume_role.rolname <> 'service_role'", probe)
        self.assertIn("service_resume_role.rolname = 'service_role'", probe)
        self.assertIn("pg_get_functiondef(resume_rpc.oid)", probe)
        self.assertIn("scraper run batch is inactive or superseded", probe)
        self.assertIn("where persisted_row.batch_id = resumed_batch.id", probe)
        self.assertIn("jsonb_array_length(persisted_picks) = 0", probe)
        self.assertIn("to_jsonb(persisted_row)", probe)
        self.assertIn("= 0", probe)
        self.assertIn("from unnest( array[", probe)
        self.assertIn("format( '''%s'', persisted_row.%s'", probe)
        self.assertIn("from regexp_matches(", probe)
        self.assertIn("persisted_row\\.[a-z_]", probe)
        self.assertIn(") = 27", probe)

        self.assertIn("picks_table.relrowsecurity", probe)
        self.assertIn(
            "elsif new.estado = ''pendiente'' and new.active then",
            probe,
        )
        self.assertIn("policyname = 'picks_public_read'", probe)
        self.assertIn("policyname = 'picks_member_read'", probe)
        for policy in (
            "picks_admin_select",
            "picks_admin_insert",
            "picks_admin_update",
            "picks_admin_delete",
        ):
            self.assertIn(f"policyname = '{policy}'", probe)
        self.assertIn("ledger_table.relrowsecurity", probe)
        self.assertIn("ledger_table.relname in ( 'scraper_runs', 'pick_batches' )", probe)

    def test_migration_fails_closed_on_wrong_homonymous_audit_constraint(self):
        text = " ".join(SOURCE_AUDIT_SQL.read_text(encoding="utf-8").lower().split())
        creation = text.index("add constraint picks_source_audit_complete_check")
        validation = text.index("from pg_constraint as installed_audit_constraint")
        failure = text.index(
            "raise exception 'picks_source_audit_complete_check has unexpected definition'"
        )
        probe = text.index("create or replace function public.scraper_schema_status()")

        self.assertLess(creation, validation)
        self.assertLess(validation, failure)
        self.assertLess(failure, probe)
        checked = text[validation:failure]
        self.assertIn("installed_audit_constraint.conrelid = 'public.picks'::regclass", checked)
        self.assertIn("installed_audit_constraint.contype = 'c'", checked)
        self.assertIn("pg_get_constraintdef", checked)
        self.assertIn(
            "installed_audit_constraint.conbin::text = expected_audit_constraint.conbin::text",
            text,
        )
        self.assertIn(
            "add constraint picks_source_audit_expected_20260820234500_check",
            text,
        )
        self.assertIn(
            "drop constraint picks_source_audit_expected_20260820234500_check",
            text,
        )

    def test_meta_social_migration_is_transactional_and_upserts_public_jpeg_bucket(self):
        text = " ".join(META_SOCIAL_SQL.read_text(encoding="utf-8").lower().split())

        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))
        self.assertIn(
            "insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)",
            text,
        )
        self.assertIn(
            "values ('social-media', 'social-media', true, 5242880, array['image/jpeg'])",
            text,
        )
        bucket_upsert = text[text.index("insert into storage.buckets"):]
        self.assertIn("on conflict (id) do update", bucket_upsert)
        for assignment in (
            "name = excluded.name",
            "public = excluded.public",
            "file_size_limit = excluded.file_size_limit",
            "allowed_mime_types = excluded.allowed_mime_types",
        ):
            self.assertIn(assignment, bucket_upsert)

    def test_meta_social_read_rpc_selects_the_exact_eligible_run_and_pick(self):
        text = " ".join(META_SOCIAL_SQL.read_text(encoding="utf-8").lower().split())
        signature = "public.get_meta_social_batch( requested_run_key text ) returns jsonb"
        body = function_body(META_SOCIAL_SQL, signature)

        self.assertIn(f"create or replace function {signature}", text)
        function_start = text.index(f"create or replace function {signature}")
        function_end = text.index("$$;", function_start)
        declaration = text[function_start:function_end]
        self.assertIn("language plpgsql security definer", declaration)
        self.assertIn("set search_path = public, pg_temp", declaration)

        self.assertIn("requested_run_key is null", body)
        self.assertIn("btrim(requested_run_key) = ''", body)
        self.assertIn("raise exception 'requested_run_key must not be blank'", body)
        self.assertIn("runs.run_key = requested_run_key", body)
        self.assertIn("runs.status in ('published', 'partial')", body)
        self.assertIn("if not found then return null", body)

        advisory_lock = body.index("perform pg_advisory_xact_lock(20260820233000)")
        first_ledger_read = min(
            body.index("from public.scraper_runs"),
            body.index("from public.pick_batches"),
        )
        self.assertLess(advisory_lock, first_ledger_read)

        self.assertIn("batches.run_id = selected_run.id", body)
        self.assertIn("batches.active", body)
        self.assertIn("if active_batch_count <> 1 then", body)
        self.assertIn("raise exception 'meta social batch integrity error'", body)

        eligible_start = body.index("select count(*) into eligible_pick_count")
        eligible_end = body.index("if eligible_pick_count <> 1 then", eligible_start)
        eligible_statement = body[eligible_start:eligible_end]
        self.assertIn("if eligible_pick_count <> 1 then", body)
        self.assertIn("raise exception 'meta social pick integrity error'", body)
        selected_start = body.index("select picks.* into selected_pick", eligible_end)
        selected_end = body.index(
            "if selected_pick.source_audit_version is distinct from 1",
            selected_start,
        )
        selected_statement = body[selected_start:selected_end]

        for statement in (eligible_statement, selected_statement):
            self.assertIn("picks.batch_id = selected_batch.id", statement)
            self.assertIn("picks.active = true", statement)
            self.assertIn("picks.estado = 'pendiente'", statement)
            self.assertIn("picks.visibility = 'public'", statement)
            self.assertIn("picks.es_parlay = false", statement)
            self.assertNotIn("coalesce(picks.es_parlay", statement)

        for audit_guard in (
            "selected_pick.source_audit_version is distinct from 1",
            "nullif(btrim(selected_pick.source), '') is null",
            "length(btrim(selected_pick.source)) not between 1 and 100",
            "nullif(btrim(selected_pick.source_event_id), '') is null",
            "length(btrim(selected_pick.source_event_id)) not between 1 and 500",
            "nullif(btrim(selected_pick.source_market_key), '') is null",
            "length(btrim(selected_pick.source_market_key)) not between 1 and 1000",
            "nullif(btrim(selected_pick.source_selection_key), '') is null",
            "length(btrim(selected_pick.source_selection_key)) not between 1 and 500",
            "selected_pick.source_observed_at is null",
            "selected_pick.source_starts_at is null",
            "selected_pick.source_observed_at > clock_timestamp()",
            "selected_pick.source_starts_at <= selected_pick.source_observed_at",
            "selected_pick.source_starts_at <= clock_timestamp()",
        ):
            self.assertIn(audit_guard, body)
        self.assertGreaterEqual(body.count("return null"), 2)

    def test_meta_social_read_rpc_returns_only_the_public_pick_allowlist(self):
        body = function_body(
            META_SOCIAL_SQL,
            "public.get_meta_social_batch( requested_run_key text ) returns jsonb",
        )
        result_start = body.index("return jsonb_build_object(")
        result = body[result_start:]
        expected_fields = (
            "id", "categoria", "partido", "pick", "cuota", "confianza",
            "estado", "es_parlay", "liga", "mercado", "riesgo",
            "fecha_generacion", "fecha_evento", "horario", "tiene_valor",
            "visibility", "source", "source_event_id", "source_market_key",
            "source_selection_key", "source_observed_at", "source_starts_at",
        )

        self.assertIn("'run_id', selected_run.id", result)
        self.assertIn("'batch_id', selected_batch.id", result)
        self.assertIn("'delivery_status', selected_run.delivery_status", result)
        outer_arguments, _ = sql_call_arguments(result, "jsonb_build_object")
        public_pick_key = outer_arguments.index("'public_pick'")
        public_pick_expression = outer_arguments[public_pick_key + 1]
        public_pick_arguments, public_pick_end = sql_call_arguments(
            public_pick_expression,
            "jsonb_build_object",
        )
        self.assertEqual(public_pick_expression[public_pick_end:].strip(), "")
        self.assertEqual(len(public_pick_arguments), len(expected_fields) * 2)
        self.assertEqual(
            tuple(zip(public_pick_arguments[::2], public_pick_arguments[1::2])),
            tuple(
                (f"'{field}'", f"selected_pick.{field}")
                for field in expected_fields
            ),
        )
        self.assertNotIn("razonamiento", body)
        self.assertNotIn("to_jsonb(", body)

    def test_meta_social_write_rpc_validates_receipts_before_updating_full_ledger(self):
        text = " ".join(META_SOCIAL_SQL.read_text(encoding="utf-8").lower().split())
        signature = (
            "public.record_meta_social_delivery( requested_run_id uuid, "
            "requested_destination text, requested_success boolean, "
            "requested_receipt text default '', requested_error text default '' ) returns void"
        )
        body = function_body(META_SOCIAL_SQL, signature)

        self.assertIn(f"create or replace function {signature}", text)
        function_start = text.index(f"create or replace function {signature}")
        function_end = text.index("$$;", function_start)
        declaration = text[function_start:function_end]
        self.assertIn("language plpgsql security definer", declaration)
        self.assertIn("set search_path = public, pg_temp", declaration)
        self.assertIn("requested_run_id is null", body)
        self.assertIn("requested_success is null", body)
        self.assertIn("requested_destination not in ('facebook', 'instagram')", body)
        self.assertIn("requested_receipt is null", body)
        self.assertIn("requested_error is null", body)
        self.assertIn("requested_receipt !~ '^[a-za-z0-9_:-]{1,200}$'", body)
        self.assertIn("requested_error <> ''", body)
        self.assertIn("requested_receipt <> ''", body)
        self.assertIn(
            "requested_error not in ('token_invalid', 'delivery_failed', 'not_configured')",
            body,
        )

        first_lock = body.index("for update")
        for validation in (
            "requested_destination not in ('facebook', 'instagram')",
            "requested_receipt !~ '^[a-za-z0-9_:-]{1,200}$'",
            "requested_error not in ('token_invalid', 'delivery_failed', 'not_configured')",
        ):
            self.assertLess(body.index(validation), first_lock)
        self.assertIn("runs.id = requested_run_id", body)
        self.assertIn("runs.status in ('published', 'partial')", body)
        self.assertIn("raise exception 'unknown or unpublished scraper run %'", body)
        self.assertIn("jsonb_set(", body)
        self.assertIn("array[requested_destination]", body)
        self.assertIn("'receipt', requested_receipt", body)
        self.assertIn("'error', requested_error", body)
        for ledger_field in ("success", "receipt", "error", "updated_at"):
            self.assertIn(f"'{ledger_field}'", body)
        self.assertIn("jsonb_each(next_delivery_status)", body)
        self.assertIn("details->>'success' is distinct from 'true'", body)
        self.assertIn("then 'published' else 'partial'", body)
        self.assertNotIn("left(", body)
        self.assertNotIn("normalized_", body)
        self.assertNotIn("btrim(", body)
        self.assertNotIn("lower(", body)
        self.assertNotIn("record_scraper_delivery", body)
        self.assertNotIn("telegram", body)

    def test_meta_social_rpcs_are_service_only_and_leave_telegram_contract_unchanged(self):
        text = " ".join(META_SOCIAL_SQL.read_text(encoding="utf-8").lower().split())
        signatures = (
            "public.get_meta_social_batch(text)",
            "public.record_meta_social_delivery(uuid, text, boolean, text, text)",
        )
        for signature in signatures:
            self.assertIn(
                f"revoke all on function {signature} from public, anon, authenticated",
                text,
            )
            self.assertIn(
                f"grant execute on function {signature} to service_role",
                text,
            )
            grants = re.findall(
                rf"\bgrant\s+([^;]+?)\s+on\s+function\s+"
                rf"{function_signature_pattern(signature)}\s+to\s+([^;]+);",
                text,
            )
            self.assertEqual(grants, [("execute", "service_role")])
        self.assertNotIn("grant execute on function public.get_meta_social_batch(text) to anon", text)
        self.assertNotIn("create or replace function public.record_scraper_delivery", text)

        legacy = function_body(
            RUN_LEDGER_SQL,
            "public.record_scraper_delivery( requested_run_id uuid, requested_destination text, requested_success boolean, requested_error text default '' ) returns void",
        )
        self.assertIn("requested_destination not in ('admin', 'vip', 'free')", legacy)
        self.assertNotIn("facebook", legacy)
        self.assertNotIn("instagram", legacy)

    def test_meta_social_claim_upgrade_is_transactional_and_replaces_old_completion(self):
        text = " ".join(
            META_SOCIAL_CLAIMS_SQL.read_text(encoding="utf-8").lower().split()
        )

        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))
        self.assertIn(
            "drop function if exists public.record_meta_social_delivery(uuid, text, boolean, text, text)",
            text,
        )
        self.assertIn(
            "public.record_meta_social_delivery( requested_run_id uuid, requested_destination text, requested_success boolean, requested_receipt text, requested_error text, requested_attempt_id uuid ) returns void",
            text,
        )
        self.assertNotIn("create or replace function public.record_meta_social_delivery( requested_run_id uuid, requested_destination text, requested_success boolean, requested_receipt text default '', requested_error text default '' )", text)

    def test_meta_social_claim_is_atomic_bounded_and_reclaimable_after_expiry(self):
        signature = (
            "public.claim_meta_social_destination( requested_run_id uuid, "
            "requested_destination text, requested_attempt_id uuid, "
            "requested_lease_expires_at timestamptz ) returns boolean"
        )
        text = " ".join(
            META_SOCIAL_CLAIMS_SQL.read_text(encoding="utf-8").lower().split()
        )
        body = function_body(META_SOCIAL_CLAIMS_SQL, signature)

        declaration_start = text.index(f"create or replace function {signature}")
        declaration_end = text.index("$$;", declaration_start)
        declaration = text[declaration_start:declaration_end]
        self.assertIn("language plpgsql security definer", declaration)
        self.assertIn("set search_path = public, pg_temp", declaration)
        for validation in (
            "requested_run_id is null",
            "requested_attempt_id is null",
            "requested_destination not in ('facebook', 'instagram')",
            "requested_lease_expires_at is null",
            "requested_lease_expires_at <= checked_at",
            "requested_lease_expires_at > checked_at + interval '10 minutes'",
        ):
            self.assertIn(validation, body)
        lock = body.index("for update")
        self.assertIn("runs.id = requested_run_id", body)
        self.assertIn("runs.status in ('published', 'partial')", body)
        self.assertLess(body.index("requested_destination not in"), lock)
        self.assertIn("destination_entry->>'success' = 'true'", body)
        self.assertIn("destination_entry->>'state' = 'in_progress'", body)
        self.assertIn("(destination_entry->>'lease_expires_at')::timestamptz > checked_at", body)
        self.assertIn("return false", body)
        for field in (
            "'state', 'in_progress'",
            "'success', false",
            "'receipt', ''",
            "'error', ''",
            "'attempt_id', requested_attempt_id::text",
            "'lease_expires_at', requested_lease_expires_at",
            "'updated_at', now()",
        ):
            self.assertIn(field, body)
        self.assertIn("array[requested_destination]", body)
        self.assertIn("return true", body)

    def test_meta_social_completion_is_attempt_owned_and_success_is_terminal(self):
        signature = (
            "public.record_meta_social_delivery( requested_run_id uuid, "
            "requested_destination text, requested_success boolean, "
            "requested_receipt text, requested_error text, "
            "requested_attempt_id uuid ) returns void"
        )
        text = " ".join(
            META_SOCIAL_CLAIMS_SQL.read_text(encoding="utf-8").lower().split()
        )
        body = function_body(META_SOCIAL_CLAIMS_SQL, signature)

        declaration_start = text.index(f"create or replace function {signature}")
        declaration_end = text.index("$$;", declaration_start)
        declaration = text[declaration_start:declaration_end]
        self.assertIn("language plpgsql security definer", declaration)
        self.assertIn("set search_path = public, pg_temp", declaration)
        self.assertIn("requested_attempt_id is null", body)
        self.assertIn("for update", body)
        terminal = body.index("destination_entry->>'success' = 'true'")
        ownership = body.index("destination_entry->>'state' is distinct from 'in_progress'")
        mutation = body.index("next_delivery_status := jsonb_set")
        self.assertLess(terminal, ownership)
        self.assertLess(ownership, mutation)
        self.assertIn("return;", body[terminal:ownership])
        self.assertIn(
            "destination_entry->>'attempt_id' is distinct from requested_attempt_id::text",
            body,
        )
        self.assertIn("raise exception 'meta social claim ownership error'", body)
        self.assertIn("'state', case when requested_success then 'success' else 'failed' end", body)
        self.assertNotIn("'lease_expires_at'", body[mutation:])
        self.assertIn("jsonb_each(next_delivery_status)", body)
        self.assertIn("details->>'success' is distinct from 'true'", body)
        self.assertIn("then 'published' else 'partial'", body)
        self.assertIn("accepted by meta", text)
        self.assertIn("before the receipt", text)
        self.assertIn("duplicate", text)

    def test_meta_social_claim_rpcs_are_service_role_only(self):
        text = " ".join(
            META_SOCIAL_CLAIMS_SQL.read_text(encoding="utf-8").lower().split()
        )
        signatures = (
            "public.claim_meta_social_destination(uuid, text, uuid, timestamptz)",
            "public.record_meta_social_delivery(uuid, text, boolean, text, text, uuid)",
        )
        for signature in signatures:
            self.assertIn(
                f"revoke all on function {signature} from public, anon, authenticated",
                text,
            )
            self.assertIn(
                f"grant execute on function {signature} to service_role",
                text,
            )
            grants = re.findall(
                rf"\bgrant\s+([^;]+?)\s+on\s+function\s+"
                rf"{function_signature_pattern(signature)}\s+to\s+([^;]+);",
                text,
            )
            self.assertEqual(grants, [("execute", "service_role")])

    def test_daily_portfolio_ledger_is_private_and_revisioned(self):
        text = " ".join(
            DAILY_PORTFOLIO_SQL.read_text(encoding="utf-8").lower().split()
        )
        for table in (
            "daily_pick_portfolios",
            "daily_pick_scans",
            "daily_pick_entries",
            "daily_pick_releases",
        ):
            self.assertIn(f"create table public.{table}", text)
            self.assertIn(f"alter table public.{table} enable row level security", text)
            self.assertIn(
                f"revoke all on table public.{table} from public, anon, authenticated",
                text,
            )
        self.assertIn("portfolio_date date primary key", text)
        self.assertIn("revision integer not null default 0", text)
        self.assertIn("release_revision integer not null default 0", text)
        self.assertIn("run_key text not null unique", text)
        self.assertIn("released_revision integer", text)
        self.assertIn("physical_event_key text not null", text)
        self.assertIn("physical_event_key ~ '^physical:v1:[0-9a-f]{64}$'", text)
        self.assertIn("unique (portfolio_date, physical_event_key)", text)
        self.assertRegex(
            text,
            r"unique \(\s*portfolio_date, source, source_event_id, "
            r"source_market_key, source_selection_key\s*\)",
        )

    def test_daily_stage_is_locked_replay_safe_and_replaces_only_draft(self):
        signature = (
            "public.stage_daily_pick_portfolio( requested_run_key text, "
            "requested_portfolio_date date, requested_source_hash text, "
            "requested_picks jsonb ) returns jsonb"
        )
        body = function_body(DAILY_PORTFOLIO_SQL, signature)

        self.assertIn("pg_advisory_xact_lock", body)
        self.assertLess(body.index("pg_advisory_xact_lock"), body.index("for update"))
        self.assertIn("existing_scan.source_hash <> requested_source_hash", body)
        self.assertIn("existing_scan.portfolio_date <> requested_portfolio_date", body)
        self.assertIn("jsonb_array_length(requested_picks) not between 1 and 6", body)
        self.assertIn("released_revision is not null", body)
        self.assertIn("released_revision is null", body)
        self.assertIn("active = false", body)
        self.assertIn("row_number() over", body)
        self.assertIn("partition by", body)
        self.assertIn("physical_event_key", body)
        self.assertIn("source_event_id", body)
        self.assertIn("selected_count", body)
        self.assertIn("expected_public_count", body)
        self.assertIn("not (entry.value ? 'es_parlay')", body)
        self.assertIn("jsonb_typeof(entry.value->'es_parlay') <> 'boolean'", body)
        self.assertNotIn("coalesce((candidate.value->>'es_parlay')::boolean, false)", body)
        self.assertIn("revision = locked_portfolio.revision + 1", body)

    def test_daily_release_appends_only_delta_and_resume_is_exact(self):
        release_signature = (
            "public.release_daily_pick_portfolio( requested_run_key text, "
            "requested_portfolio_date date ) returns jsonb"
        )
        resume_signature = (
            "public.resume_daily_pick_release( requested_run_key text ) returns jsonb"
        )
        release = function_body(DAILY_PORTFOLIO_SQL, release_signature)
        resume = function_body(DAILY_PORTFOLIO_SQL, resume_signature)

        self.assertIn("pg_advisory_xact_lock", release)
        self.assertIn("public.publish_pick_batch(", release)
        self.assertIn("insert into public.scraper_runs", release)
        self.assertIn("insert into public.picks", release)
        self.assertIn("entries.released_revision is null", release)
        self.assertIn("set released_revision = next_release_revision", release)
        self.assertIn("insert into public.daily_pick_releases", release)
        self.assertIn("'picks', full_picks", release)
        self.assertIn("'delivery_picks', delivery_picks", release)
        self.assertIn("'feed_eligible', next_release_revision = 1", release)
        self.assertIn("where releases.run_id = selected_run.id", resume)
        self.assertIn("entries.released_revision = selected_release.revision", resume)
        self.assertIn("'created', false", resume)

    def test_daily_rpcs_are_service_role_only(self):
        text = " ".join(
            DAILY_PORTFOLIO_SQL.read_text(encoding="utf-8").lower().split()
        )
        signatures = (
            "public.stage_daily_pick_portfolio(text, date, text, jsonb)",
            "public.release_daily_pick_portfolio(text, date)",
            "public.resume_daily_pick_release(text)",
            "public.daily_pick_schema_status()",
        )
        for signature in signatures:
            self.assertIn(
                f"revoke all on function {signature} from public, anon, authenticated",
                text,
            )
            self.assertIn(
                f"grant execute on function {signature} to service_role",
                text,
            )

    def test_daily_schema_probe_checks_every_runtime_rpc_and_private_table(self):
        signature = "public.daily_pick_schema_status() returns boolean"
        body = function_body(DAILY_PORTFOLIO_SQL, signature)

        for rpc in (
            "stage_daily_pick_portfolio(text,date,text,jsonb)",
            "release_daily_pick_portfolio(text,date)",
            "resume_daily_pick_release(text)",
            "get_meta_social_batch(text)",
        ):
            self.assertIn(f"to_regprocedure('public.{rpc}') is not null", body)
        for table in (
            "daily_pick_portfolios",
            "daily_pick_scans",
            "daily_pick_entries",
            "daily_pick_releases",
        ):
            self.assertIn(f"to_regclass('public.{table}') is not null", body)
        self.assertIn("bool_and(classes.relrowsecurity)", body)
        self.assertIn("has_table_privilege", body)
        self.assertIn("required_privilege.name", body)
        self.assertIn("has_function_privilege", body)
        self.assertIn("procedures.prosecdef", body)
        self.assertIn("procedures.prorettype = 'jsonb'::regtype", body)
        self.assertIn("information_schema.columns", body)
        self.assertIn("unique (portfolio_date, physical_event_key)", body)
        self.assertIn("'anon'", body)
        self.assertIn("'authenticated'", body)
        self.assertIn("'service_role'", body)

    def test_meta_feed_uses_first_daily_revision_and_supports_six_pick_portfolio(self):
        signature = (
            "public.get_meta_social_batch( requested_run_key text ) returns jsonb"
        )
        body = function_body(DAILY_PORTFOLIO_SQL, signature)

        self.assertIn("daily_pick_releases", body)
        self.assertIn("selected_release.feed_eligible is false", body)
        self.assertIn("return null", body)
        self.assertIn("expected_public_count", body)
        self.assertIn("case when eligible_pick_count = 6 then 2 else 1 end", body)
        self.assertIn("order by picks.id", body)


if __name__ == "__main__":
    unittest.main()
