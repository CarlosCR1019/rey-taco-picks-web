import unittest

from backend.publishing_policy import assign_visibility, public_payload


class PublishingPolicyTests(unittest.TestCase):
    def test_only_first_single_pick_is_public(self):
        rows = [
            {"id": 1, "es_parlay": True, "pick": "Parlay"},
            {"id": 2, "es_parlay": False, "pick": "Gratis"},
            {"id": 3, "es_parlay": False, "pick": "VIP"},
        ]
        marked = assign_visibility(rows)
        self.assertEqual([row["visibility"] for row in marked], ["premium", "public", "premium"])

    def test_public_file_never_contains_premium_selections(self):
        rows = assign_visibility([
            {"id": 1, "es_parlay": False, "pick": "Gratis"},
            {"id": 2, "es_parlay": False, "pick": "VIP"},
        ])
        self.assertEqual([row["pick"] for row in public_payload(rows)], ["Gratis"])


if __name__ == "__main__":
    unittest.main()
