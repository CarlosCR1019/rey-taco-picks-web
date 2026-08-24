from pathlib import Path
import unittest

from backend.publishing_policy import (
    assign_visibility,
    event_labels_share_date,
    expected_public_pick_count,
    public_payload,
    scheduled_event_date,
)


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

    def test_public_count_is_one_through_five_and_two_for_six(self):
        self.assertEqual(expected_public_pick_count(0), 0)
        for total in range(1, 6):
            self.assertEqual(expected_public_pick_count(total), 1)
            rows = [
                {
                    "id": index,
                    "es_parlay": False,
                    "source": "playdoit",
                    "source_event_id": f"event-{index}",
                }
                for index in range(total)
            ]
            self.assertEqual(
                sum(
                    row["visibility"] == "public"
                    for row in assign_visibility(rows)
                ),
                1,
            )
        self.assertEqual(expected_public_pick_count(6), 2)

    def test_six_picks_expose_two_non_parlays_from_distinct_matches(self):
        rows = [
            {
                "id": index,
                "es_parlay": index == 1,
                "pick": f"Pick {index}",
                "source": "playdoit",
                "source_event_id": (
                    "event-a" if index in {1, 2, 3} else f"event-{index}"
                ),
            }
            for index in range(1, 7)
        ]

        marked = assign_visibility(rows)
        public = [row for row in marked if row["visibility"] == "public"]

        self.assertEqual([row["id"] for row in public], [2, 4])
        self.assertTrue(all(row["es_parlay"] is False for row in public))
        self.assertEqual(
            len({(row["source"], row["source_event_id"]) for row in public}),
            2,
        )
        self.assertTrue(
            all(
                row["visibility"] == "premium"
                for row in marked
                if row["id"] not in {2, 4}
            )
        )

    def test_assign_visibility_does_not_mutate_input(self):
        rows = [
            {
                "id": 1,
                "es_parlay": False,
                "source": "playdoit",
                "source_event_id": "event-a",
            }
        ]

        assign_visibility(rows)

        self.assertNotIn("visibility", rows[0])

    def test_free_telegram_channel_never_queues_the_premium_batch(self):
        scraper = (Path(__file__).resolve().parents[1] / "backend" / "scraper.py").read_text(encoding="utf-8")
        self.assertNotIn("enumerate(picks[1:]", scraper)
        self.assertIn("free_picks = public_payload(picks)", scraper)

    def test_publisher_retires_previous_public_pending_pick_before_insert(self):
        scraper = (Path(__file__).resolve().parents[1] / "backend" / "scraper.py").read_text(encoding="utf-8")
        self.assertIn('eq("visibility", "public")', scraper)
        self.assertIn('{"visibility": "premium"}', scraper)

    def test_tomorrow_label_persists_the_actual_event_date(self):
        self.assertEqual(scheduled_event_date("Mañana 20:00", "2026-08-20"), "2026-08-21")
        self.assertEqual(scheduled_event_date("Hoy 18:00", "2026-08-20"), "2026-08-20")

    def test_playdoit_day_month_label_persists_the_actual_event_date(self):
        self.assertEqual(scheduled_event_date("21/08 • 19:00", "2026-08-20"), "2026-08-21")
        self.assertEqual(scheduled_event_date("01/01 • 12:00", "2026-12-31"), "2027-01-01")

    def test_parlay_legs_must_share_the_same_mexico_calendar_date(self):
        self.assertTrue(event_labels_share_date(["21/08 • 19:00", "21/08 • 21:00"], "2026-08-20"))
        self.assertFalse(event_labels_share_date(["Hoy 19:00", "Mañana 21:00"], "2026-08-20"))

    def test_scraper_accepts_only_catalog_ids_and_has_no_generated_fallback(self):
        scraper = (Path(__file__).resolve().parents[1] / "backend" / "scraper.py").read_text(encoding="utf-8")
        self.assertIn("validate_ai_ranking", scraper)
        self.assertIn('"candidate_id"', scraper)
        self.assertNotIn("raw_picks", scraper)
        self.assertNotIn("picks_fallback", scraper)
        self.assertNotIn("event_labels_share_date(parlay_horarios", scraper)
        self.assertNotIn('"categoria": "Parlay Seguro"', scraper)


if __name__ == "__main__":
    unittest.main()
