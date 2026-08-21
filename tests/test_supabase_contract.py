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
        self.assertIn("estado in ('ganado', 'perdido', 'void', 'revision_pendiente')", text)
        self.assertNotIn("using (true)", text)

    def test_premium_access_requires_an_unexpired_subscription(self):
        text = SQL.read_text(encoding="utf-8").lower()
        self.assertIn("status in ('active', 'trialing')", text)
        self.assertIn("current_period_end > now()", text)


if __name__ == "__main__":
    unittest.main()
