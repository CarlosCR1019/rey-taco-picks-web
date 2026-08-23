from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from types import SimpleNamespace

import pytest

from backend.social_content import (
    SocialCaptions,
    SocialContent,
    build_fallback_captions,
)
from backend.social_copy import GroqCopyProvider, validate_social_captions


NOW = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)


def social_content(**overrides: object) -> SocialContent:
    values: dict[str, object] = {
        "pick_id": "42",
        "category": "Fútbol",
        "event": "América vs Tigres",
        "selection": "América gana",
        "odds_text": "1.80",
        "schedule": "21 de agosto, 21:00",
        "observed_at": NOW,
        "starts_at": datetime(2026, 8, 22, 3, 0, tzinfo=timezone.utc),
        "league": "Liga MX",
        "market": "Ganador del partido",
        "risk_label": "SENTINEL_PRIVATE_RISK",
        "evidence_label": "SENTINEL_PRIVATE_EVIDENCE",
        "has_value_signal": True,
        "is_demo": False,
    }
    values.update(overrides)
    return SocialContent(**values)  # type: ignore[arg-type]


class FakeCompletions:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome: object) -> None:
        self.completions = FakeCompletions(outcome)
        self.chat = SimpleNamespace(completions=self.completions)


def response_with_content(content: object) -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def valid_candidate(content: SocialContent) -> SocialCaptions:
    fallback = build_fallback_captions(content)
    return SocialCaptions(
        facebook=f"Pick público del día.\n{fallback.facebook}",
        instagram=(
            "Información deportiva basada en datos observados.\n"
            f"{fallback.instagram}"
        ),
    )


def response_for(captions: SocialCaptions) -> object:
    return response_with_content(
        json.dumps(
            {
                "facebook": captions.facebook,
                "instagram": captions.instagram,
            },
            ensure_ascii=False,
        )
    )


def provider_with_outcome(
    outcome: object,
    *,
    api_key: str = "test-api-key",
    model: str = "openai/gpt-oss-20b",
) -> tuple[GroqCopyProvider, FakeClient, list[FakeClient]]:
    client = FakeClient(outcome)
    constructions: list[FakeClient] = []

    def factory() -> object:
        constructions.append(client)
        return client

    return (
        GroqCopyProvider(
            api_key=api_key,
            model=model,
            client_factory=factory,
        ),
        client,
        constructions,
    )


@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_blank_or_missing_api_key_returns_fallback_without_client(api_key):
    constructed = 0

    def client_factory():
        nonlocal constructed
        constructed += 1
        raise AssertionError("client must not be constructed")

    content = social_content()
    provider = GroqCopyProvider(
        api_key=api_key,  # type: ignore[arg-type]
        client_factory=client_factory,
    )

    assert constructed == 0
    assert provider.captions(content) == build_fallback_captions(content)
    assert constructed == 0


