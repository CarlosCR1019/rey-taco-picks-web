from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal
import re

import pytest

from backend.social_content import (
    SOCIAL_PICK_FIELDS,
    SocialCaptions,
    SocialContent,
    build_fallback_captions,
    content_from_public_pick,
    demo_social_content,
)


NOW = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
CANONICAL_BATCH_ID = "11111111-1111-4111-8111-111111111111"
PROMOTIONAL_SUBJECT_CLAIMS = (
    "This pick is sure to win",
    "This pick will be a winner",
    "This pick wins",
    "The bet wins",
    "This selection is a winner",
    "Our pick wins",
    "His bet for today",
    "Their selection wins",
    "The selection for today",
    "Este pick gana",
    "Este pick será ganador",
    "Nuestro pronóstico de hoy",
    "Su apuesta de hoy",
)
PROBABILITY_LEXICON_CLAIMS = (
    "High likelihood of winning",
    "Likely to win",
    "This pick is expected to win",
    "Expected outcome",
    "Sure result",
    "Surely a winner",
    "Certain result",
    "Certainly a winner",
    "Probably wins",
    "Probable que gane",
    "Probablemente gana",
    "Resultado esperado",
    "Resultado seguro",
    "Seguramente gana",
    "Resultado cierto",
    "Ciertamente gana",
    "Con certeza",
)
CHANCE_OF_WIN_CLAIMS = (
    "High chance to win",
    "High chance of winning",
    "Chance of winning",
    "Very high chance of winning",
    "Several chances to win",
    "Muchas chances de ganar",
    "Alta posibilidad de ganar",
    "Varias posibilidades de ganar",
    "Buena chance de ganar",
)
FUTURE_MODAL_WIN_CLAIMS = (
    "This pick will win",
    "This pick is going to win",
    "These bets are going to win",
    "This pick should win",
    "This bet must win",
    "This selection is bound to win",
    "America will definitely win",
    "America will be a winner",
    "America is going to be a winner",
    "Este pick va a ganar",
    "Este pick ganará",
    "Este pick debería ganar",
    "América será ganadora",
)
ENGLISH_POSSIBILITY_MODAL_CLAIMS = (
    "America may win",
    "America might win",
    "America could win",
    "America can win",
    "America may be a winner",
    "America might still be the winner",
    "America could end up winning",
)
POSSIBILITY_OF_WIN_CLAIMS = (
    "Good possibility of winning",
    "Possibility to win",
    "Several possibilities of winning",
    "Possibilities to win",
)
SPANISH_POSSIBILITY_CLAIMS = (
    "América podría ganar",
    "América podría volver a ganar",
    "Ellas podrían ganar",
    "América puede ganar",
    "América puede todavía ganar",
    "Los equipos pueden ganar",
    "Posiblemente gane América",
    "Probablemente ganará América",
)
RECIPIENT_WINNER_CLAIMS = (
    "You are a winner",
    "You really are a winner",
    "We are winners",
    "I am a winner",
    "They are the winners",
    "Eres ganador",
    "Tú eres una ganadora",
    "Tú realmente eres una ganadora",
    "Somos ganadores",
    "Nosotras somos ganadoras",
    "Ustedes son los ganadores",
)
SAFE_NON_WINNING_MODAL_PHRASES = (
    "America may draw",
    "America might play tomorrow",
    "America could qualify",
    "America can score",
    "América puede empatar",
    "América podría jugar mañana",
)
EXPECTED_FIELDS = frozenset(
    {
        "id",
        "categoria",
        "partido",
        "pick",
        "cuota",
        "confianza",
        "estado",
        "es_parlay",
        "liga",
        "mercado",
        "riesgo",
        "fecha_generacion",
        "fecha_evento",
        "horario",
        "tiene_valor",
        "visibility",
        "source",
        "source_event_id",
        "source_market_key",
        "source_selection_key",
        "source_observed_at",
        "source_starts_at",
    }
)


