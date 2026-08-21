"""Strict Playdoit source boundary for dates, identities, and named markets.

Playdoit DOM records are untrusted.  Event identity and start time defects reject
the record; a malformed market rejects that complete quote rather than repairing
it with a positional price or an inferred selection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
import math
from numbers import Real
import re
from typing import Any
from zoneinfo import ZoneInfo

from backend.scraper_domain import Event, Market, Outcome
from selenium.webdriver.support.ui import WebDriverWait


MEXICO = ZoneInfo("America/Mexico_City")
SUPPORTED_MARKETS = frozenset({"h2h", "totals", "spreads"})
SUPPORTED_BOX_TITLES = {
    "h2h": frozenset({"resultado final", "ganador del partido", "moneyline", "1x2"}),
    "totals": frozenset(
        {"total de goles", "total de carreras", "total de puntos"}
    ),
    "spreads": frozenset(
        {"hándicap del partido", "handicap del partido", "línea de juego"}
    ),
}
UNSUPPORTED_MARKET_SCOPES = frozenset({"first_half", "team_total"})
_DECIMAL = re.compile(r"(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_SIGNED_DECIMAL = re.compile(r"[+-]?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_CALENDAR_DATE = re.compile(r"(\d{2})([/\-])(\d{2})\Z")
_CLOCK_TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)\Z")


class MissingStartTimeError(ValueError):
    """A source record omitted either its date label or exact clock time."""

    reason = "missing_start_time"


_EVENT_SUMMARIES_SCRIPT = r"""
/* playdoit:event-summaries */
function playdoitShadow() {
  var host = document.querySelector('div#altenar > div') ||
    document.querySelector('asb-sports-app, asb-app, altenar-app');
  return host && host.shadowRoot ? host.shadowRoot : null;
}
var shadow = playdoitShadow();
if (!shadow) return [];
var containers = Array.from(shadow.querySelectorAll('div[class*="EventBoxContainer"]'));
return containers.map(function(container) {
  var text = (container.innerText || '').trim();
  if (/e-fútbol|esports|virtual|cyber|\ben vivo\b|\blive\b/i.test(text)) return null;
  var dateMatch = text.match(/(?:^|\s)(Hoy|Mañana|\d{2}[\/-]\d{2})(?=\s|$)/im);
  var timeMatch = text.match(/(?:^|\s)((?:[01]\d|2[0-3]):[0-5]\d)(?=\s|$)/m);
  var date = dateMatch ? dateMatch[1] : '';
  var clock = timeMatch ? timeMatch[1] : '';
  var identityCandidates = [container].concat(Array.from(container.querySelectorAll(
    '[data-event-id], [data-eventid], [data-event-id-value]'
  )));
  var eventIds = identityCandidates.map(function(node) {
    return node.getAttribute('data-event-id') ||
      node.getAttribute('data-eventid') ||
      node.getAttribute('data-event-id-value') || '';
  }).map(function(value) { return value.trim(); }).filter(Boolean);
  eventIds = Array.from(new Set(eventIds));
  var eventId = eventIds.length === 1 ? eventIds[0] : '';
  var competitors = Array.from(container.querySelectorAll(
    '[class*="CompetitorName"], [class*="NameContainer"], [class*="EventName"]'
  )).map(function(node) { return (node.innerText || '').split('\n')[0].trim(); })
    .filter(function(value) { return value.length >= 2; });
  var home = competitors[0] || '';
  var away = competitors[1] || '';
  var leagueNode = container.closest('[data-league], [data-league-name]');
  var sportNode = container.closest('[data-sport], [data-sport-name]');
  return {
    event_id: eventId.trim(),
    sport: sportNode ? (sportNode.getAttribute('data-sport') || sportNode.getAttribute('data-sport-name') || '').trim() : '',
    league: leagueNode ? (leagueNode.getAttribute('data-league') || leagueNode.getAttribute('data-league-name') || '').trim() : '',
    home: home,
    away: away,
    date_label: date,
    time_label: clock,
    rejection_reason: eventIds.length > 1 ? 'ambiguous_event_identity' :
      (!eventId ? 'missing_event_identity' : (!date || !clock ? 'missing_start_time' : ''))
  };
}).filter(Boolean);
"""


_CLICK_EVENT_SCRIPT = r"""
/* playdoit:click-event */
var sourceId = arguments[0], home = arguments[1], away = arguments[2];
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return false;
var containers = Array.from(host.shadowRoot.querySelectorAll('div[class*="EventBoxContainer"]'));
var target = containers.find(function(container) {
  var nodes = [container].concat(Array.from(container.querySelectorAll(
    '[data-event-id], [data-eventid], [data-event-id-value]'
  )));
  var values = nodes.map(function(candidate) {
    return candidate.getAttribute('data-event-id') || candidate.getAttribute('data-eventid') ||
      candidate.getAttribute('data-event-id-value') || '';
  });
  var text = (container.innerText || '').toLocaleLowerCase();
  return values.some(function(value) { return value.trim() === sourceId; }) &&
    text.includes(home.toLocaleLowerCase()) && text.includes(away.toLocaleLowerCase());
});
if (!target) return false;
var clickable = target.querySelector(
  '[class*="Competitors"], [class*="NameContainer"], [class*="EventName"]'
) || target;
clickable.click();
return true;
"""


_DISCOVER_MARKET_TABS_SCRIPT = r"""
/* playdoit:discover-market-tabs */
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return [];
var nodes = Array.from(host.shadowRoot.querySelectorAll('*'));
var found = {};
nodes.forEach(function(node, index) {
  if (node.children.length !== 0) return;
  var label = (node.textContent || '').trim().toLocaleLowerCase();
  var key = null;
  if (/^(resultado final|ganador|moneyline|1x2)$/.test(label)) key = 'h2h';
  else if (/^(totales?|total de goles|más\/menos|mas\/menos)$/.test(label)) key = 'totals';
  else if (/^(hándicap|handicap|línea de juego)$/.test(label)) key = 'spreads';
  if (key && !found[key]) found[key] = {key: key, token: String(index)};
});
return Object.keys(found).map(function(key) { return found[key]; });
"""


_CLICK_MARKET_TAB_SCRIPT = r"""
/* playdoit:click-market-tab */
var token = Number(arguments[0]);
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot || !Number.isInteger(token)) return false;
var nodes = Array.from(host.shadowRoot.querySelectorAll('*'));
var node = nodes[token];
if (!node) return false;
(node.parentElement || node).click();
node.click();
return true;
"""


_IS_MARKET_TAB_ACTIVE_SCRIPT = r"""
/* playdoit:is-market-tab-active */
var token = Number(arguments[0]);
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot || !Number.isInteger(token)) return false;
var node = Array.from(host.shadowRoot.querySelectorAll('*'))[token];
if (!node) return false;
var candidate = node.parentElement || node;
return node.getAttribute('aria-selected') === 'true' ||
  candidate.getAttribute('aria-selected') === 'true' ||
  node.classList.contains('active') || node.classList.contains('selected') ||
  candidate.classList.contains('active') || candidate.classList.contains('selected');
