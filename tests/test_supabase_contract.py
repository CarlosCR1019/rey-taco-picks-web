from pathlib import Path
import unittest


SQL = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260820220000_secure_membership.sql"
)
RUN_LEDGER_SQL = SQL.parent / "20260820233000_scraper_run_ledger.sql"


class SupabaseContractTests(unittest.TestCase):
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
        self.assertLess(lock_position, hash_check_position)
        self.assertLess(hash_check_position, replay_position)
        self.assertIn("claimed_run.status in ('published', 'partial')", text)
        self.assertIn("'run_id', claimed_run.id", text)
        self.assertIn(
            "'batch_id', ( select id from public.pick_batches where run_id = claimed_run.id )",
            text,
        )
        self.assertIn("where run_id = claimed_run.id", text)
        self.assertIn("'delivery_status', claimed_run.delivery_status", text)
        self.assertIn("'created', false", text)

    def test_publishing_rpc_replaces_the_active_pending_lifecycle(self):
        text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
        self.assertIn("update public.picks set visibility = 'premium'", text)
        self.assertIn("where estado = 'pendiente' and visibility = 'public'", text)
        self.assertIn("update public.pick_batches set active = false where active", text)
        self.assertIn("update public.picks set active = false where active", text)
        self.assertIn("jsonb_populate_record(null::public.picks", text)
        self.assertIn("set status = 'published', finished_at = now()", text)
        self.assertIn("'created', true", text)

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
        self.assertIn("create policy picks_admin_insert", text)
        self.assertIn("create policy picks_admin_update", text)
        self.assertIn("create policy picks_admin_delete", text)

    def test_scraper_run_ledger_migration_is_transactional(self):
        text = RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().strip()
        self.assertTrue(text.startswith("begin;"))
        self.assertTrue(text.endswith("commit;"))


if __name__ == "__main__":
    unittest.main()