def valid_row(**overrides):
    row = {
        "id": 1780000000000000,
        "categoria": "  Fútbol   mexicano ",
        "partido": "  América   vs   Tigres  ",
        "pick": "  América   gana  ",
        "cuota": 1.8,
        "confianza": "65% respaldo de datos",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "  Liga   MX  ",
        "mercado": "  Ganador   del partido  ",
        "riesgo": "  Riesgo   medio  ",
        "fecha_generacion": "2026-08-21",
        "fecha_evento": "2026-08-21",
        "horario": "  Hoy   20:00 hrs  ",
        "tiene_valor": True,
        "visibility": "public",
        "source": "  the-odds-api  ",
        "source_event_id": "  event-public-178  ",
        "source_market_key": "  h2h|full_time|  ",
        "source_selection_key": "  home  ",
        "source_observed_at": "2026-08-21T12:00:00-06:00",
        "source_starts_at": "2026-08-22T02:00:00Z",
    }
    row.update(overrides)
    return row


def test_public_field_allowlist_is_exact_and_immutable():
    assert SOCIAL_PICK_FIELDS == EXPECTED_FIELDS
    assert isinstance(SOCIAL_PICK_FIELDS, frozenset)


def test_builds_normalized_immutable_content_from_one_current_public_row():
    content = content_from_public_pick(valid_row(), reference_at=NOW)

    assert content == SocialContent(
        pick_id="1780000000000000",
        category="Fútbol mexicano",
        event="América vs Tigres",
        selection="América gana",
        odds_text="1.80",
        schedule="Hoy 20:00 hrs",
        observed_at=datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc),
        starts_at=datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc),
        league="Liga MX",
        market="Ganador del partido",
        risk_label="Riesgo medio",
        evidence_label="Respaldo de datos: 65%",
        has_value_signal=True,
        is_demo=False,
    )
    assert content.object_key(batch_id=CANONICAL_BATCH_ID) == (
        "daily/11111111-1111-4111-8111-111111111111/"
        "1780000000000000.jpg"
    )
    with pytest.raises(FrozenInstanceError):
        content.event = "Cambio"  # type: ignore[misc]


@pytest.mark.parametrize("reference_at", [None, datetime(2026, 8, 21, 20, 0)])
def test_rejects_reference_without_timezone(reference_at):
    with pytest.raises(ValueError, match="reference_at"):
        content_from_public_pick(valid_row(), reference_at=reference_at)  # type: ignore[arg-type]


