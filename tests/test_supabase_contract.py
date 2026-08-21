from pathlib import Path
import unittest


SQL = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260820220000_secure_membership.sql"
)


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


if __name__ == "__main__":
    unittest.main()
