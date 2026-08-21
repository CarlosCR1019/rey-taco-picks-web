import unittest

from backend.verificar_resultados import grade_pending_pick


class ResultsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "home_team": "Tigres UANL",
            "away_team": "Club America",
            "completed": True,
            "source": "espn",
            "source_id": "event-1",
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


if __name__ == "__main__":
    unittest.main()
