"""Optional AI social copy behind deterministic, fail-closed captions."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import re
from typing import Protocol
from unicodedata import category as unicode_category
from unicodedata import name as unicode_name
from unicodedata import normalize as normalize_unicode

from backend.social_content import (
    SocialCaptions,
    SocialContent,
    build_fallback_captions,
)


_LOGGER = logging.getLogger(__name__)
_OPTIONAL_NEUTRAL_LINES = (
    "Información del pick",
    "Pick público del día.",
    "Información deportiva basada en datos observados.",
    "Consulta los datos disponibles.",
)
_SYSTEM_PROMPT = (
    "Redacta dos captions informativos en español usando únicamente los datos "
    "públicos entregados. La política estructurada siguiente es autoritativa: "
    "incluye cada required_line literalmente y usa sólo optional_lines como "
    "texto adicional. No emitas otros datos o líneas. Responde sólo con un "
    "objeto JSON con las claves facebook e instagram."
)
_MAX_CAPTION_CODEPOINTS = 2000
_NUMERIC_TOKEN = re.compile(r"\d+(?:[.,:/-]\d+)*")
_HASHTAG = re.compile(r"#[^\s#]+")
_URI_SCHEME = re.compile(
    r"(?<!\w)[a-z][a-z0-9+.-]*:(?=[^\s])",
    re.IGNORECASE,
)
_DOMAIN = re.compile(
    r"(?<![\w-])(?:[^\W_][\w-]*\.)+[^\W\d_][\w-]*(?![\w-])",
    re.IGNORECASE,
)
_EMAIL = re.compile(
    r"(?<![\w.+-])[\w.+-]+@(?:[^\W_][\w-]*\.)+"
    r"[^\W\d_][\w-]*(?![\w-])",
    re.IGNORECASE,
)
_IDNA_DOT_TRANSLATION: dict[int, str] = {
    ord("。"): ".",
    ord("．"): ".",
    ord("｡"): ".",
}
_PROMOTIONAL_CONTENT_SUBJECT = re.compile(
    r"\b(?:this|that|these|those|the|my|your|his|her|its|our|their|"
    r"este|esta|estos|estas|el|la|los|las|mi|mis|tu|tus|su|sus|"
    r"nuestro|nuestra|nuestros|nuestras)\s+"
    r"(?:picks?|bets?|selections?|apuestas?|selecci[oó]n|selecciones|"
    r"pron[oó]sticos?)\b"
)
_UNSAFE_DYNAMIC_PATTERNS = (
    re.compile(
        r"\b(?:por\s+ciento|puntos?\s+porcentuales?|porcentajes?|"
        r"per\s+cent|percent(?:age)?s?|pct)\b"
    ),
    re.compile(
        r"\b(?:a?segur\w*|sure|surely|certain|certainly|certainty|"
        r"certez\w*|ciert[oa]s?)\b"
    ),
    re.compile(r"\b(?:garant\w*|guarant\w*)\b"),
    re.compile(
        r"\b(?:probabilidad(?:es)?|probable(?:s|mente)?|probabilit\w*|"
        r"likely|likelihood|chance|chances|posibilidad(?:es)?|"
        r"posible(?:s|mente)?|possibly|maybe|perhaps|quiz[aá]s?|"
        r"esperad[oa]s?|expected)\b"
    ),
    re.compile(r"\bsin\s+riesgo\b"),
    re.compile(
        r"\b(?:patrocin\w*|sponsor\w*|publicidad|advertis\w*|"
        r"colaboraci\w*(?:\s+\w+){0,2}\s+pagad\w*|paid\s+collabor\w*)\b"
    ),
    re.compile(
        r"\b(?:socio\s+oficial|official\s+partner|presentado\s+por|"
        r"powered\s+by|cortes[ií]a\s+de)\b"
    ),
    re.compile(r"\b(?:promes\w*|promet\w*|promis\w*)\b"),
    re.compile(
        r"\b(?:promoc\w*|imperdible|ofertas?|exclusiv[oa]s?|"
        r"bonos?|descuentos?|gratis|gratuit\w*|free|regalos?|premios?)\b"
    ),
    re.compile(
        r"\b(?:(?:apuesta|arriesga|juega|participa|[uú]nete|reg[ií]strate)"
        r"\s+(?:todo|ya|ahora)|"
        r"bet\s+it\s+all|stake\s+everything|all[- ]in|"
        r"haz\s+tu\s+apuesta|bet\s+now|place\s+your\s+bet)\b"
    ),
    re.compile(r"\b(?:apuest\w*|bets?|wagers?)\b"),
    re.compile(
        r"\b(?:triunf\w*|venc\w*|derrot\w*|victor\w*|impon\w*|"
        r"super\w*|prevalec\w*|domin\w*|conquist\w*|coron\w*)\b"
    ),
    re.compile(r"\b(?:ganar\w*|gan(?:a|e|o|ó)\w*)\b"),
)
_WIN_OUTCOME_TOKENS = frozenset(
    {
        "win",
        "wins",
        "winning",
        "won",
        "winner",
        "winners",
        "victory",
        "victories",
        "ganar",
        "gano",
        "gana",
        "ganas",
        "gane",
        "ganes",
        "ganan",
        "ganamos",
        "ganando",
        "ganaré",
        "ganarás",
        "ganará",
        "ganaremos",
        "ganaréis",
        "ganarán",
        "ganador",
        "ganadora",
        "ganadores",
        "ganadoras",
        "victoria",
        "victorias",
    }
)
_WORD_TOKEN = re.compile(r"\w+")


class CaptionProvider(Protocol):
    def captions(self, content: SocialContent) -> SocialCaptions: ...


class GroqCopyProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "openai/gpt-oss-20b",
        client_factory: Callable[[], object] | None = None,
    ) -> None:
        self._api_key = api_key if isinstance(api_key, str) else ""
        self._model = model
        if client_factory is None:

            def default_client_factory() -> object:
                from groq import Groq

                return Groq(api_key=self._api_key)

            self._client_factory = default_client_factory
        else:
            self._client_factory = client_factory
        self._client: object | None = None

    def captions(self, content: SocialContent) -> SocialCaptions:
        fallback = build_fallback_captions(content)
        if not self._api_key.strip():
            return fallback
        try:
            if self._client is None:
                self._client = self._client_factory()
            response = self._client.chat.completions.create(  # type: ignore[attr-defined]
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "system",
                        "content": json.dumps(
                            _caption_line_policy(content, fallback),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            _public_payload(content),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                reasoning_effort="low",
                temperature=0.2,
                max_completion_tokens=1200,
            )
            return _parse_captions(response, content=content, fallback=fallback)
        except Exception as exc:
            exception_class = type(exc).__name__
            _LOGGER.info(
                "groq_copy status=fallback exception=%s",
                exception_class,
            )
            return fallback


def _public_payload(content: SocialContent) -> dict[str, object]:
    return {
        "event": content.event,
        "selection": content.selection,
        "odds_text": content.odds_text,
        "schedule": content.schedule,
        "observed_at": content.observed_at.isoformat(),
        "starts_at": content.starts_at.isoformat(),
        "league": content.league,
        "market": content.market,
        "has_value_signal": content.has_value_signal,
        "is_demo": content.is_demo,
    }


def _conditional_caption_lines(content: SocialContent) -> tuple[str, ...]:
    return tuple(
        label
        for enabled, label in (
            (content.is_demo, "DEMO NO VIGENTE"),
            (content.has_value_signal, "Señal de valor comparada"),
        )
        if enabled
    )


def _required_caption_lines(
    content: SocialContent,
    fallback: SocialCaptions,
    *,
    platform: str,
) -> tuple[str, ...]:
    normalized_fallback = normalize_unicode("NFKC", getattr(fallback, platform))
    fallback_lines = normalized_fallback.splitlines()
    observation_line = next(
        line for line in fallback_lines if line.startswith("Observado:")
    )
    hashtag_line = next(line for line in fallback_lines if line.startswith("#"))
    return (
        normalize_unicode("NFKC", content.event),
        f"Selección: {normalize_unicode('NFKC', content.selection)}",
        f"Momio observado: {normalize_unicode('NFKC', content.odds_text)}",
        observation_line,
        "Consulta: reytacopicks.com",
        "18+ · Apuesta con responsabilidad",
        hashtag_line,
    ) + _conditional_caption_lines(content)


def _caption_line_policy(
    content: SocialContent,
    fallback: SocialCaptions,
) -> dict[str, object]:
    return {
        "caption_line_policy": {
            platform: {
                "required_lines": list(
                    _required_caption_lines(
                        content,
                        fallback,
                        platform=platform,
                    )
                ),
                "optional_lines": list(_OPTIONAL_NEUTRAL_LINES),
            }
            for platform in ("facebook", "instagram")
        }
    }


def _parse_captions(
    response: object,
    *,
    content: SocialContent,
    fallback: SocialCaptions,
) -> SocialCaptions:
    raw_content = response.choices[0].message.content  # type: ignore[attr-defined]
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise ValueError("provider content must be nonblank JSON")
    parsed = json.loads(raw_content, object_pairs_hook=_unique_json_object)
    if not isinstance(parsed, dict) or set(parsed) != {"facebook", "instagram"}:
        raise ValueError("provider JSON must contain exact caption keys")
    facebook = parsed["facebook"]
    instagram = parsed["instagram"]
    if not isinstance(facebook, str) or not isinstance(instagram, str):
        raise ValueError("provider captions must be strings")
    return SocialCaptions(
        facebook=_validate_caption(
            facebook,
            platform="facebook",
            content=content,
            fallback=fallback,
        ),
        instagram=_validate_caption(
            instagram,
            platform="instagram",
            content=content,
            fallback=fallback,
        ),
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("provider JSON contains a duplicate key")
        parsed[key] = value
    return parsed


def _validate_caption(
    candidate: str,
    *,
    platform: str,
    content: SocialContent,
    fallback: SocialCaptions,
) -> str:
    _validate_unicode_numbers(candidate)
    normalized = normalize_unicode("NFKC", candidate)
    if not normalized.strip() or len(normalized) > _MAX_CAPTION_CODEPOINTS:
        raise ValueError("provider caption is blank or oversized")
    if any(
        unicode_category(character) in {"Cc", "Cf"} and character != "\n"
        for character in normalized
    ):
        raise ValueError("provider caption contains a control character")

    normalized_fallback = normalize_unicode("NFKC", getattr(fallback, platform))
    required_lines = _required_caption_lines(
        content,
        fallback,
        platform=platform,
    )
    conditional_lines = _conditional_caption_lines(content)
    normalized_event = required_lines[0]
    normalized_selection = normalize_unicode("NFKC", content.selection)
    observation_line = required_lines[3]
    candidate_lines = [
        stripped
        for line in normalized.splitlines()
        if (stripped := line.strip())
    ]

    folded = normalized.casefold()
    if content.is_demo:
        if "DEMO NO VIGENTE" not in candidate_lines:
            raise ValueError("provider caption omits the demo label")
    elif "demo no vigente" in folded:
        raise ValueError("provider caption leaks the demo label")
    if content.has_value_signal:
        if "Señal de valor comparada" not in candidate_lines:
            raise ValueError("provider caption omits the value label")
    elif "señal de valor comparada" in folded:
        raise ValueError("provider caption invents a value label")

    if any(required not in candidate_lines for required in required_lines):
        raise ValueError("provider caption omits a required exact line")
    allowed_lines = frozenset(required_lines + _OPTIONAL_NEUTRAL_LINES)
    if any(line not in allowed_lines for line in candidate_lines):
        raise ValueError("provider caption contains an unaudited line")
    _validate_protected_contexts(
        candidate_lines,
        approved_lines=required_lines,
        protected_fragments=(
            normalized_event,
            normalized_selection,
            required_lines[2],
            observation_line,
            "reytacopicks.com",
            "18+",
            "Apuesta con responsabilidad",
        )
        + conditional_lines,
    )

    if any("PERCENT SIGN" in unicode_name(character, "") for character in normalized):
        raise ValueError("provider caption contains a percentage")
    _validate_numbers(normalized, content=content, fallback=fallback)
    _validate_hashtags(
        normalized,
        platform=platform,
        normalized_fallback=normalized_fallback,
    )
    _validate_urls(normalized)
    dynamic_text = _dynamic_text(
        normalized,
        content=content,
        fallback=fallback,
    )
    if _contains_unsafe_dynamic_claim(dynamic_text):
        raise ValueError("provider caption contains an unsafe claim")
    return normalized


def _approved_public_texts(
    content: SocialContent,
    fallback: SocialCaptions,
) -> tuple[str, ...]:
    return (
        fallback.facebook,
        fallback.instagram,
        content.event,
        content.selection,
        content.odds_text,
        content.schedule,
        content.observed_at.isoformat(),
        content.starts_at.isoformat(),
        content.league,
        content.market,
    )


def _validate_protected_contexts(
    candidate_lines: list[str],
    *,
    approved_lines: tuple[str, ...],
    protected_fragments: tuple[str, ...],
) -> None:
    folded_candidate_lines = tuple(line.casefold() for line in candidate_lines)
    folded_approved_lines = tuple(line.casefold() for line in approved_lines)
    for fragment in protected_fragments:
        folded_fragment = fragment.casefold()
        allowed_contexts = {
            line for line in folded_approved_lines if folded_fragment in line
        }
        if any(
            folded_fragment in line and line not in allowed_contexts
            for line in folded_candidate_lines
        ):
            raise ValueError("provider caption alters a protected fact")


def _validate_numbers(
    candidate: str,
    *,
    content: SocialContent,
    fallback: SocialCaptions,
) -> None:
    allowed_numbers = {
        token
        for text in _approved_public_texts(content, fallback)
        for token in _NUMERIC_TOKEN.findall(normalize_unicode("NFKC", text))
    }
    if any(token not in allowed_numbers for token in _NUMERIC_TOKEN.findall(candidate)):
        raise ValueError("provider caption invents a numeric token")


def _validate_unicode_numbers(candidate: str) -> None:
    if any(
        not character.isascii()
        and unicode_category(character).startswith("N")
        for character in candidate
    ):
        raise ValueError("provider caption invents a Unicode numeric token")


def _validate_hashtags(
    candidate: str,
    *,
    platform: str,
    normalized_fallback: str,
) -> None:
    hashtags = _HASHTAG.findall(candidate)
    limit = 2 if platform == "facebook" else 4
    allowed = frozenset(_HASHTAG.findall(normalized_fallback))
    if (
        len(hashtags) > limit
        or any(hashtag not in allowed for hashtag in hashtags)
        or candidate.count("#") != len(hashtags)
    ):
        raise ValueError("provider caption contains invalid hashtags")


def _validate_urls(candidate: str) -> None:
    folded = candidate.casefold().translate(_IDNA_DOT_TRANSLATION)
    if (
        _URI_SCHEME.search(folded) is not None
        or _EMAIL.search(folded) is not None
        or "www." in folded
    ):
        raise ValueError("provider caption contains an unauthorized URL")
    domains = _DOMAIN.findall(folded)
    if any(domain != "reytacopicks.com" for domain in domains):
        raise ValueError("provider caption contains an unauthorized URL")
    if re.search(r"reytacopicks[.]com[/?:#]", folded) is not None:
        raise ValueError("provider caption expands the required plain domain")


def _dynamic_text(
    candidate: str,
    *,
    content: SocialContent,
    fallback: SocialCaptions,
) -> str:
    dynamic = candidate
    approved_fragments: set[str] = set()
    for approved_text in _approved_public_texts(content, fallback):
        normalized = normalize_unicode("NFKC", approved_text)
        approved_fragments.add(normalized)
        approved_fragments.update(normalized.splitlines())
    approved_fragments.update(
        {
            "reytacopicks.com",
            "18+",
            "Apuesta con responsabilidad",
            "DEMO NO VIGENTE",
            "Señal de valor comparada",
        }
    )
    for fragment in sorted(approved_fragments, key=len, reverse=True):
        if fragment:
            dynamic = dynamic.replace(fragment, " ")
    return _HASHTAG.sub(" ", dynamic).casefold()


def _contains_unsafe_dynamic_claim(dynamic_text: str) -> bool:
    if _PROMOTIONAL_CONTENT_SUBJECT.search(dynamic_text) is not None:
        return True
    if any(pattern.search(dynamic_text) is not None for pattern in _UNSAFE_DYNAMIC_PATTERNS):
        return True
    return not frozenset(_WORD_TOKEN.findall(dynamic_text)).isdisjoint(
        _WIN_OUTCOME_TOKENS
    )