@pytest.mark.parametrize("row", [None, "row", 7, [], [valid_row(), valid_row()]])
def test_rejects_non_mapping_empty_or_multiple_row_inputs(row):
    with pytest.raises(ValueError, match="mapping"):
        content_from_public_pick(row, reference_at=NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize("missing_field", sorted(EXPECTED_FIELDS))
def test_rejects_each_missing_required_field(missing_field):
    row = valid_row()
    row.pop(missing_field)

    with pytest.raises(ValueError, match="exact public pick fields"):
        content_from_public_pick(row, reference_at=NOW)


def test_rejects_an_extra_field():
    with pytest.raises(ValueError, match="exact public pick fields"):
        content_from_public_pick(
            {**valid_row(), "unexpected": "must fail closed"},
            reference_at=NOW,
        )


def test_rejects_sensitive_reasoning_instead_of_ignoring_it():
    with pytest.raises(ValueError, match="exact public pick fields"):
        content_from_public_pick(
            {**valid_row(), "razonamiento": "private model reasoning"},
            reference_at=NOW,
        )


def test_rejects_a_premium_row():
    with pytest.raises(ValueError, match="visibility"):
        content_from_public_pick(
            valid_row(visibility="premium"),
            reference_at=NOW,
        )


@pytest.mark.parametrize("es_parlay", [True, None, 0, "false"])
def test_rejects_parlay_and_non_boolean_false_values(es_parlay):
    with pytest.raises(ValueError, match="es_parlay"):
        content_from_public_pick(valid_row(es_parlay=es_parlay), reference_at=NOW)


@pytest.mark.parametrize("estado", ["ganado", "Pendiente", " pendiente ", None])
def test_rejects_nonpending_state(estado):
    with pytest.raises(ValueError, match="estado"):
        content_from_public_pick(valid_row(estado=estado), reference_at=NOW)


@pytest.mark.parametrize("tiene_valor", [None, 0, 1, "true"])
def test_rejects_non_boolean_value_signal(tiene_valor):
    with pytest.raises(ValueError, match="tiene_valor"):
        content_from_public_pick(
            valid_row(tiene_valor=tiene_valor),
            reference_at=NOW,
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("categoria", "  "),
        ("horario", None),
        ("liga", "\t"),
        ("mercado", 7),
        ("riesgo", "\n"),
        ("source", ""),
        ("source_event_id", None),
        ("source_market_key", "  "),
        ("source_selection_key", 0),
    ],
)
def test_rejects_incomplete_normalized_public_and_audit_text(field, invalid_value):
    with pytest.raises(ValueError, match=field):
        content_from_public_pick(
            valid_row(**{field: invalid_value}),
            reference_at=NOW,
        )


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("source", 100),
        ("source_event_id", 500),
        ("source_market_key", 1000),
        ("source_selection_key", 500),
    ],
)
def test_rejects_oversized_source_audit_identity(field, limit):
    with pytest.raises(ValueError, match=field):
        content_from_public_pick(
            valid_row(**{field: "x" * (limit + 1)}),
            reference_at=NOW,
        )


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("source", 100),
        ("source_event_id", 500),
        ("source_market_key", 1000),
        ("source_selection_key", 500),
    ],
)
def test_audit_bounds_apply_before_internal_whitespace_is_collapsed(field, limit):
    whitespace_inflated = "x" + (" " * limit) + "y"

    with pytest.raises(ValueError, match=field):
        content_from_public_pick(
            valid_row(**{field: whitespace_inflated}),
            reference_at=NOW,
        )


@pytest.mark.parametrize("field", ["partido", "pick"])
@pytest.mark.parametrize("blank_value", ["", "  \t\n", None, 7])
def test_rejects_blank_or_non_string_event_and_selection(field, blank_value):
    with pytest.raises(ValueError, match=field):
        content_from_public_pick(
            valid_row(**{field: blank_value}),
            reference_at=NOW,
        )


def test_rejects_an_observation_after_the_reference():
    with pytest.raises(ValueError, match="source_observed_at"):
        content_from_public_pick(
            valid_row(source_observed_at="2026-08-21T20:00:01Z"),
            reference_at=NOW,
        )


def test_rejects_an_expired_event_at_the_reference():
    with pytest.raises(ValueError, match="source_starts_at"):
        content_from_public_pick(
            valid_row(source_starts_at="2026-08-21T20:00:00Z"),
            reference_at=NOW,
        )


def test_rejects_an_event_not_after_its_observation():
    with pytest.raises(ValueError, match="source_starts_at"):
        content_from_public_pick(
            valid_row(
                source_observed_at="2026-08-21T18:00:00Z",
                source_starts_at="2026-08-21T18:00:00Z",
            ),
            reference_at=NOW,
        )


@pytest.mark.parametrize(
    ("field", "timestamp"),
    [
        ("source_observed_at", "2026-08-21T18:00:00"),
        ("source_starts_at", "2026-08-22T02:00:00"),
        ("source_observed_at", "2026-08-21 18:00:00Z"),
        ("source_starts_at", "not-an-iso-timestamp"),
        ("source_observed_at", None),
    ],
)
def test_rejects_naive_or_invalid_source_timestamps(field, timestamp):
    with pytest.raises(ValueError, match=field):
        content_from_public_pick(
            valid_row(**{field: timestamp}),
            reference_at=NOW,
        )


@pytest.mark.parametrize(
    "odds",
    [
        True,
        False,
        None,
        "",
        "not-a-number",
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        "NaN",
        "Infinity",
        1,
        "1.00",
        0,
        -1,
    ],
)
def test_rejects_invalid_nonfinite_or_nonpositive_decimal_odds(odds):
    with pytest.raises(ValueError, match="cuota"):
        content_from_public_pick(valid_row(cuota=odds), reference_at=NOW)


