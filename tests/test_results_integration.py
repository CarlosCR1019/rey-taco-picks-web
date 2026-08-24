import unittest

from backend.verificar_resultados import event_date_cdmx, espn_scoreboard_url, grade_pending_pick, grade_pending_pick_from_results


class ResultsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "home_team": "Tigres UANL",
            "away_team": "Club America",
            "completed": True,
            "source": "espn",
            "source_id": "event-1",
            "event_date": "2026-08-23",
            "scores": [
                {"name": "Tigres UANL", "score": 2},
                {"name": "Club America", "score": 1},
            ],
        }

    def test_incomplete_result_is_not_graded(self):
        result = {**self.result, "completed": False}
        self.assertIsNone(
            grade_pending_pick(
                {"partido": "Tigres vs America", "pick": "Más de 2.5 goles", "cuota": 1.8},
                result,
            )
        )

    def test_corner_result_without_corner_stats_requires_review(self):
        decision = grade_pending_pick(
            {"partido": "Tigres vs America", "pick": "Más de 8.5 córners", "cuota": 1.8},
            self.result,
        )
        self.assertEqual(decision["estado"], "revision_pendiente")
        self.assertEqual(decision["resultado_unidades"], 0.0)

    def test_completed_total_is_graded_with_audit_data(self):
        decision = grade_pending_pick(
            {"partido": "Tigres vs America", "pick": "Más de 2.5 goles", "cuota": 1.8},
            self.result,
        )
        self.assertEqual(decision["estado"], "ganado")
        self.assertEqual(decision["resultado_unidades"], 0.8)
        self.assertEqual(decision["resultado_marcador"], "2-1")
        self.assertEqual(decision["visibility"], "public")

    def test_duplicate_team_events_are_not_graded_without_a_unique_date(self):
        duplicate = {**self.result, "source_id": "event-2"}
        decision = grade_pending_pick_from_results(
            {"partido": "Tigres vs America", "pick": "Más de 2.5 goles", "cuota": 1.8},
            [self.result, duplicate],
        )
        self.assertIsNone(decision)

    def test_pick_date_selects_the_matching_rematch(self):
        old = {**self.result, "source_id": "old", "event_date": "2026-08-19"}
        current = {**self.result, "source_id": "current", "event_date": "2026-08-20"}
        decision = grade_pending_pick_from_results(
            {"partido": "Tigres vs America", "pick": "Más de 2.5 goles", "cuota": 1.8, "fecha_generacion": "2026-08-20"},
            [old, current],
        )
        self.assertEqual(decision["resultado_evento_id"], "current")

    def test_scoreboard_request_includes_the_pick_date(self):
        self.assertEqual(
            espn_scoreboard_url("https://example.test/scoreboard", "2026-08-19"),
            "https://example.test/scoreboard?dates=20260819",
        )

    def test_utc_event_date_is_compared_in_mexico_city_time(self):
        self.assertEqual(event_date_cdmx("2026-08-21T01:30:00Z"), "2026-08-20")

    def test_parlay_waits_for_every_leg_then_grades_the_combination(self):
        second = {
            **self.result,
            "home_team": "Monterrey",
            "away_team": "Pumas UNAM",
            "source_id": "event-2",
            "scores": [{"score": 1}, {"score": 1}],
        }
        pick = {
            "partido": "Tigres vs America + Monterrey vs Pumas",
            "pick": "America hándicap +1.5 & Menos de 2.5 goles",
            "cuota": 2.4,
            "es_parlay": True,
        }
        self.assertIsNone(grade_pending_pick_from_results(pick, [self.result]))
        decision = grade_pending_pick_from_results(pick, [self.result, second])
        self.assertEqual(decision["estado"], "ganado")
        self.assertEqual(decision["resultado_evento_id"], "event-1,event-2")

    def test_persisted_market_identity_grades_canonical_label(self):
        pick = {
            "partido": "Tigres vs America",
            "pick": "Tigres",
            "mercado": "Resultado final",
            "source_market_key": (
                'market:v1:["playdoit","h2h","full_game",null]'
            ),
            "cuota": 1.8,
        }

        decision = grade_pending_pick(pick, self.result)

        self.assertEqual(decision["estado"], "ganado")

    def test_persisted_deep_market_uses_detailed_api_statistics(self):
        detailed = {
            **self.result,
            "home_team": "Fulham",
            "away_team": "Chelsea",
            "scores": [{"score": 1}, {"score": 2}],
            "home_corners": 3,
            "away_corners": 6,
        }
        pick = {
            "partido": "Fulham vs Chelsea",
            "pick": "Más de 8.5",
            "mercado": "Total de tiros de esquina",
            "source_market_key": (
                'market:v1:["playdoit","playdoit_market:corners-1",'
                '"source_unspecified",null,"corners-1",'
                '{"scope":"event","participant_id":null,"team_id":null,'
                '"competitor_id":null,"offer_kind":"standard",'
                '"lineup_confirmed":false}]'
            ),
            "cuota": 1.85,
        }

        decision = grade_pending_pick(pick, detailed)

        self.assertEqual(decision["estado"], "ganado")

    def test_detailed_api_result_is_preferred_over_matching_score_fallback(self):
        espn = {
            **self.result,
            "home_team": "Fulham",
            "away_team": "Chelsea",
            "source_id": "espn-1",
            "event_date": "2026-08-23",
            "scores": [{"score": 1}, {"score": 2}],
        }
        detailed = {
            **espn,
            "source": "api_football",
            "source_id": "991",
            "home_corners": 3,
            "away_corners": 6,
        }
        pick = {
            "partido": "Fulham vs Chelsea",
            "fecha_evento": "2026-08-23",
            "pick": "Más de 8.5",
            "mercado": "Total de tiros de esquina",
            "source_market_key": (
                'market:v1:["playdoit","playdoit_market:corners-1",'
                '"source_unspecified",null,"corners-1",'
                '{"scope":"event","participant_id":null,"team_id":null,'
                '"competitor_id":null,"offer_kind":"standard",'
                '"lineup_confirmed":false}]'
            ),
            "cuota": 1.85,
        }

        decision = grade_pending_pick_from_results(pick, [espn, detailed])

        self.assertEqual(decision["estado"], "ganado")
        self.assertEqual(decision["resultado_fuente"], "api_football")
        self.assertEqual(decision["resultado_evento_id"], "991")

    def test_multiple_detailed_matches_never_fall_back_to_espn(self):
        espn = {**self.result, "source_id": "espn-1"}
        first = {
            **self.result,
            "source": "api_football",
            "source_id": "api-1",
        }
        second = {
            **first,
            "source_id": "api-2",
        }
        pick = {
            "partido": "Tigres vs America",
            "fecha_evento": "2026-08-23",
            "pick": "Tigres",
            "mercado": "Resultado final",
            "source_market_key": (
                'market:v1:["playdoit","h2h","full_game",null]'
            ),
            "cuota": 1.8,
        }

        self.assertIsNone(
            grade_pending_pick_from_results(pick, [espn, first, second])
        )

    def test_malformed_final_result_never_becomes_an_invented_zero_zero(self):
        malformed_rows = [
            {**self.result, "scores": [{}, {}]},
            {**self.result, "completed": "false"},
            {**self.result, "source_id": ""},
            {**self.result, "event_date": ""},
        ]
        pick = {
            "partido": "Tigres vs America",
            "pick": "Empate",
            "mercado": "Resultado final",
            "source_market_key": (
                'market:v1:["playdoit","h2h","full_game",null]'
            ),
            "cuota": 2.0,
        }

        for malformed in malformed_rows:
            with self.subTest(malformed=malformed):
                self.assertIsNone(grade_pending_pick(pick, malformed))

    def test_invalid_decimal_odds_prevent_settlement(self):
        for odds in (None, "bad", 0.5, float("nan"), float("inf")):
            with self.subTest(odds=odds):
                self.assertIsNone(grade_pending_pick(
                    {
                        "partido": "Tigres vs America",
                        "pick": "Tigres gana",
                        "cuota": odds,
                    },
                    self.result,
                ))


if __name__ == "__main__":
    unittest.main()