@pytest.mark.parametrize(
    ("model", "expected_model"),
    [
        (None, "openai/gpt-oss-20b"),
        ("custom/test-model", "custom/test-model"),
    ],
)
def test_request_is_lazy_bounded_structured_and_public_only(model, expected_model):
    content = social_content()
    candidate = valid_candidate(content)
    client = FakeClient(response_for(candidate))
    constructions = 0

    def factory() -> object:
        nonlocal constructions
        constructions += 1
        return client

    kwargs: dict[str, object] = {
        "api_key": "SENTINEL_SECRET_API_KEY",
        "client_factory": factory,
    }
    if model is not None:
        kwargs["model"] = model
    provider = GroqCopyProvider(**kwargs)  # type: ignore[arg-type]

    assert constructions == 0
    assert provider.captions(content) == candidate
    assert constructions == 1
    assert len(client.completions.requests) == 1

    request = client.completions.requests[0]
    assert request["model"] == expected_model
    assert request["response_format"] == {"type": "json_object"}
    assert request["reasoning_effort"] == "low"
    assert request["include_reasoning"] is False
    assert "reasoning_format" not in request
    assert 0 <= request["temperature"] <= 0.3  # type: ignore[operator]
    assert 0 < request["max_completion_tokens"] <= 2000  # type: ignore[operator]
    messages = request["messages"]
    assert isinstance(messages, list)
    assert len(messages) == 3
    assert messages[-2]["role"] == "system"
    line_policy = json.loads(messages[-2]["content"])["caption_line_policy"]
    fallback = build_fallback_captions(content)
    optional_lines = [
        "Información del pick",
        "Pick público del día.",
        "Información deportiva basada en datos observados.",
        "Consulta los datos disponibles.",
    ]
    for platform in ("facebook", "instagram"):
        fallback_lines = getattr(fallback, platform).splitlines()
        assert set(line_policy[platform]["required_lines"]) == (
            set(fallback_lines) - {"Información del pick"}
        )
        assert line_policy[platform]["optional_lines"] == optional_lines
    assert messages[-1]["role"] == "user"
    public_payload = json.loads(messages[-1]["content"])
    assert public_payload == {
        "event": content.event,
        "has_value_signal": content.has_value_signal,
        "is_demo": content.is_demo,
        "league": content.league,
        "market": content.market,
        "observed_at": content.observed_at.isoformat(),
        "odds_text": content.odds_text,
        "schedule": content.schedule,
        "selection": content.selection,
        "starts_at": content.starts_at.isoformat(),
    }
    serialized_request = json.dumps(request, ensure_ascii=False)
    for forbidden in (
        "SENTINEL_SECRET_API_KEY",
        content.pick_id,
        content.category,
        content.risk_label,
        content.evidence_label,
        "source_event_id",
        "credential",
        "premium",
    ):
        assert forbidden not in serialized_request


def test_valid_exact_json_with_neutral_prose_is_accepted():
    content = social_content()
    candidate = valid_candidate(content)
    provider, _, _ = provider_with_outcome(response_for(candidate))

    assert provider.captions(content) == candidate


def test_client_is_constructed_once_and_reused_lazily():
    content = social_content()
    candidate = valid_candidate(content)
    provider, client, constructions = provider_with_outcome(response_for(candidate))

    assert constructions == []
    assert provider.captions(content) == candidate
    assert provider.captions(content) == candidate
    assert len(constructions) == 1
    assert len(client.completions.requests) == 2


def test_default_client_uses_short_timeout_and_no_retry_budget(monkeypatch):
    content = social_content()
    candidate = valid_candidate(content)
    client = FakeClient(response_for(candidate))
    constructor_calls: list[dict[str, object]] = []

    def fake_groq(**kwargs: object) -> object:
        constructor_calls.append(kwargs)
        return client

    monkeypatch.setitem(sys.modules, "groq", SimpleNamespace(Groq=fake_groq))
    provider = GroqCopyProvider(api_key="test-api-key")

    assert constructor_calls == []
    assert provider.captions(content) == candidate
    assert constructor_calls == [
        {
            "api_key": "test-api-key",
            "timeout": 10.0,
            "max_retries": 0,
        }
    ]


@pytest.mark.parametrize(
    "outcome",
    [
        response_with_content("{"),
        response_with_content(""),
        response_with_content("   "),
        SimpleNamespace(choices=[]),
        SimpleNamespace(),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())]),
        SimpleNamespace(choices=[SimpleNamespace(message=None)]),
        response_with_content("[]"),
        response_with_content('{"facebook": "only one"}'),
        response_with_content(
            '{"facebook": "one", "instagram": "two", "extra": "three"}'
        ),
        response_with_content('{"facebook": 1, "instagram": "two"}'),
        response_with_content('{"facebook": "one", "instagram": null}'),
    ],
    ids=[
        "malformed-json",
        "empty-content",
        "blank-content",
        "empty-choices",
        "missing-choices",
        "missing-content",
        "missing-message",
        "non-object-json",
        "missing-key",
        "extra-key",
        "nonstring-facebook",
        "nonstring-instagram",
    ],
)
def test_malformed_response_shapes_fall_back_as_a_whole(outcome):
    content = social_content()
    provider, _, _ = provider_with_outcome(outcome)

    assert provider.captions(content) == build_fallback_captions(content)