"""


_MARKET_SIGNATURE_SCRIPT = r"""
/* playdoit:market-signature */
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return '';
var boxes = Array.from(host.shadowRoot.querySelectorAll(
  '[class*="MarketBox"], [class*="EventDetailsMarketBox"]'
));
return boxes.map(function(box) { return (box.innerText || '').trim(); })
  .filter(Boolean).join('\n---\n');
"""


_EXTRACT_VISIBLE_MARKET_SCRIPT = r"""
/* playdoit:extract-visible-market */
var marketKey = arguments[0], home = arguments[1], away = arguments[2];
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return [];
var boxes = Array.from(host.shadowRoot.querySelectorAll(
  '[class*="MarketBox"], [class*="EventDetailsMarketBox"]'
));
var SUPPORTED_BOX_TITLES = {
  h2h: ['resultado final', 'ganador del partido', 'moneyline', '1x2'],
  totals: ['total de goles', 'total de carreras', 'total de puntos'],
  spreads: ['hándicap del partido', 'handicap del partido', 'línea de juego']
};
var decimal = /^\d+(?:\.\d+)?$/;
var signed = /^[+-]?\d+(?:\.\d+)?$/;
return boxes.map(function(box) {
  var titleNode = box.querySelector('[class*="MarketName"], [class*="MarketTitle"], [class*="HeaderMarket"]');
  var title = titleNode ? (titleNode.textContent || '').trim().toLocaleLowerCase() : '';
  var period = (box.getAttribute('data-period') || '').trim().toLocaleLowerCase();
  var scope = (box.getAttribute('data-scope') || '').trim().toLocaleLowerCase();
  if (!(SUPPORTED_BOX_TITLES[marketKey] || []).includes(title)) return null;
  if (!['full_game', 'full game', 'partido completo'].includes(period)) return null;
  if (!['event', 'match', 'partido'].includes(scope)) return null;
  if (/primer|primera mitad|1st|equipo|team|local|visitante/.test(title)) return null;
  var buttons = Array.from(box.querySelectorAll(
    'button, [class*="OddBoxButton"], [class*="SelectionButton"]'
  ));
  var outcomes = [];
  var marketLine = null;
  buttons.forEach(function(button) {
    var priceNode = button.querySelector(
      '[data-odds], [data-price], [class*="OddValue"], [class*="Price"]'
    );
    var nameNode = button.querySelector(
      '[data-selection-name], [class*="SelectionName"], [class*="OutcomeName"], [class*="Name"]'
    );
    if (!priceNode || !nameNode) return;
    var price = (priceNode.getAttribute('data-odds') ||
      priceNode.getAttribute('data-price') || priceNode.textContent || '').trim();
    if (!decimal.test(price)) return;
    var label = (nameNode.getAttribute('data-selection-name') || nameNode.textContent || '').trim();
    if (!label) return;
    var lower = label.toLocaleLowerCase();
    var key = null, name = label, line = null;
    if (marketKey === 'h2h') {
      if (lower === home.toLocaleLowerCase()) { key = 'home'; name = home; }
      else if (lower === away.toLocaleLowerCase()) { key = 'away'; name = away; }
      else if (/^(empate|draw)$/.test(lower)) { key = 'draw'; name = label; }
    } else if (marketKey === 'totals') {
      if (/\b(más|mas|over)\b/.test(lower)) key = 'over';
      else if (/\b(menos|under)\b/.test(lower)) key = 'under';
    } else if (marketKey === 'spreads') {
      if (lower.startsWith(home.toLocaleLowerCase())) { key = 'home'; name = label; }
      else if (lower.startsWith(away.toLocaleLowerCase())) { key = 'away'; name = label; }
    }
    if (!key) return;
    if (marketKey !== 'h2h') {
      var lineNode = button.querySelector('[data-line], [data-point], [class*="Point"], [class*="Handicap"]');
      if (!lineNode) return;
      line = (lineNode.getAttribute('data-line') || lineNode.getAttribute('data-point') ||
        lineNode.textContent || '').trim();
      if (!signed.test(line)) return;
    }
    var outcome = {key: key, name: name, price: price};
    if (line !== null) {
      outcome.line = line;
      if (marketLine === null || key === 'home' || key === 'over') marketLine = line;
    }
    outcomes.push(outcome);
  });
  if (!outcomes.length) return null;
  var result = {key: marketKey, period: 'full_game', outcomes: outcomes};
  if (marketLine !== null) result.line = marketLine;
  return result;
}).filter(Boolean);
"""


_RETURN_TO_EVENTS_SCRIPT = r"""
/* playdoit:return-to-events */
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return false;
var button = host.shadowRoot.querySelector(
  'button[class*="BackButton"], [class*="HeaderBack"]'
);
if (!button) return false;
button.click();
return true;
"""


_EVENT_LIST_READY_SCRIPT = r"""
/* playdoit:event-list-ready */
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
return Boolean(host && host.shadowRoot &&
  host.shadowRoot.querySelector('div[class*="EventBoxContainer"]'));
