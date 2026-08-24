from datetime import datetime, timezone
import unittest

from backend.membership_admin import is_active_subscription, spei_subscription_record


class MembershipAdminTests(unittest.TestCase):
    def test_spei_approval_creates_a_real_30_day_subscription(self):
        now = datetime(2026, 8, 20, tzinfo=timezone.utc)
        record = spei_subscription_record("user-1", now=now)
        self.assertEqual(record["provider"], "spei")
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["current_period_end"], "2026-09-19T00:00:00+00:00")

    def test_access_requires_active_status_and_future_expiry(self):
        now = datetime(2026, 8, 20, tzinfo=timezone.utc)
        self.assertTrue(is_active_subscription({"status": "active", "current_period_end": "2026-08-21T00:00:00+00:00"}, now))
        self.assertFalse(is_active_subscription({"status": "active", "current_period_end": "2026-08-19T00:00:00+00:00"}, now))
        self.assertFalse(is_active_subscription({"status": "canceled", "current_period_end": "2026-08-21T00:00:00+00:00"}, now))


if __name__ == "__main__":
    unittest.main()