class FakeRateLimitError(Exception):
    pass


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("SENTINEL_EXCEPTION_MESSAGE"),
        FakeRateLimitError("SENTINEL_EXCEPTION_MESSAGE"),
        RuntimeError("SENTINEL_EXCEPTION_MESSAGE"),
    ],
)
def test_provider_call_errors_fall_back_without_sensitive_logs(error, caplog):
    content = social_content()
    provider, _, _ = provider_with_outcome(
        error,
        api_key="SENTINEL_SECRET_API_KEY",
    )

    with caplog.at_level("INFO"):
        result = provider.captions(content)

    assert result == build_fallback_captions(content)
    assert "groq_copy status=fallback" in caplog.text
    assert type(error).__name__ in caplog.text
    assert "SENTINEL_EXCEPTION_MESSAGE" not in caplog.text
    assert "SENTINEL_SECRET_API_KEY" not in caplog.text


def test_client_construction_error_falls_back_without_exception_message(caplog):
    content = social_content()

    def broken_factory():
        raise TimeoutError("SENTINEL_FACTORY_MESSAGE")

    provider = GroqCopyProvider(
        api_key="SENTINEL_SECRET_API_KEY",
        client_factory=broken_factory,
    )

    with caplog.at_level("INFO"):
        result = provider.captions(content)

    assert result == build_fallback_captions(content)
    assert "exception=TimeoutError" in caplog.text
    assert "SENTINEL_FACTORY_MESSAGE" not in caplog.text
    assert "SENTINEL_SECRET_API_KEY" not in caplog.text


def test_raw_malformed_response_is_never_logged(caplog):
    content = social_content()
    raw_response = "SENTINEL_RAW_PROVIDER_RESPONSE"
    provider, _, _ = provider_with_outcome(response_with_content(raw_response))

    with caplog.at_level("INFO"):
        assert provider.captions(content) == build_fallback_captions(content)

    assert raw_response not in caplog.text


def replace_platform(
    captions: SocialCaptions,
    platform: str,
    value: str,
) -> SocialCaptions:
    values = {
        "facebook": captions.facebook,
        "instagram": captions.instagram,
    }
    values[platform] = value
    return SocialCaptions(**values)


def with_platform_suffix(
    content: SocialContent,
    suffix: str,
    *,
    platform: str = "facebook",
) -> SocialCaptions:
    candidate = valid_candidate(content)
    original = getattr(candidate, platform)
    return replace_platform(candidate, platform, f"{original}\n{suffix}")


def caption_result(content: SocialContent, candidate: SocialCaptions) -> SocialCaptions:
    provider, _, _ = provider_with_outcome(response_for(candidate))
    return provider.captions(content)


def test_public_caption_validator_accepts_fallback_and_audited_decoration():
    content = social_content()
    fallback = build_fallback_captions(content)
    decorated = valid_candidate(content)

    assert validate_social_captions(fallback, content) == fallback
    assert validate_social_captions(decorated, content) == decorated


def test_public_caption_validator_normalizes_the_complete_result():
    content = social_content()
    fallback = build_fallback_captions(content)
    candidate = SocialCaptions(
        facebook=f"Ｐｉｃｋ público del día.\n{fallback.facebook}",
        instagram=f"Ｃｏｎｓｕｌｔａ los datos disponibles.\n{fallback.instagram}",
    )

    result = validate_social_captions(candidate, content)

    assert result.facebook.startswith("Pick público del día.\n")
    assert result.instagram.startswith("Consulta los datos disponibles.\n")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda candidate, content: replace_platform(
            candidate,
            "facebook",
            candidate.facebook.replace(content.event, "", 1),
        ),
        lambda candidate, _content: replace_platform(
            candidate,
            "instagram",
            candidate.instagram.replace("18+ · Apuesta con responsabilidad", "", 1),
        ),
        lambda candidate, _content: replace_platform(
            candidate,
            "facebook",
            f"{candidate.facebook}\nResultado garantizado.",
        ),
        lambda candidate, _content: replace_platform(
            candidate,
            "instagram",
            f"{candidate.instagram}\nDato neutral 999.",
        ),
        lambda candidate, _content: replace_platform(
            candidate,
            "facebook",
            f"{candidate.facebook}\nApuesta ahora.",
        ),
        lambda candidate, _content: replace_platform(
            candidate,
            "facebook",
            f"{candidate.facebook} #ReyTacoPicks",
        ),
        lambda candidate, _content: replace_platform(
            candidate,
            "instagram",
            candidate.instagram.replace(
                "#ApuestasResponsables",
                "#EtiquetaInventada",
            ),
        ),
    ],
    ids=(
        "missing-fact",
        "missing-footer",
        "guarantee",
        "invented-number",
        "unsafe-cta",
        "excessive-hashtag",
        "wrong-hashtag",
    ),
)
def test_public_caption_validator_rejects_unsafe_provider_packages(mutate):
    content = social_content()
    unsafe = mutate(valid_candidate(content), content)

    with pytest.raises(ValueError):
        validate_social_captions(unsafe, content)