"""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _mexico_observation(observed_at: datetime) -> datetime:
    if not isinstance(observed_at, datetime):
        raise TypeError("observed_at must be a datetime")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return observed_at.astimezone(MEXICO)


def _strict_number(value: object, field: str, *, price: bool = False) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be decimal")
    if isinstance(value, str):
        normalized = value.strip()
        pattern = _DECIMAL if price else _SIGNED_DECIMAL
        if pattern.fullmatch(normalized) is None:
            raise ValueError(f"{field} must be decimal")
        result = float(normalized)
    elif isinstance(value, Real):
        result = float(value)
    else:
        raise TypeError(f"{field} must be decimal")
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    if price and not 1.01 <= result <= 50.0:
        raise ValueError("price must be decimal odds between 1.01 and 50")
    return result


def resolve_mexico_start(
    date_label: str, time_label: str, observed_at: datetime
) -> datetime:
    """Resolve a strict Playdoit label to one future Mexico City instant."""

    observed = _mexico_observation(observed_at)
    if (
        not isinstance(date_label, str)
        or not date_label.strip()
        or not isinstance(time_label, str)
        or not time_label.strip()
    ):
        raise MissingStartTimeError("missing_start_time")
    date_text = date_label.strip()
    time_text = time_label.strip()
    time_match = _CLOCK_TIME.fullmatch(time_text)
    if time_match is None:
        raise ValueError("time_label must be HH:MM")
    hour, minute = (int(value) for value in time_match.groups())

    relative = date_text.casefold()
    if relative == "hoy":
        calendar_day = observed.date()
        candidate = datetime(
            calendar_day.year,
            calendar_day.month,
            calendar_day.day,
            hour,
            minute,
            tzinfo=MEXICO,
        )
    elif relative in {"mañana", "manana"}:
        calendar_day = observed.date() + timedelta(days=1)
        candidate = datetime(
            calendar_day.year,
            calendar_day.month,
            calendar_day.day,
            hour,
            minute,
            tzinfo=MEXICO,
        )
    else:
        date_match = _CALENDAR_DATE.fullmatch(date_text)
        if date_match is None:
            raise ValueError("date_label must be Hoy, Mañana, dd/mm, or dd-mm")
        day_value, _separator, month_value = date_match.groups()
        day_number = int(day_value)
        month = int(month_value)
        current_candidate = None
        try:
            current_candidate = datetime(
                observed.year, month, day_number, hour, minute, tzinfo=MEXICO
            )
        except ValueError:
            pass
        if current_candidate is not None and current_candidate > observed:
            candidate = current_candidate
        elif current_candidate is not None and (
            observed.date() - current_candidate.date()
        ).days <= 180:
            candidate = current_candidate
        else:
            candidate = None
            for year in range(observed.year + 1, observed.year + 9):
                try:
                    possible = datetime(
                        year, month, day_number, hour, minute, tzinfo=MEXICO
                    )
                except ValueError:
                    continue
                if possible > observed:
                    candidate = possible
                    break
            if candidate is None:
                raise ValueError("date_label is not a valid calendar date")

    assert candidate is not None
    if candidate <= observed:
        raise ValueError("event start must be in the future")
    return candidate


def _raw_outcomes(raw: Mapping[str, object]) -> list[Mapping[str, object]]:
    outcomes = raw.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        raise ValueError("market outcomes must be a non-empty list")
    if not all(isinstance(row, Mapping) for row in outcomes):
        raise TypeError("market outcomes must contain objects")
    return outcomes


def _named_team_key(name: str, home: str, away: str) -> str | None:
    normalized = name.casefold()
    if normalized == home.casefold():
        return "home"
    if normalized == away.casefold():
        return "away"
    if normalized in {"empate", "draw"}:
        return "draw"
    return None


def _normalize_h2h(
    raw: Mapping[str, object], home: str, away: str, sport: str
) -> Market:
    outcomes: dict[str, Outcome] = {}
    for row in _raw_outcomes(raw):
        key = _required_text(row.get("key"), "outcome key").casefold()
        name = _required_text(row.get("name"), "outcome name")
        if key != _named_team_key(name, home, away) or key in outcomes:
            raise ValueError("h2h contains an unknown or duplicate selection")
        outcomes[key] = Outcome(
            key, name, _strict_number(row.get("price"), "price", price=True)
        )

    soccer = sport.casefold() in {"soccer", "football", "fútbol", "futbol"}
    expected = {"home", "draw", "away"} if soccer else {"home", "away"}
    if set(outcomes) != expected:
        raise ValueError("h2h selections do not match the sport format")
    order = ("home", "draw", "away") if soccer else ("home", "away")
    return Market(
        "h2h",
        "full_game",
        None,
        tuple(outcomes[key] for key in order),
        bookmaker_key="playdoit",
    )


def _normalize_totals(raw: Mapping[str, object]) -> Market:
    line = _strict_number(raw.get("line"), "line")
    outcomes: dict[str, Outcome] = {}
    for row in _raw_outcomes(raw):
        key = _required_text(row.get("key"), "outcome key").casefold()
        if key not in {"over", "under"} or key in outcomes:
            raise ValueError("totals contains an unknown or duplicate selection")
        name = _required_text(row.get("name"), "outcome name")
        normalized_name = name.casefold()
        expected_prefixes = (
            ("más", "mas", "over") if key == "over" else ("menos", "under")
        )
        if not normalized_name.startswith(expected_prefixes):
            raise ValueError("total selection name contradicts its key")
        named_lines = re.findall(r"[+-]?\d+(?:\.\d+)?", normalized_name)
        if not named_lines or not math.isclose(
            float(named_lines[-1]), line, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ValueError("total selection name must contain the market line")
        row_line = _strict_number(row.get("line"), "outcome line")
        if not math.isclose(row_line, line, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("totals selections must share one line")
        outcomes[key] = Outcome(
            key,
            name,
            _strict_number(row.get("price"), "price", price=True),
        )
    if set(outcomes) != {"over", "under"}:
        raise ValueError("totals must contain over and under")
    return Market(
        "totals",
        "full_game",
        line,
        (outcomes["over"], outcomes["under"]),
        bookmaker_key="playdoit",
    )


def _normalize_spreads(
    raw: Mapping[str, object], home: str, away: str
) -> Market:
    line = _strict_number(raw.get("line"), "line")
    outcomes: dict[str, Outcome] = {}
    points: dict[str, float] = {}
    for row in _raw_outcomes(raw):
        key = _required_text(row.get("key"), "outcome key").casefold()
        name = _required_text(row.get("name"), "outcome name")
        if key not in {"home", "away"} or key in outcomes:
            raise ValueError("spreads contains an unknown or duplicate selection")
        if not name.casefold().startswith(
            (home if key == "home" else away).casefold()
        ):
            raise ValueError("spread selection is not bound to its named team")
        points[key] = _strict_number(row.get("line"), "outcome line")
        outcomes[key] = Outcome(
            key,
            name,
            _strict_number(row.get("price"), "price", price=True),
        )
    if set(outcomes) != {"home", "away"}:
        raise ValueError("spreads must contain home and away")
    if not math.isclose(points["home"], line, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("spread home line must equal the market line")
    if not math.isclose(
        points["home"], -points["away"], rel_tol=0.0, abs_tol=1e-9
    ):
        raise ValueError("spread lines must be opposing")
    return Market(
        "spreads",
        "full_game",
        line,
        (outcomes["home"], outcomes["away"]),
        bookmaker_key="playdoit",
    )


def _normalize_market(
    raw: Mapping[str, object], home: str, away: str, sport: str
) -> Market | None:
    key = raw.get("key")
    period = raw.get("period")
    if not isinstance(key, str) or key.casefold() not in SUPPORTED_MARKETS:
        return None
    if not isinstance(period, str) or period.casefold() != "full_game":
        return None
    try:
        normalized_key = key.casefold()
        if normalized_key == "h2h":
            return _normalize_h2h(raw, home, away, sport)
        if normalized_key == "totals":
            return _normalize_totals(raw)
        return _normalize_spreads(raw, home, away)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _market_identity(market: Market) -> tuple[object, ...]:
    return (market.bookmaker_key, market.key, market.period, market.line)


def _market_prices(market: Market) -> tuple[tuple[str, str, float], ...]:
    return tuple(
        (outcome.key, outcome.name, outcome.price) for outcome in market.outcomes
    )


def normalize_playdoit_event(raw: dict[str, Any], observed_at: datetime) -> Event:
    """Normalize one Playdoit record without inventing identity, time, or odds."""

    if not isinstance(raw, dict):
        raise TypeError("raw event must be an object")
    event_id = _required_text(raw.get("event_id"), "event_id")
    sport = _required_text(raw.get("sport"), "sport")
    league = _required_text(raw.get("league"), "league")
    home = _required_text(raw.get("home"), "home")
    away = _required_text(raw.get("away"), "away")
    observed = _mexico_observation(observed_at)
    if not isinstance(raw.get("date_label"), str) or not str(
        raw.get("date_label")
    ).strip():
        raise MissingStartTimeError("missing_start_time")
    if not isinstance(raw.get("time_label"), str) or not str(
        raw.get("time_label")
    ).strip():
        raise MissingStartTimeError("missing_start_time")
    starts_at = resolve_mexico_start(
        str(raw["date_label"]),
        str(raw["time_label"]),
        observed,
    )

    raw_markets = raw.get("markets", [])
    if not isinstance(raw_markets, list):
        raise TypeError("markets must be a list")
    selected: dict[tuple[object, ...], Market] = {}
    conflicted: set[tuple[object, ...]] = set()
    for raw_market in raw_markets:
        if not isinstance(raw_market, Mapping):
            continue
        market = _normalize_market(raw_market, home, away, sport)
        if market is None:
            continue
        identity = _market_identity(market)
        if identity in conflicted:
            continue
        previous = selected.get(identity)
        if previous is None:
            selected[identity] = market
        elif _market_prices(previous) != _market_prices(market):
            selected.pop(identity)
            conflicted.add(identity)

    return Event(
        source="playdoit",
        source_event_id=event_id,
        sport=sport,
        league=league,
        home_team=home,
        away_team=away,
        starts_at=starts_at,
        observed_at=observed,
        markets=tuple(selected.values()),
    )


def normalize_playdoit_events(
    raw_events: Iterable[dict[str, Any]],
    observed_at: datetime,
    *,
    rejections: list[str] | None = None,
) -> tuple[Event, ...]:
    """Normalize a batch and omit any source ID with conflicting revisions."""

    selected: dict[str, Event] = {}
    order: list[str] = []
    conflicted: set[str] = set()
    for raw in raw_events:
        try:
            event = normalize_playdoit_event(raw, observed_at)
        except MissingStartTimeError:
            if rejections is not None:
                rejections.append(MissingStartTimeError.reason)
            continue
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        event_id = event.source_event_id
        if event_id in conflicted:
            continue
        previous = selected.get(event_id)
        if previous is None:
            selected[event_id] = event
            order.append(event_id)
        elif previous != event:
            selected.pop(event_id)
            conflicted.add(event_id)
    return tuple(selected[event_id] for event_id in order if event_id in selected)


def market_signature(driver: Any) -> str:
    """Return the currently rendered market text used only as a wait signal."""

    value = driver.execute_script(_MARKET_SIGNATURE_SCRIPT)
    return value.strip() if isinstance(value, str) else ""


def _available_market_tabs(driver: Any) -> dict[str, str]:
    raw_tabs = driver.execute_script(_DISCOVER_MARKET_TABS_SCRIPT)
    tabs: dict[str, str] = {}
    if not isinstance(raw_tabs, list):
        return tabs
    for raw in raw_tabs:
        if not isinstance(raw, Mapping):
            continue
        key = raw.get("key")
        token = raw.get("token")
        if (
            isinstance(key, str)
            and key in SUPPORTED_MARKETS
            and isinstance(token, str)
            and token
            and key not in tabs
        ):
            tabs[key] = token
    return tabs


def extract_visible_markets(
    driver: Any, market_key: str, home: str, away: str
) -> list[dict[str, Any]]:
    """Extract the active tab, passing all source text as script arguments."""

    raw = driver.execute_script(
        _EXTRACT_VISIBLE_MARKET_SCRIPT, market_key, home, away
    )
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def extract_supported_markets(
    driver: Any,
    home: str,
    away: str,
    *,
    wait_factory: Any = None,
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """Click supported tabs sequentially and isolate stale/timeout failures."""

    active_wait_factory = wait_factory or WebDriverWait

    markets: list[dict[str, Any]] = []
    try:
        active_wait_factory(driver, timeout).until(
            lambda active: bool(_available_market_tabs(active))
        )
    except Exception:
        # A transient discovery failure is isolated; each market below gets a
        # fresh bounded attempt against the current DOM.
        pass
    for market_key in ("h2h", "totals", "spreads"):
        try:
            # Altenar replaces tab nodes after clicks. Recapture every time.
            tabs = _available_market_tabs(driver)
            token = tabs.get(market_key)
            if token is None:
                continue
            active = driver.execute_script(_IS_MARKET_TAB_ACTIVE_SCRIPT, token)
            if active is not True:
                if driver.execute_script(_CLICK_MARKET_TAB_SCRIPT, token) is not True:
                    continue
            active_wait_factory(driver, timeout).until(
                lambda active: (
                    signature
                    if (signature := market_signature(active))
                    and active.execute_script(
                        _IS_MARKET_TAB_ACTIVE_SCRIPT, token
                    ) is True
                    else False
                )
            )
            markets.extend(
                extract_visible_markets(driver, market_key, home, away)
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            continue
    return markets


def _complete_summary(raw: object) -> bool:
    if not isinstance(raw, Mapping):
        return False
    for field in ("event_id", "home", "away"):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            return False
    return True


def extract_playdoit_raw_events(
    driver: Any,
    *,
    wait_factory: Any = None,
    timeout: float = 8.0,
    rejections: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Capture structured raw records without positional prices or defaults."""

    active_wait_factory = wait_factory or WebDriverWait
    try:
        summaries = driver.execute_script(_EVENT_SUMMARIES_SCRIPT)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return []
    if not isinstance(summaries, list):
        return []
    records: list[dict[str, Any]] = []
    for summary in summaries:
        if not _complete_summary(summary):
            if rejections is not None and isinstance(summary, Mapping):
                reason = summary.get("rejection_reason")
                if isinstance(reason, str) and reason:
                    rejections.append(reason)
            continue
        record = dict(summary)
        if not isinstance(record.get("date_label"), str) or not str(
            record.get("date_label")
        ).strip() or not isinstance(record.get("time_label"), str) or not str(
            record.get("time_label")
        ).strip():
            if rejections is not None:
                rejections.append(MissingStartTimeError.reason)
            continue
        event_id = str(record["event_id"]).strip()
        home = str(record["home"]).strip()
        away = str(record["away"]).strip()
        entered_detail = False
        try:
            entered_detail = driver.execute_script(
                _CLICK_EVENT_SCRIPT, event_id, home, away
            ) is True
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            continue
        if not entered_detail:
            continue
        try:
            record["markets"] = extract_supported_markets(
                driver,
                home,
                away,
                wait_factory=wait_factory,
                timeout=timeout,
            )
            records.append(record)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            continue
        finally:
            try:
                driver.execute_script(_RETURN_TO_EVENTS_SCRIPT)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            try:
                active_wait_factory(driver, timeout).until(
                    lambda active: active.execute_script(
                        _EVENT_LIST_READY_SCRIPT
                    ) is True
                )
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
    return records
