import unittest

from backend.results_domain import (
    EventResult,
    find_matching_event,
    grade_pick,
    match_event,
    unit_result,
)


class ResultDomainTests(unittest.TestCase):
    def setUp(self):
        self.final = EventResult(
            home="Tigres UANL",
            away="Club America",
            home_score=2,
            away_score=1,
            completed=True,
            source="espn",
            source_id="match-1",
        )

    def test_both_teams_must_match(self):
        self.assertTrue(match_event("Tigres vs America", self.final))
        self.assertFalse(match_event("Tigres vs Monterrey", self.final))

    def test_single_shared_generic_token_is_not_a_match(self):
        event = EventResult("Club Leon", "Monterrey", 1, 0, True)
        self.assertFalse(match_event("Club America vs Monterrey", event))

    def test_incomplete_events_are_not_selected(self):
        live = EventResult("Tigres UANL", "Club America", 2, 1, False)
        self.assertIsNone(find_matching_event("Tigres vs America", [live]))
        self.assertEqual(grade_pick("Más de 2.5 goles", live), "pendiente")

    def test_totals_are_graded_from_final_score(self):
        self.assertEqual(grade_pick("Más de 2.5 goles", self.final), "ganado")
        self.assertEqual(grade_pick("Menos de 2.5 goles", self.final), "perdido")

    def test_moneyline_and_both_teams_to_score(self):
        self.assertEqual(grade_pick("Tigres gana ML", self.final), "ganado")
        self.assertEqual(grade_pick("America gana directo", self.final), "perdido")
        self.assertEqual(grade_pick("Ambos equipos anotan: Sí", self.final), "ganado")

    def test_corners_without_stats_require_review(self):
        self.assertEqual(
            grade_pick("Más de 8.5 tiros de esquina", self.final),
            "revision_pendiente",
        )

    def test_corners_with_stats_are_graded(self):
        result = EventResult("Tigres", "America", 2, 1, True, 5, 4)
        self.assertEqual(grade_pick("Más de 8.5 córners", result), "ganado")

    def test_unknown_market_never_defaults_to_loss_or_win(self):
        self.assertEqual(grade_pick("Jugador tendrá dos remates", self.final), "revision_pendiente")

    def test_unit_result_uses_decimal_odds(self):
        self.assertEqual(unit_result("ganado", 1.80), 0.8)
        self.assertEqual(unit_result("perdido", 1.80), -1.0)
        self.assertEqual(unit_result("revision_pendiente", 1.80), 0.0)


if __name__ == "__main__":
    unittest.main()