@pytest.mark.parametrize("candidate", [None, {}, ("facebook", "instagram")])
def test_public_caption_validator_requires_exact_caption_package(candidate):
    with pytest.raises(ValueError, match="SocialCaptions"):
        validate_social_captions(candidate, social_content())


def required_fragments(content: SocialContent) -> tuple[tuple[str, str], ...]:
    fallback = build_fallback_captions(content)
    observation_line = next(
        line for line in fallback.facebook.splitlines() if line.startswith("Observado:")
    )
    return (
        ("event", content.event),
        ("selection", content.selection),
        ("odds-line", f"Momio observado: {content.odds_text}"),
        ("observation-line", observation_line),
        ("domain", "reytacopicks.com"),
        ("adult-label", "18+"),
        ("responsibility", "Apuesta con responsabilidad"),
    )


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
@pytest.mark.parametrize("fragment_index", range(7))
def test_missing_each_required_fact_or_footer_falls_back_wholly(
    platform,
    fragment_index,
):
    content = social_content()
    candidate = valid_candidate(content)
    _, fragment = required_fragments(content)[fragment_index]
    changed = getattr(candidate, platform).replace(fragment, "", 1)
    unsafe_candidate = replace_platform(candidate, platform, changed)

    result = caption_result(content, unsafe_candidate)

    assert result == build_fallback_captions(content)
    assert result != unsafe_candidate


@pytest.mark.parametrize(
    ("canonical_line", "altered_line"),
    [
        ("América vs Tigres", "Evento descartado: América vs Tigres"),
        ("Selección: América gana", "Selección descartada: América gana"),
        (
            "Consulta: reytacopicks.com",
            "No consultes: reytacopicks.com",
        ),
        (
            "18+ · Apuesta con responsabilidad",
            "18+ · No Apuesta con responsabilidad",
        ),
    ],
)
def test_required_facts_and_footer_reject_altered_context(
    canonical_line,
    altered_line,
):
    content = social_content()
    candidate = valid_candidate(content)
    changed = candidate.facebook.replace(canonical_line, altered_line, 1)
    unsafe_candidate = replace_platform(candidate, "facebook", changed)

    assert caption_result(content, unsafe_candidate) == build_fallback_captions(
        content
    )


def test_required_canonical_lines_use_stripped_line_equality():
    content = social_content()
    candidate = valid_candidate(content)
    observation_line = required_fragments(content)[3][1]
    canonical_lines = {
        content.event,
        f"Selección: {content.selection}",
        f"Momio observado: {content.odds_text}",
        observation_line,
        "Consulta: reytacopicks.com",
        "18+ · Apuesta con responsabilidad",
        "Señal de valor comparada",
    }
    padded_candidate = SocialCaptions(
        facebook="\n".join(
            f"  {line}  " if line in canonical_lines else line
            for line in candidate.facebook.splitlines()
        ),
        instagram="\n".join(
            f"  {line}  " if line in canonical_lines else line
            for line in candidate.instagram.splitlines()
        ),
    )

    assert caption_result(content, padded_candidate) == padded_candidate