@pytest.mark.parametrize(
    ("odds", "expected"),
    [
        (1.8, "1.80"),
        ("2", "2.00"),
        (Decimal("2.345"), "2.35"),
    ],
)
def test_formats_decimal_odds_to_exactly_two_places(odds, expected):
    assert (
        content_from_public_pick(valid_row(cuota=odds), reference_at=NOW).odds_text
        == expected
    )


@pytest.mark.parametrize("odds", ["1.0001", Decimal("1.004")])
def test_rejects_odds_that_round_to_even_money(odds):
    with pytest.raises(ValueError, match="cuota"):
        content_from_public_pick(valid_row(cuota=odds), reference_at=NOW)


def test_accepts_the_first_half_up_odds_boundary_above_even_money():
    content = content_from_public_pick(
        valid_row(cuota=Decimal("1.005")),
        reference_at=NOW,
    )

    assert content.odds_text == "1.01"


@pytest.mark.parametrize(
    "pick_id",
    [True, False, None, "", "  ", "+1", "-1", "1/2", "../1", "1.0", "abc", 1.0],
)
def test_rejects_non_ascii_digit_pick_ids(pick_id):
    with pytest.raises(ValueError, match="id"):
        content_from_public_pick(valid_row(id=pick_id), reference_at=NOW)


@pytest.mark.parametrize(
    "batch_id",
    [
        "11111111-1111-4111-8111-11111111111A",
        "{11111111-1111-4111-8111-111111111111}",
        "11111111111141118111111111111111",
        "../11111111-1111-4111-8111-111111111111",
        "11111111-1111-4111-8111-111111111111/..",
        "not-a-uuid",
        "",
    ],
)
def test_object_key_rejects_uppercase_noncanonical_or_traversal_batch_ids(batch_id):
    content = content_from_public_pick(valid_row(), reference_at=NOW)

    with pytest.raises(ValueError, match="batch_id"):
        content.object_key(batch_id=batch_id)


@pytest.mark.parametrize("pick_id", ["../1", "1/2", "-1", "", "١٢٣", 123])
def test_object_key_revalidates_digits_only_pick_id(pick_id):
    content = replace(
        content_from_public_pick(valid_row(), reference_at=NOW),
        pick_id=pick_id,
    )

    with pytest.raises(ValueError, match="pick_id"):
        content.object_key(batch_id=CANONICAL_BATCH_ID)


def test_fallback_captions_include_only_required_factual_persisted_copy():
    content = content_from_public_pick(valid_row(), reference_at=NOW)

    captions = build_fallback_captions(content)

    assert isinstance(captions, SocialCaptions)
    for caption in (captions.facebook, captions.instagram):
        assert "América vs Tigres" in caption
        assert "América gana" in caption
        assert "Momio observado: 1.80" in caption
        assert "Observado: 21 de agosto de 2026, 12:00" in caption
        assert "hora de Ciudad de México" in caption
        assert "reytacopicks.com" in caption
        assert "18+" in caption
        assert "Apuesta con responsabilidad" in caption
        assert "Señal de valor comparada" in caption
        assert "DEMO NO VIGENTE" not in caption
        assert "%" not in caption
        lowered = caption.casefold()
        for unsafe in (
            "probabilidad",
            "seguro",
            "segura",
            "garantizado",
            "sin riesgo",
            "patrocinado",
            "sponsor",
        ):
            assert unsafe not in lowered

    assert len(re.findall(r"(?<!\w)#[\wÁ-ú]+", captions.facebook)) <= 2
    assert len(re.findall(r"(?<!\w)#[\wÁ-ú]+", captions.instagram)) <= 4
    assert captions.facebook.splitlines()[-1] == (
        "#ReyTacoPicks #ApuestasResponsables"
    )
    assert captions.instagram.splitlines()[-1] == (
        "#ReyTacoPicks #ApuestasResponsables "
        "#PronósticosDeportivos #Deportes"
    )
    assert re.findall(r"(?<!\w)#[\wÁ-ú]+", captions.facebook) == [
        "#ReyTacoPicks",
        "#ApuestasResponsables",
    ]
    assert re.findall(r"(?<!\w)#[\wÁ-ú]+", captions.instagram) == [
        "#ReyTacoPicks",
        "#ApuestasResponsables",
        "#PronósticosDeportivos",
        "#Deportes",
    ]
    with pytest.raises(FrozenInstanceError):
        captions.facebook = "Cambio"  # type: ignore[misc]


