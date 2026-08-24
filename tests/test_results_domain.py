import unittest

from backend.results_domain import (
    EventResult,
    MarketIdentity,
    PlayerResult,
    find_matching_event,
    grade_pick,
    match_event,
    parse_market_identity,
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
        self.assertEqual(
            grade_pick("Más de 2.25 goles", self.final),
            "revision_pendiente",
        )

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

    def test_handicap_and_run_line_use_the_selected_team_margin(self):
        self.assertEqual(grade_pick("America hándicap +1.5", self.final), "ganado")
        self.assertEqual(grade_pick("Tigres run line -1.5", self.final), "perdido")
        self.assertEqual(
            grade_pick("Tigres hándicap -1.25", self.final),
            "revision_pendiente",
        )

    def test_partial_period_market_requires_period_stats(self):
        self.assertEqual(
            grade_pick("Más de 0.5 Carreras 1er Inning", self.final),
            "revision_pendiente",
        )

    def test_unit_result_uses_decimal_odds(self):
        self.assertEqual(unit_result("ganado", 1.80), 0.8)
        self.assertEqual(unit_result("perdido", 1.80), -1.0)
        self.assertEqual(unit_result("revision_pendiente", 1.80), 0.0)

    def test_market_audit_identity_is_decoded_strictly(self):
        canonical = parse_market_identity(
            'market:v1:["playdoit","totals","full_game",2.5]'
        )
        generic = parse_market_identity(
            'market:v1:["playdoit","playdoit_market:shots-1",'
            '"source_unspecified",null,"shots-1",'
            '{"scope":"player","participant_id":"p-7","team_id":null,'
            '"competitor_id":null,"offer_kind":"standard",'
            '"lineup_confirmed":true}]'
        )

        self.assertEqual(
            canonical,
            MarketIdentity("playdoit", "totals", "full_game", 2.5),
        )
        self.assertEqual(generic.market_key, "playdoit_market:shots-1")
        self.assertEqual(generic.scope, "player")
        self.assertEqual(generic.source_market_id, "shots-1")
        self.assertIsNone(parse_market_identity("market:v1:not-json"))
        self.assertIsNone(parse_market_identity('market:v1:["x","totals"]'))

    def test_canonical_market_identity_grades_selection_only_labels(self):
        h2h = MarketIdentity("playdoit", "h2h", "full_game", None)
        totals = MarketIdentity("playdoit", "totals", "full_game", 2.5)
        spread = MarketIdentity("playdoit", "spreads", "full_game", -1.5)

        self.assertEqual(
            grade_pick("Tigres", self.final, market_identity=h2h), "ganado"
        )
        self.assertEqual(
            grade_pick("Más de 2.5", self.final, market_identity=totals),
            "ganado",
        )
        self.assertEqual(
            grade_pick(
                "Tigres -1.5", self.final, market_identity=spread
            ),
            "perdido",
        )
        self.assertEqual(
            grade_pick(
                "Más de 3.5", self.final, market_identity=totals
            ),
            "revision_pendiente",
        )
        self.assertEqual(
            grade_pick(
                "Tigres -2.5", self.final, market_identity=spread
            ),
            "revision_pendiente",
        )
        away_spread = MarketIdentity(
            "playdoit", "spreads", "full_game", -1.5
        )
        self.assertEqual(
            grade_pick(
                "America +1.5", self.final, market_identity=away_spread
            ),
            "ganado",
        )

    def test_detailed_team_and_event_stats_grade_only_when_present(self):
        detailed = EventResult(
            "Fulham",
            "Chelsea",
            1,
            2,
            True,
            home_corners=3,
            away_corners=6,
            home_shots_on=2,
            away_shots_on=7,
            home_yellow_cards=1,
            away_yellow_cards=3,
        )
        event_market = MarketIdentity(
            "playdoit",
            "playdoit_market:corners-1",
            "source_unspecified",
            None,
            source_market_id="corners-1",
            scope="event",
        )
        team_market = MarketIdentity(
            "playdoit",
            "playdoit_market:shots-1",
            "source_unspecified",
            None,
            source_market_id="shots-1",
            scope="team_total",
            team_id="playdoit-chelsea",
        )

        self.assertEqual(
            grade_pick(
                "Más de 8.5",
                detailed,
                market_name="Total de tiros de esquina",
                market_identity=event_market,
            ),
            "ganado",
        )

        self.assertEqual(
            grade_pick(
                "Más de 5.5",
                detailed,
                market_name="Remates a puerta de Chelsea",
                market_identity=team_market,
            ),
            "ganado",
        )
        self.assertEqual(
            grade_pick(
                "Más de 4.5",
                detailed,
                market_name="Faltas de Chelsea",
                market_identity=team_market,
            ),
            "revision_pendiente",
        )

    def test_player_props_require_one_exact_player_and_supported_stat(self):
        detailed = EventResult(
            "Fulham",
            "Chelsea",
            1,
            2,
            True,
            players=(
                PlayerResult(
                    "Cole Palmer",
                    "Chelsea",
                    minutes=90,
                    shots_total=4,
                    shots_on=2,
                    goals=1,
                    assists=0,
                    yellow_cards=0,
                    red_cards=0,
                ),
            ),
        )
        player_market = MarketIdentity(
            "playdoit",
            "playdoit_market:shots-1",
            "source_unspecified",
            None,
            source_market_id="shots-1",
            scope="player",
            participant_id="playdoit-player-7",
        )
        did_not_play = EventResult(
            "Fulham",
            "Chelsea",
            1,
            2,
            True,
            players=(
                PlayerResult(
                    "Cole Palmer",
                    "Chelsea",
                    minutes=0,
                    shots_total=0,
                    shots_on=0,
                    goals=0,
                    assists=0,
                    yellow_cards=0,
                    red_cards=0,
                ),
            ),
        )

        self.assertEqual(
            grade_pick(
                "Más de 1.5",
                detailed,
                market_name="Remates a puerta - Cole Palmer",
                market_identity=player_market,
            ),
            "ganado",
        )
        self.assertEqual(
            grade_pick(
                "Más de 0.5",
                did_not_play,
                market_name="Remates a puerta - Cole Palmer",
                market_identity=player_market,
            ),
            "revision_pendiente",
        )
        self.assertEqual(
            grade_pick(
                "Cole Palmer",
                detailed,
                market_name="Anotará en cualquier momento",
                market_identity=player_market,
            ),
            "ganado",
        )
        self.assertEqual(
            grade_pick(
                "Cole Palmer",
                detailed,
                market_name="Primer goleador",
                market_identity=player_market,
            ),
            "revision_pendiente",
        )

        inferred_player_market = MarketIdentity(
            "playdoit",
            "playdoit_market:goals-1",
            "source_unspecified",
            None,
            source_market_id="goals-1",
            scope="source_unspecified",
            competitor_id="playdoit-player-7",
        )
        self.assertEqual(
            grade_pick(
                "Cole Palmer - 1+ goles",
                detailed,
                market_name="Goles del jugador",
                market_identity=inferred_player_market,
            ),
            "ganado",
        )

    def test_first_half_markets_never_use_full_game_statistics(self):
        detailed = EventResult(
            "Fulham",
            "Chelsea",
            1,
            2,
            True,
            home_corners=3,
            away_corners=6,
            home_first_half_score=0,
            away_first_half_score=1,
        )
        first_half = MarketIdentity(
            "playdoit",
            "playdoit_market:first-half-1",
            "first_half",
            None,
            source_market_id="first-half-1",
            scope="event",
        )
        self.assertEqual(
            grade_pick(
                "Más de 0.5",
                detailed,
                market_name="Total de goles primera mitad",
                market_identity=first_half,
            ),
            "ganado",
        )
        self.assertEqual(
            grade_pick(
                "Más de 3.5",
                detailed,
                market_name="Córners primera mitad",
                market_identity=first_half,
            ),
            "revision_pendiente",
        )

    def test_team_goal_total_never_uses_both_teams_combined_score(self):
        team_total = MarketIdentity(
            "playdoit",
            "playdoit_market:team-goals-1",
            "full_game",
            None,
            source_market_id="team-goals-1",
            scope="team_total",
            team_id="playdoit-america",
        )

        self.assertEqual(
            grade_pick(
                "Más de 1.5",
                self.final,
                market_name="Total de goles de América",
                market_identity=team_total,
            ),
            "perdido",
        )

    def test_missing_corner_stats_never_fall_back_to_goal_score(self):
        corners = MarketIdentity(
            "playdoit",
            "playdoit_market:corners-1",
            "full_game",
            None,
            source_market_id="corners-1",
            scope="event",
        )

        self.assertEqual(
            grade_pick(
                "Over 2.5",
                self.final,
                market_name="Total corners",
                market_identity=corners,
            ),
            "revision_pendiente",
        )

    def test_generic_result_and_double_chance_use_the_declared_period(self):
        first_half = MarketIdentity(
            "playdoit",
            "playdoit_market:first-half-result",
            "first_half",
            None,
            source_market_id="first-half-result",
            scope="event",
        )
        detailed = EventResult(
            "Fulham",
            "Chelsea",
            1,
            2,
            True,
            home_first_half_score=0,
            away_first_half_score=1,
        )
        double_chance = MarketIdentity(
            "playdoit",
            "playdoit_market:double-chance",
            "full_game",
            None,
            source_market_id="double-chance",
            scope="event",
        )

        self.assertEqual(
            grade_pick(
                "Chelsea",
                detailed,
                market_name="Resultado primera mitad",
                market_identity=first_half,
            ),
            "ganado",
        )
        self.assertEqual(
            grade_pick(
                "Fulham o empate",
                detailed,
                market_name="Doble oportunidad",
                market_identity=double_chance,
            ),
            "perdido",
        )
        self.assertEqual(
            grade_pick(
                "Chelsea o empate",
                detailed,
                market_name="Doble oportunidad",
                market_identity=double_chance,
            ),
            "ganado",
        )


if __name__ == "__main__":
    unittest.main()