@pytest.mark.parametrize(
    "contradictory_line",
    [
        "Selección descartada: América gana",
        "Evento cancelado: América vs Tigres",
        "No consultes reytacopicks.com",
        "18+ · No Apuesta con responsabilidad",
    ],
)
def test_protected_facts_are_rejected_outside_canonical_context(
    contradictory_line,
):
    content = social_content()
    candidate = with_platform_suffix(content, contradictory_line)

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "unsafe_suffix",
    [
        "Dato neutral 999.",
        "Aviso 18%.",
        "Aviso 18％.",
    ],
    ids=["invented-number", "percentage", "fullwidth-percentage"],
)
def test_unapproved_numbers_and_percentages_fall_back(unsafe_suffix):
    content = social_content()
    candidate = with_platform_suffix(content, unsafe_suffix)

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "textual_percentage",
    ["18 por ciento", "18 porcentaje", "18 percent"],
)
def test_textual_percentage_families_fall_back(textual_percentage):
    content = social_content()
    candidate = with_platform_suffix(content, textual_percentage)

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "unsafe_claim",
    [
        "Es un resultado seguro.",
        "Es una apuesta segura.",
        "Resultado garantizado.",
        "We guarantee this result.",
        "Guaranteed outcome.",
        "Alta probabilidad.",
        "High probability.",
        "High likelihood.",
        "Likely outcome.",
        "High chance to win.",
        "Este pick va a ganar.",
        "You are a winner.",
        "América podría ganar.",
        "Maybe América wins.",
        "Tu victoria está cerca.",
        "Este pick gana.",
        "Nuestra apuesta de hoy.",
        "Apuesta todo.",
        "Alternativa sin riesgo.",
        "Contenido patrocinado por un equipo.",
        "Sponsor oficial de la casa de apuestas.",
        "Promesa de victoria.",
    ],
)
def test_each_unsafe_semantic_family_falls_back(unsafe_claim):
    content = social_content()
    candidate = with_platform_suffix(content, unsafe_claim)

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "unsafe_variant",
    [
        "América triunfará.",
        "El equipo vencerá.",
        "Juega ya.",
        "Oferta exclusiva.",
        "América se impondrá.",
        "Participa ahora.",
        "Código promocional.",
        "Rendimiento 18٪.",
        "Rendimiento 18 pct.",
    ],
)
def test_adversarial_win_cta_promo_and_percentage_variants_fall_back(
    unsafe_variant,
):
    content = social_content()
    candidate = with_platform_suffix(content, unsafe_variant)

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "unsafe_semantic_variant",
    [
        "Resultado asegurado.",
        "Certeza absoluta.",
        "América superará a Tigres.",
        "Acceso gratis.",
        "Colaboración pagada.",
        "Apuesta.",
        "Rendimiento 18 per cent.",
        "Rendimiento 18 puntos porcentuales.",
    ],
)
def test_broad_guarantee_win_promo_sponsor_cta_percentage_variants_fall_back(
    unsafe_semantic_variant,
):
    content = social_content()
    candidate = with_platform_suffix(content, unsafe_semantic_variant)

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize("unicode_number", ["Ⅸ", "⑱", "１８", "١٨"])
def test_every_non_ascii_unicode_number_category_falls_back(unicode_number):
    content = social_content()
    candidate = with_platform_suffix(content, f"Nivel {unicode_number}.")

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "unsafe_betting_promotion",
    [
        "Apuesta ahora.",
        "Apuesta ya.",
        "Haz tu apuesta.",
        "Bet now.",
        "Promoción especial.",
    ],
)
def test_betting_cta_and_promotion_variants_fall_back(
    unsafe_betting_promotion,
):
    content = social_content()
    candidate = with_platform_suffix(content, unsafe_betting_promotion)

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "percent_sign",
    ["%", "\u066a", "\ufe6a", "\uff05", "\U000e0025"],
)
def test_every_unicode_percent_sign_falls_back(percent_sign):
    content = social_content()
    candidate = with_platform_suffix(content, f"Rendimiento 18{percent_sign}.")

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_excess_known_hashtags_fall_back(platform):
    content = social_content()
    candidate = valid_candidate(content)
    changed = f"{getattr(candidate, platform)} #ReyTacoPicks"
    unsafe_candidate = replace_platform(candidate, platform, changed)

    assert caption_result(content, unsafe_candidate) == build_fallback_captions(
        content
    )


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_unknown_hashtag_within_count_limit_falls_back(platform):
    content = social_content()
    candidate = valid_candidate(content)
    changed = getattr(candidate, platform).replace(
        "#ApuestasResponsables",
        "#EtiquetaInventada",
    )
    unsafe_candidate = replace_platform(candidate, platform, changed)

    assert caption_result(content, unsafe_candidate) == build_fallback_captions(
        content
    )