def assert_persisted_claim_is_rejected(predictive_claim):
    with pytest.raises(ValueError, match="pick"):
        content_from_public_pick(
            valid_row(pick=predictive_claim),
            reference_at=NOW,
        )


def assert_manual_claim_is_rejected(predictive_claim):
    content = replace(
        content_from_public_pick(valid_row(), reference_at=NOW),
        selection=predictive_claim,
    )

    with pytest.raises(ValueError, match="selection"):
        build_fallback_captions(content)


@pytest.mark.parametrize("claim", PROMOTIONAL_SUBJECT_CLAIMS)
def test_persisted_rows_reject_promotional_content_subjects(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", PROMOTIONAL_SUBJECT_CLAIMS)
def test_manual_content_rejects_promotional_content_subjects(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", PROBABILITY_LEXICON_CLAIMS)
def test_persisted_rows_reject_probability_lexicon(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", PROBABILITY_LEXICON_CLAIMS)
def test_manual_content_rejects_probability_lexicon(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", CHANCE_OF_WIN_CLAIMS)
def test_persisted_rows_reject_chance_of_win_structures(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", CHANCE_OF_WIN_CLAIMS)
def test_manual_content_rejects_chance_of_win_structures(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", FUTURE_MODAL_WIN_CLAIMS)
def test_persisted_rows_reject_future_modal_win_structures(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", FUTURE_MODAL_WIN_CLAIMS)
def test_manual_content_rejects_future_modal_win_structures(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", ENGLISH_POSSIBILITY_MODAL_CLAIMS)
def test_persisted_rows_reject_english_possibility_modals(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", ENGLISH_POSSIBILITY_MODAL_CLAIMS)
def test_manual_content_rejects_english_possibility_modals(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", POSSIBILITY_OF_WIN_CLAIMS)
def test_persisted_rows_reject_possibility_of_win_structures(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", POSSIBILITY_OF_WIN_CLAIMS)
def test_manual_content_rejects_possibility_of_win_structures(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", SPANISH_POSSIBILITY_CLAIMS)
def test_persisted_rows_reject_spanish_possibility_claims(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", SPANISH_POSSIBILITY_CLAIMS)
def test_manual_content_rejects_spanish_possibility_claims(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", RECIPIENT_WINNER_CLAIMS)
def test_persisted_rows_reject_recipient_winner_claims(claim):
    assert_persisted_claim_is_rejected(claim)


@pytest.mark.parametrize("claim", RECIPIENT_WINNER_CLAIMS)
def test_manual_content_rejects_recipient_winner_claims(claim):
    assert_manual_claim_is_rejected(claim)


@pytest.mark.parametrize("safe_phrase", SAFE_NON_WINNING_MODAL_PHRASES)
def test_accepts_modals_without_a_win_or_winner_outcome(safe_phrase):
    content = content_from_public_pick(
        valid_row(pick=safe_phrase),
        reference_at=NOW,
    )

    assert content.selection == safe_phrase
    assert safe_phrase in build_fallback_captions(content).instagram


@pytest.mark.parametrize(
    "safe_selection",
    [
        "América gana",
        "Victoria de América",
        "America wins",
        "America to win",
        "Pick: America wins",
        "Double chance: America or draw",
    ],
)
def test_accepts_neutral_standalone_market_selections(safe_selection):
    content = content_from_public_pick(
        valid_row(pick=safe_selection),
        reference_at=NOW,
    )

    assert content.selection == safe_selection
    assert safe_selection in build_fallback_captions(content).facebook


@pytest.mark.parametrize(
    ("field", "unsafe_fact"),
    [
        ("partido", "América con 99% probabilidad"),
        ("pick", "Éxito en 80 por ciento"),
        ("pick", "Ventaja de 80 porcentaje"),
        ("pick", "80 percent chance"),
        ("pick", "Éxito 80％"),
        ("pick", "Selección segura"),
        ("pick", "Resultado garantizado"),
        ("pick", "Victoria con garantía"),
        ("pick", "Guaranteed winner"),
        ("pick", "Guarantee of victory"),
        ("pick", "Alternativa sin riesgo"),
        ("partido", "Evento patrocinado"),
        ("pick", "Promesa de victoria"),
        ("partido", "DEMO NO VIGENTE"),
        ("pick", "América gana #Extra #Etiquetas #NoFijas"),
    ],
)
def test_rejects_persisted_facts_that_would_make_captions_unsafe(
    field, unsafe_fact
):
    with pytest.raises(ValueError, match=field):
        content_from_public_pick(
            valid_row(**{field: unsafe_fact}),
            reference_at=NOW,
        )


def test_caption_builder_revalidates_manually_constructed_caption_facts():
    content = replace(
        content_from_public_pick(valid_row(), reference_at=NOW),
        selection="Apuesta segura con 99% probabilidad #Extra",
    )

    with pytest.raises(ValueError, match="selection"):
        build_fallback_captions(content)


@pytest.mark.parametrize(
    "unsafe_selection",
    ["80 por ciento", "80 porcentaje", "80 percent chance", "80％"],
)
def test_caption_builder_rejects_textual_and_unicode_percentages(
    unsafe_selection,
):
    content = replace(
        content_from_public_pick(valid_row(), reference_at=NOW),
        selection=unsafe_selection,
    )

    with pytest.raises(ValueError, match="selection"):
        build_fallback_captions(content)


@pytest.mark.parametrize(
    "unsafe_odds_text",
    ["99% probabilidad #Extra", "segura", "1.00", "1.8", "NaN", "Infinity"],
)
def test_caption_builder_revalidates_manually_constructed_odds_text(
    unsafe_odds_text,
):
    content = replace(
        content_from_public_pick(valid_row(), reference_at=NOW),
        odds_text=unsafe_odds_text,
    )

    with pytest.raises(ValueError, match="odds_text"):
        build_fallback_captions(content)


def test_value_signal_copy_appears_only_for_true_persisted_content():
    without_value = content_from_public_pick(
        valid_row(tiene_valor=False),
        reference_at=NOW,
    )
    demo_with_value = replace(
        demo_social_content(reference_at=NOW),
        has_value_signal=True,
    )

    assert "Señal de valor comparada" not in build_fallback_captions(
        without_value
    ).facebook
    assert "Señal de valor comparada" not in build_fallback_captions(
        demo_with_value
    ).instagram


def test_demo_content_is_fictional_future_and_visibly_labeled():
    demo = demo_social_content(reference_at=NOW)

    assert demo.is_demo is True
    assert demo.observed_at <= NOW
    assert demo.starts_at > NOW
    assert "ejemplo" in f"{demo.event} {demo.selection}".casefold()
    assert "sin vigencia" in demo.schedule.casefold()
    captions = build_fallback_captions(demo)
    assert "DEMO NO VIGENTE" in captions.facebook
    assert "DEMO NO VIGENTE" in captions.instagram


def test_demo_rejects_a_naive_reference():
    with pytest.raises(ValueError, match="reference_at"):
        demo_social_content(reference_at=datetime(2026, 8, 21, 20, 0))


def test_fallback_captions_and_demo_fixture_are_deterministic():
    content = content_from_public_pick(valid_row(), reference_at=NOW)

    assert build_fallback_captions(content) == build_fallback_captions(content)
    assert demo_social_content(reference_at=NOW) == demo_social_content(
        reference_at=NOW
    )