@pytest.mark.parametrize(
    "unauthorized_url",
    [
        "https://reytacopicks.com",
        "https://example.com",
        "www.example.com",
        "example.net",
        "mailto:ventas@reytacopicks.com",
        "custom:value",
        "ssh://host",
        "irc:canal",
        "ventas@reytacopicks.com",
        "ejemplo.рф",
        "ejemplo。com",
    ],
)
def test_urls_other_than_the_plain_required_domain_fall_back(unauthorized_url):
    content = social_content()
    candidate = with_platform_suffix(content, unauthorized_url)

    assert caption_result(content, candidate) == build_fallback_captions(content)


def test_plain_required_domain_and_decimal_odds_are_not_misclassified_as_urls():
    content = social_content()
    candidate = valid_candidate(content)

    result = caption_result(content, candidate)

    assert result == candidate
    assert "reytacopicks.com" in result.facebook
    assert "1.80" in result.instagram


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_demo_requires_exact_label_in_each_caption(platform):
    content = social_content(is_demo=True, has_value_signal=False)
    candidate = valid_candidate(content)
    changed = getattr(candidate, platform).replace("DEMO NO VIGENTE", "", 1)
    unsafe_candidate = replace_platform(candidate, platform, changed)

    assert caption_result(content, unsafe_candidate) == build_fallback_captions(
        content
    )


def test_demo_label_leaking_into_production_falls_back():
    content = social_content(is_demo=False)
    candidate = with_platform_suffix(content, "DEMO NO VIGENTE")

    assert caption_result(content, candidate) == build_fallback_captions(content)


def test_demo_with_value_flag_accepts_canonical_demo_copy_without_value_line():
    content = social_content(is_demo=True, has_value_signal=True)
    candidate = valid_candidate(content)

    assert "DEMO NO VIGENTE" in candidate.facebook
    assert "Señal de valor comparada" not in candidate.instagram
    assert caption_result(content, candidate) == candidate


def test_demo_with_value_flag_rejects_value_line_in_either_caption():
    content = social_content(is_demo=True, has_value_signal=True)
    candidate = valid_candidate(content)
    leaked_value_candidate = SocialCaptions(
        facebook=f"{candidate.facebook}\nSeñal de valor comparada",
        instagram=f"{candidate.instagram}\nSeñal de valor comparada",
    )

    assert caption_result(
        content,
        leaked_value_candidate,
    ) == build_fallback_captions(content)


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_true_value_signal_requires_exact_label_in_each_caption(platform):
    content = social_content(has_value_signal=True)
    candidate = valid_candidate(content)
    changed = getattr(candidate, platform).replace(
        "Señal de valor comparada",
        "",
        1,
    )
    unsafe_candidate = replace_platform(candidate, platform, changed)

    assert caption_result(content, unsafe_candidate) == build_fallback_captions(
        content
    )


def test_value_signal_label_on_false_content_falls_back():
    content = social_content(has_value_signal=False)
    candidate = with_platform_suffix(content, "Señal de valor comparada")

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "control",
    ["\x00", "\t", "\r", "\u200b", "\u2060"],
    ids=["nul", "tab", "carriage-return", "zero-width-space", "word-joiner"],
)
def test_unicode_control_or_format_character_falls_back(control):
    content = social_content()
    candidate = with_platform_suffix(content, f"texto{control}oculto")

    assert caption_result(content, candidate) == build_fallback_captions(content)


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_caption_over_2000_code_points_falls_back(platform):
    content = social_content()
    candidate = valid_candidate(content)
    changed = f"{'x' * 2001}\n{getattr(candidate, platform)}"
    unsafe_candidate = replace_platform(candidate, platform, changed)

    assert caption_result(content, unsafe_candidate) == build_fallback_captions(
        content
    )


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_blank_caption_value_falls_back(platform):
    content = social_content()
    candidate = replace_platform(valid_candidate(content), platform, "   ")

    assert caption_result(content, candidate) == build_fallback_captions(content)


def test_nfkc_normalized_safe_candidate_is_returned_normalized():
    content = social_content()
    fallback = build_fallback_captions(content)
    compatibility_candidate = SocialCaptions(
        facebook=f"Ｐｉｃｋ público del día.\n{fallback.facebook}",
        instagram=f"Ｃｏｎｓｕｌｔａ los datos disponibles.\n{fallback.instagram}",
    )

    result = caption_result(content, compatibility_candidate)

    assert result.facebook.startswith("Pick público del día.\n")
    assert result.instagram.startswith("Consulta los datos disponibles.\n")


def test_allowed_neutral_and_required_lines_may_be_reordered():
    content = social_content()
    fallback = build_fallback_captions(content)
    candidate = SocialCaptions(
        facebook="\n".join(
            ["Consulta los datos disponibles.", *reversed(fallback.facebook.splitlines())]
        ),
        instagram="\n".join(
            ["Pick público del día.", *reversed(fallback.instagram.splitlines())]
        ),
    )

    assert caption_result(content, candidate) == candidate


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_platform_fixed_hashtag_line_is_required(platform):
    content = social_content()
    candidate = valid_candidate(content)
    changed = "\n".join(
        line for line in getattr(candidate, platform).splitlines() if not line.startswith("#")
    )
    incomplete = replace_platform(candidate, platform, changed)

    assert caption_result(content, incomplete) == build_fallback_captions(content)


@pytest.mark.parametrize(
    "unknown_line",
    ["Comentario neutral.", "Información del pick."],
)
def test_unknown_harmless_looking_line_falls_back(unknown_line):
    content = social_content()
    candidate = with_platform_suffix(content, unknown_line)

    assert caption_result(content, candidate) == build_fallback_captions(content)


def test_duplicate_json_keys_fall_back():
    content = social_content()
    candidate = valid_candidate(content)
    duplicate_json = (
        "{"
        f'"facebook":{json.dumps(candidate.facebook, ensure_ascii=False)},'
        f'"facebook":{json.dumps(candidate.facebook, ensure_ascii=False)},'
        f'"instagram":{json.dumps(candidate.instagram, ensure_ascii=False)}'
        "}"
    )
    provider, _, _ = provider_with_outcome(response_with_content(duplicate_json))

    assert provider.captions(content) == build_fallback_captions(content)


def test_validation_failure_logs_neither_candidate_nor_api_key(caplog):
    content = social_content()
    candidate_sentinel = "SENTINEL_UNSAFE_CANDIDATE seguro"
    candidate = with_platform_suffix(content, candidate_sentinel)
    provider, _, _ = provider_with_outcome(
        response_for(candidate),
        api_key="SENTINEL_SECRET_API_KEY",
    )

    with caplog.at_level("INFO"):
        result = provider.captions(content)

    assert result == build_fallback_captions(content)
    assert candidate_sentinel not in caplog.text
    assert "SENTINEL_SECRET_API_KEY" not in caplog.text


def test_one_invalid_caption_discards_both_and_repeated_calls_are_deterministic():
    content = social_content()
    original_content = social_content()
    original_fallback = build_fallback_captions(content)
    candidate = valid_candidate(content)
    unsafe_candidate = replace_platform(
        candidate,
        "facebook",
        f"{candidate.facebook}\nDato 999",
    )
    provider, client, constructions = provider_with_outcome(
        response_for(unsafe_candidate)
    )

    first = provider.captions(content)
    second = provider.captions(content)

    assert first == original_fallback
    assert second == original_fallback
    assert content == original_content
    assert build_fallback_captions(content) == original_fallback
    assert len(constructions) == 1
    assert len(client.completions.requests) == 2
