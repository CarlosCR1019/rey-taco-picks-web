"""Strict Playdoit source boundary for dates, identities, and named markets.

Playdoit DOM records are untrusted.  Event identity and start time defects reject
the record; a malformed market rejects that complete quote rather than repairing
it with a positional price or an inferred selection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
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
    "h2h": frozenset({
        "resultado final",
        "resultado final (tiempo regular)",
        "ganador del partido",
        "moneyline",
        "1x2",
    }),
    "totals": frozenset(
        {"total", "total de goles", "total de carreras", "total de puntos"}
    ),
    "spreads": frozenset(
        {
            "hándicap asiatico",
            "hándicap asiático",
            "handicap asiatico",
            "handicap asiático",
            "hándicap del partido",
            "handicap del partido",
            "línea de juego",
        }
    ),
}
UNSUPPORTED_MARKET_SCOPES = frozenset({"first_half", "team_total"})
SUPPORTED_MARKET_PERIODS = frozenset(
    {"full_game", "full game", "partido completo"}
)
SUPPORTED_MARKET_SCOPES = frozenset({"event", "match", "partido"})
_DECIMAL = re.compile(r"(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_SIGNED_DECIMAL = re.compile(r"[+-]?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_SPREAD_SELECTION_LINE = re.compile(
    r"\(([+-]?(?:0|[1-9]\d*)(?:\.\d+)?)\)\s*\Z"
)
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
function playdoitFiber(node) {
  if (!node) return null;
  var key = Object.getOwnPropertyNames(node).find(function(name) {
    return name.indexOf('__reactFiber$') === 0;
  });
  return key ? node[key] : null;
}
function playdoitProps(node, predicate) {
  var fiber = playdoitFiber(node);
  for (var depth = 0; fiber && depth < 30; depth += 1, fiber = fiber.return) {
    var candidates = [fiber.memoizedProps, fiber.pendingProps];
    for (var index = 0; index < candidates.length; index += 1) {
      var props = candidates[index];
      if (props && predicate(props)) return props;
    }
  }
  return null;
}
function playdoitOdd(button) {
  var props = playdoitProps(button, function(candidate) {
    return candidate.odd && typeof candidate.odd === 'object';
  });
  if (!props) return null;
  var odd = props.odd;
  return {
    id: odd.id,
    competitorId: odd.competitorId,
    name: odd.name,
    oddStatus: odd.oddStatus,
    price: odd.price,
    typeId: odd.typeId,
    sv: odd.sv
  };
}
function playdoitMarket(button) {
  var props = playdoitProps(button, function(candidate) {
    return candidate.market && typeof candidate.market === 'object' &&
      Array.isArray(candidate.market.oddIds);
  });
  if (!props) return null;
  var market = props.market;
  return {
    id: market.id,
    name: market.name,
    oddIds: market.oddIds.slice(),
    sportMarketId: market.sportMarketId,
    typeId: market.typeId,
    sv: market.sv
  };
}
var shadow = playdoitShadow();
if (!shadow) return [];
var containers = Array.from(shadow.querySelectorAll(
  'div[class*="EventBoxContainer"]'
)).filter(function(container) {
  return !String(container.className || '').includes('BannerEventBoxContainer');
});
return containers.map(function(container) {
  var eventProps = playdoitProps(container, function(candidate) {
    return candidate.event && typeof candidate.event === 'object' &&
      Array.isArray(candidate.competitors) &&
      candidate.sport && candidate.championship;
  });
  if (!eventProps) return null;
  var event = eventProps.event;
  var groups = {};
  Array.from(container.querySelectorAll('button[class*="OddBoxButton"]'))
    .forEach(function(button) {
      var odd = playdoitOdd(button);
      var market = playdoitMarket(button);
      if (!odd || !market || !market.id || !odd.id ||
          !market.oddIds.map(String).includes(String(odd.id))) return;
      var key = String(market.id);
      if (!groups[key]) groups[key] = {market: market, odds: []};
      if (!groups[key].odds.some(function(value) {
        return String(value.id) === String(odd.id);
      })) groups[key].odds.push(odd);
    });
  return {
    event: {
      id: event.id,
      name: event.name,
      startDate: event.startDate,
      status: event.status
    },
    sport: {
      id: eventProps.sport.id,
      name: eventProps.sport.name,
      iconName: eventProps.sport.iconName
    },
    championship: {
      id: eventProps.championship.id,
      name: eventProps.championship.name
    },
    competitors: eventProps.competitors.map(function(competitor) {
      return {id: competitor.id, name: competitor.name};
    }),
    markets: Object.keys(groups).map(function(key) { return groups[key]; })
  };
}).filter(Boolean);
"""


_CLICK_EVENT_SCRIPT = r"""
/* playdoit:click-event */
var sourceId = arguments[0], home = arguments[1], away = arguments[2];
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return false;
function playdoitFiber(node) {
  if (!node) return null;
  var key = Object.getOwnPropertyNames(node).find(function(name) {
    return name.indexOf('__reactFiber$') === 0;
  });
  return key ? node[key] : null;
}
function playdoitProps(node) {
  var fiber = playdoitFiber(node);
  for (var depth = 0; fiber && depth < 30; depth += 1, fiber = fiber.return) {
    var candidates = [fiber.memoizedProps, fiber.pendingProps];
    for (var index = 0; index < candidates.length; index += 1) {
      var props = candidates[index];
      if (props && props.event && typeof props.event === 'object' &&
          Array.isArray(props.competitors)) return props;
    }
  }
  return null;
}
var containers = Array.from(host.shadowRoot.querySelectorAll('div[class*="EventBoxContainer"]'));
var target = containers.find(function(container) {
  var nodes = [container].concat(Array.from(container.querySelectorAll(
    '[data-event-id], [data-eventid], [data-event-id-value]'
  )));
  var values = nodes.map(function(candidate) {
    return candidate.getAttribute('data-event-id') || candidate.getAttribute('data-eventid') ||
      candidate.getAttribute('data-event-id-value') || '';
  });
  var props = playdoitProps(container);
  var reactId = props && props.event ? String(props.event.id || '') : '';
  var competitorNames = props ? props.competitors.map(function(competitor) {
    return String(competitor.name || '').trim().toLocaleLowerCase();
  }) : [];
  var text = (container.innerText || '').toLocaleLowerCase();
  var identityMatches = competitorNames.length ?
    competitorNames.includes(home.toLocaleLowerCase()) &&
      competitorNames.includes(away.toLocaleLowerCase()) :
    text.includes(home.toLocaleLowerCase()) && text.includes(away.toLocaleLowerCase());
  return (reactId === sourceId || values.some(function(value) {
    return value.trim() === sourceId;
  })) && identityMatches;
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
var supportedTitles = arguments[3], supportedPeriods = arguments[4], supportedScopes = arguments[5];
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return [];
var boxes = Array.from(host.shadowRoot.querySelectorAll(
  '[class*="MarketBox"], [class*="EventDetailsMarketBox"]'
));
var decimal = /^\d+(?:\.\d+)?$/;
var signed = /^[+-]?\d+(?:\.\d+)?$/;
return boxes.map(function(box) {
  var titleNode = box.querySelector('[class*="MarketName"], [class*="MarketTitle"], [class*="HeaderMarket"]');
  var title = titleNode ? (titleNode.textContent || '').trim().toLocaleLowerCase() : '';
  var period = (box.getAttribute('data-period') || '').trim().toLocaleLowerCase();
  var scope = (box.getAttribute('data-scope') || '').trim().toLocaleLowerCase();
  if (!supportedTitles.includes(title)) return null;
  if (!supportedPeriods.includes(period)) return null;
  if (!supportedScopes.includes(scope)) return null;
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
  var result = {
    key: marketKey,
    title: title,
    period: period,
    scope: scope,
    outcomes: outcomes
  };
  if (marketLine !== null) result.line = marketLine;
  return result;
}).filter(Boolean);
"""


_EXTRACT_REACT_DETAIL_MARKETS_SCRIPT = r"""
/* playdoit:extract-react-detail-markets */
var sourceId = String(arguments[0] || '').trim();
var home = String(arguments[1] || '').trim().toLocaleLowerCase();
var away = String(arguments[2] || '').trim().toLocaleLowerCase();
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot || !sourceId || !home || !away) {
  return {verified: false, source_event_id: '', groups: []};
}
var route = new URLSearchParams(
  String(window.location.hash || '').replace(/^#/, '')
);
var routedEventId = String(route.get('eventId') || '').trim();
if (routedEventId !== sourceId) {
  return {verified: false, source_event_id: routedEventId, groups: []};
}
var roots = Array.from(host.shadowRoot.querySelectorAll(
  '[class*="EventDetailsMarketsContainer"]'
));
if (roots.length !== 1) {
  return {verified: false, source_event_id: sourceId, groups: []};
}
var detailRoot = roots[0];
var detailText = (detailRoot.innerText || '').toLocaleLowerCase();
if (!detailText.includes(home) || !detailText.includes(away)) {
  return {verified: false, source_event_id: sourceId, groups: []};
}
function playdoitFiber(node) {
  if (!node) return null;
  var key = Object.getOwnPropertyNames(node).find(function(name) {
    return name.indexOf('__reactFiber$') === 0;
  });
  return key ? node[key] : null;
}
function playdoitField(node, field) {
  var fiber = playdoitFiber(node);
  for (var depth = 0; fiber && depth < 30; depth += 1, fiber = fiber.return) {
    var candidates = [fiber.memoizedProps, fiber.pendingProps];
    for (var index = 0; index < candidates.length; index += 1) {
      var props = candidates[index];
      if (props && props[field] && typeof props[field] === 'object') {
        return props[field];
      }
    }
  }
  return null;
}
var groups = {};
Array.from(detailRoot.querySelectorAll('button[class*="OddBoxButton"]'))
  .forEach(function(button) {
    var odd = playdoitField(button, 'odd');
    var market = playdoitField(button, 'market');
    if (!odd || !market || market.id === undefined || market.id === null ||
        odd.id === undefined || odd.id === null) return;
    if (Array.isArray(market.oddIds) && market.oddIds.length &&
        !market.oddIds.some(function(value) {
          return String(value) === String(odd.id);
        })) return;
    var offerRoot = button.closest('[class*="Boosted"], [class*="PlayBoost"]');
    var offerKind = offerRoot ? 'boosted' : 'standard';
    var offerDescription = offerRoot ? (offerRoot.innerText || '').trim() : '';
    var marketId = String(market.id);
    if (!groups[marketId]) {
      groups[marketId] = {
        market: {
          id: market.id,
          name: market.name,
          oddIds: Array.isArray(market.oddIds) ? market.oddIds.slice() : [],
          sportMarketId: market.sportMarketId,
          typeId: market.typeId,
          sv: market.sv,
          period: market.period,
          periodName: market.periodName,
          scope: market.scope,
          scopeName: market.scopeName,
          competitorId: market.competitorId,
          teamId: market.teamId,
          participantId: market.participantId,
          shortName: market.shortName,
          variant: market.variant,
          offerKind: offerKind,
          offerDescription: offerDescription
        },
        odds: []
      };
    }
    if (!groups[marketId].odds.some(function(value) {
      return String(value.id) === String(odd.id);
    })) {
      groups[marketId].odds.push({
        id: odd.id,
        competitorId: odd.competitorId,
        name: odd.name,
        oddStatus: odd.oddStatus,
        price: odd.price,
        typeId: odd.typeId,
        sv: odd.sv
      });
    }
  });
return {
  verified: true,
  source_event_id: sourceId,
  groups: Object.keys(groups).map(function(key) { return groups[key]; })
};
"""


_EXPAND_REACT_SPREAD_MARKET_SCRIPT = r"""
/* playdoit:expand-react-spread-market */
var supportedTitles = arguments[0];
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot || !Array.isArray(supportedTitles)) return false;
var node = Array.from(host.shadowRoot.querySelectorAll(
  '[class*="EventDetailsMarketName"]'
)).find(function(candidate) {
  var text = (candidate.textContent || '').trim().toLocaleLowerCase();
  return supportedTitles.includes(text);
});
if (!node) return false;
var root = node.closest('[class*="EventDetailsMarketBoxRoot"]');
if (root) root.scrollIntoView({block: 'center'});
var header = node.closest('[class*="EventDetailsMarketHeader"]') || node;
header.click();
node.click();
return true;
"""


_ADVANCE_REACT_DETAIL_MARKETS_SCRIPT = r"""
/* playdoit:advance-react-detail-markets */
var sourceId = String(arguments[0] || '').trim();
var route = new URLSearchParams(
  String(window.location.hash || '').replace(/^#/, '')
);
if (!sourceId || route.get('eventId') !== sourceId) return null;
var host = document.querySelector('div#altenar > div') ||
  document.querySelector('asb-sports-app, asb-app, altenar-app');
if (!host || !host.shadowRoot) return null;
var roots = Array.from(host.shadowRoot.querySelectorAll(
  '[class*="EventDetailsMarketsContainer"]'
));
if (roots.length !== 1) return null;
var root = roots[0];
var before = Number(root.scrollTop || 0);
var step = Math.max(Number(root.clientHeight || 0) * 0.75, 240);
root.scrollTop = Math.min(
  before + step,
  Math.max(Number(root.scrollHeight || 0) - Number(root.clientHeight || 0), 0)
);
return {
  scrollTop: Number(root.scrollTop || 0),
  scrollHeight: Number(root.scrollHeight || 0),
  clientHeight: Number(root.clientHeight || 0)
};
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


def _normalize_source_market(raw: Mapping[str, object]) -> Market:
    source_market_id = _required_text(
        raw.get("source_market_id"), "source market id"
    )
    title = _required_text(raw.get("title"), "market title")
    period_value = _required_text(raw.get("period"), "market period")
    outcomes = tuple(
        Outcome(
            _required_text(row.get("key"), "outcome key"),
            _required_text(row.get("name"), "outcome name"),
            _strict_number(row.get("price"), "price", price=True),
            source_id=_required_text(
                row.get("source_selection_id"), "source selection id"
            ),
        )
        for row in _raw_outcomes(raw)
    )
    sport_market_id = raw.get("sport_market_id")
    return Market(
        f"playdoit_market:{source_market_id}",
        period_value,
        None,
        outcomes,
        bookmaker_key="playdoit",
        name=title,
        source_id=source_market_id,
        sport_market_id=(
            _required_text(sport_market_id, "sport_market_id")
            if sport_market_id is not None
            else None
        ),
    )


def _normalize_market(
    raw: Mapping[str, object], home: str, away: str, sport: str
) -> Market | None:
    key = raw.get("key")
    if not isinstance(key, str):
        return None
    try:
        normalized_key = key.casefold()
        if normalized_key == "source_market":
            return _normalize_source_market(raw)
        if normalized_key not in SUPPORTED_MARKETS:
            return None
        title = _required_text(raw.get("title"), "market title").casefold()
        period = _required_text(raw.get("period"), "market period").casefold()
        scope = _required_text(raw.get("scope"), "market scope").casefold()
        if title not in SUPPORTED_BOX_TITLES[normalized_key]:
            return None
        if period not in SUPPORTED_MARKET_PERIODS:
            return None
        if scope not in SUPPORTED_MARKET_SCOPES:
            return None
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
        _EXTRACT_VISIBLE_MARKET_SCRIPT,
        market_key,
        home,
        away,
        sorted(SUPPORTED_BOX_TITLES[market_key]),
        sorted(SUPPORTED_MARKET_PERIODS),
        sorted(SUPPORTED_MARKET_SCOPES),
    )
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _generic_react_market_from_group(
    raw: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Preserve one complete official group without inventing its semantics."""

    market = raw.get("market")
    odds = raw.get("odds")
    if not isinstance(market, Mapping) or not isinstance(odds, list):
        return None
    market_id = str(market.get("id") or "").strip()
    title = str(market.get("name") or "").strip()
    if not market_id or not title:
        return None
    offer_kind = str(market.get("offerKind") or "standard").strip()
    offer_description = str(
        market.get("offerDescription") or ""
    ).strip()
    if offer_kind == "boosted" and not offer_description:
        return None

    outcomes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for odd in odds:
        if not isinstance(odd, Mapping) or odd.get("oddStatus") not in (None, 0):
            continue
        odd_id = str(odd.get("id") or "").strip()
        name = str(odd.get("name") or "").strip()
        if not odd_id or not name or odd_id in seen_ids:
            continue
        try:
            price = _strict_number(odd.get("price"), "price", price=True)
        except (TypeError, ValueError, OverflowError):
            continue
        seen_ids.add(odd_id)
        outcomes.append({
            "key": f"playdoit_odd:{odd_id}",
            "source_selection_id": odd_id,
            "name": name,
            "price": price,
        })
    if not outcomes:
        return None

    explicit_period = market.get("period")
    if explicit_period is None:
        explicit_period = market.get("periodName")
    explicit_scope = market.get("scope")
    if explicit_scope is None:
        explicit_scope = market.get("scopeName")
    return {
        "key": "source_market",
        "title": title,
        "period": str(explicit_period or "source_unspecified").strip(),
        "scope": str(explicit_scope or "source_unspecified").strip(),
        "source_market_id": market_id,
        "sport_market_id": (
            str(market["sportMarketId"]).strip()
            if market.get("sportMarketId") is not None
            else None
        ),
        "offer_kind": offer_kind,
        "offer_description": offer_description,
        "outcomes": outcomes,
    }


def _react_detail_markets_from_group(
    raw: Mapping[str, Any], home: str, away: str
) -> list[dict[str, Any]]:
    market = raw.get("market")
    odds = raw.get("odds")
    if not isinstance(market, Mapping) or not isinstance(odds, list):
        return []
    title_value = market.get("name")
    if not isinstance(title_value, str) or not title_value.strip():
        return []
    title = title_value.strip()
    normalized_title = title.casefold()
    generic = _generic_react_market_from_group(raw)
    if normalized_title in SUPPORTED_BOX_TITLES["h2h"]:
        market_key = "h2h"
    elif normalized_title in SUPPORTED_BOX_TITLES["totals"]:
        market_key = "totals"
    elif normalized_title in SUPPORTED_BOX_TITLES["spreads"]:
        market_key = "spreads"
    else:
        return [generic] if generic is not None else []

    period_value = market.get("period")
    scope_value = market.get("scope")
    explicit_canonical_scope = (
        isinstance(period_value, str)
        and period_value.strip().casefold() in SUPPORTED_MARKET_PERIODS
        and isinstance(scope_value, str)
        and scope_value.strip().casefold() in SUPPORTED_MARKET_SCOPES
    )

    outcomes = []
    for odd in odds:
        if not isinstance(odd, Mapping) or odd.get("oddStatus") not in (None, 0):
            continue
        name_value = odd.get("name")
        if not isinstance(name_value, str) or not name_value.strip():
            continue
        name = name_value.strip()
        normalized_name = name.casefold()
        if market_key == "h2h":
            key = _named_team_key(name, home, away)
        elif market_key == "totals":
            if odd.get("typeId") == 12 or normalized_name.startswith(
                ("más", "mas", "over")
            ):
                key = "over"
            elif odd.get("typeId") == 13 or normalized_name.startswith(
                ("menos", "under")
            ):
                key = "under"
            else:
                key = None
        elif normalized_name.startswith(home.casefold()):
            key = "home"
        elif normalized_name.startswith(away.casefold()):
            key = "away"
        else:
            key = None
        if key is None:
            continue
        outcome = {
            "key": key,
            "name": name,
            "price": odd.get("price"),
        }
        if market_key == "totals":
            outcome["line"] = odd.get("sv", market.get("sv"))
        elif market_key == "spreads":
            line_match = _SPREAD_SELECTION_LINE.search(name)
            outcome["line"] = (
                line_match.group(1) if line_match is not None else None
            )
        outcomes.append(outcome)

    base = (
        {
            "key": market_key,
            "title": title,
            "period": period_value.strip().casefold(),
            "scope": scope_value.strip().casefold(),
        }
        if explicit_canonical_scope
        else {}
    )
    if market_key == "totals":
        sides = {
            key: [row for row in outcomes if row["key"] == key]
            for key in ("over", "under")
        }
        if any(len(rows) != 1 for rows in sides.values()):
            return []
        try:
            over_line = _strict_number(
                sides["over"][0].get("line"), "total over line"
            )
            under_line = _strict_number(
                sides["under"][0].get("line"), "total under line"
            )
        except (TypeError, ValueError, OverflowError):
            return []
        if over_line != under_line:
            return []
        if not explicit_canonical_scope:
            return [generic] if generic is not None else []
        result = {
            **base,
            "outcomes": [sides["over"][0], sides["under"][0]],
        }
        result["line"] = sides["over"][0]["line"]
        return [result]
    if market_key == "h2h":
        by_key = {
            key: [row for row in outcomes if row["key"] == key]
            for key in ("home", "draw", "away")
        }
        complete_two_way = (
            len(by_key["home"]) == 1
            and not by_key["draw"]
            and len(by_key["away"]) == 1
        )
        complete_three_way = all(len(by_key[key]) == 1 for key in by_key)
        if not (complete_two_way or complete_three_way):
            return []
        if not explicit_canonical_scope:
            return [generic] if generic is not None else []
        return [{**base, "outcomes": outcomes}]

    paired: dict[float, dict[str, list[dict[str, Any]]]] = {}
    for outcome in outcomes:
        try:
            selection_line = _strict_number(
                outcome.get("line"), "spread selection line"
            )
        except (TypeError, ValueError, OverflowError):
            continue
        canonical_line = (
            selection_line
            if outcome["key"] == "home"
            else -selection_line
        )
        pair = paired.setdefault(
            canonical_line, {"home": [], "away": []}
        )
        pair[outcome["key"]].append(outcome)

    results = []
    for pair in paired.values():
        if len(pair["home"]) != 1 or len(pair["away"]) != 1:
            continue
        home_outcome = pair["home"][0]
        results.append({
            **base,
            "line": home_outcome["line"],
            "outcomes": [home_outcome, pair["away"][0]],
        })
    if not explicit_canonical_scope:
        return [generic] if results and generic is not None else []
    return results


def extract_react_detail_groups(
    driver: Any, event_id: str, home: str, away: str
) -> list[dict[str, Any]]:
    """Return groups only when React detail provenance matches one event."""

    expected_event_id = str(event_id).strip()
    if not expected_event_id:
        return []
    raw = driver.execute_script(
        _EXTRACT_REACT_DETAIL_MARKETS_SCRIPT,
        expected_event_id,
        home,
        away,
    )
    if (
        not isinstance(raw, Mapping)
        or raw.get("verified") is not True
        or str(raw.get("source_event_id") or "").strip()
        != expected_event_id
        or not isinstance(raw.get("groups"), list)
    ):
        return []
    return [
        dict(item)
        for item in raw["groups"]
        if isinstance(item, Mapping)
    ]


def _merge_react_detail_groups(
    accumulated: dict[str, dict[str, Any]],
    observed: Iterable[Mapping[str, Any]],
) -> None:
    """Merge progressive React snapshots by official market and odd IDs."""

    for row in observed:
        market = row.get("market")
        odds = row.get("odds")
        if not isinstance(market, Mapping) or not isinstance(odds, list):
            continue
        market_id = str(market.get("id") or "").strip()
        if not market_id:
            continue
        target = accumulated.setdefault(
            market_id,
            {"market": dict(market), "odds": []},
        )
        target_market = target.get("market")
        if isinstance(target_market, dict):
            target_market.update(
                {
                    key: value
                    for key, value in market.items()
                    if value is not None
                }
            )
        target_odds = target.get("odds")
        if not isinstance(target_odds, list):
            target_odds = []
        by_id = {
            str(odd.get("id")): dict(odd)
            for odd in target_odds
            if isinstance(odd, Mapping) and odd.get("id") is not None
        }
        for odd in odds:
            if isinstance(odd, Mapping) and odd.get("id") is not None:
                by_id[str(odd["id"])] = dict(odd)
        target["odds"] = list(by_id.values())


def _react_detail_group_signature(
    accumulated: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (market_id, str(odd.get("id")))
        for market_id, row in accumulated.items()
        for odd in row.get("odds", [])
        if isinstance(odd, Mapping) and odd.get("id") is not None
    ))


def _project_react_detail_groups(
    accumulated: Mapping[str, Mapping[str, Any]],
    home: str,
    away: str,
) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    for row in accumulated.values():
        markets.extend(_react_detail_markets_from_group(row, home, away))
    return markets


def extract_react_detail_markets(
    driver: Any, event_id: str, home: str, away: str
) -> list[dict[str, Any]]:
    """Extract exact currently rendered event-level React market records."""

    markets = []
    for item in extract_react_detail_groups(
        driver, event_id, home, away
    ):
        markets.extend(_react_detail_markets_from_group(item, home, away))
    return markets


def extract_supported_markets(
    driver: Any,
    home: str,
    away: str,
    *,
    event_id: str | None = None,
    wait_factory: Any = None,
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """Click supported tabs sequentially and isolate stale/timeout failures."""

    active_wait_factory = wait_factory or WebDriverWait

    markets: list[dict[str, Any]] = []
    accumulated_groups: dict[str, dict[str, Any]] = {}
    last_signature: tuple[tuple[str, str], ...] | None = None
    stable_signatures = 0
    scroll_complete = True

    expected_event_id = str(event_id or "").strip()

    def react_detail_ready(active: Any) -> list[dict[str, Any]] | bool:
        nonlocal markets, last_signature, stable_signatures, scroll_complete
        observed = extract_react_detail_groups(
            active, expected_event_id, home, away
        )
        _merge_react_detail_groups(accumulated_groups, observed)
        signature = _react_detail_group_signature(accumulated_groups)
        if signature and signature == last_signature:
            stable_signatures += 1
        else:
            stable_signatures = 0
        last_signature = signature
        markets = _project_react_detail_groups(
            accumulated_groups, home, away
        )
        try:
            scroll_state = active.execute_script(
                _ADVANCE_REACT_DETAIL_MARKETS_SCRIPT,
                expected_event_id,
            )
            if isinstance(scroll_state, Mapping):
                scroll_top = float(scroll_state.get("scrollTop") or 0)
                scroll_height = float(scroll_state.get("scrollHeight") or 0)
                client_height = float(scroll_state.get("clientHeight") or 0)
                scroll_complete = (
                    scroll_top + client_height >= scroll_height - 1
                )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            pass
        has_deep_market = any(
            market.get("key") in {"totals", "spreads"}
            for market in markets
        )
        has_source_market = any(
            market.get("key") == "source_market" for market in markets
        )
        if (
            stable_signatures >= 1
            and scroll_complete
            and (has_deep_market or has_source_market)
        ):
            return markets
        return False

    if expected_event_id:
        try:
            markets = active_wait_factory(driver, timeout).until(
                react_detail_ready
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            pass
    if markets and not any(
        market.get("key") == "spreads" for market in markets
    ):
        try:
            expanded = driver.execute_script(
                _EXPAND_REACT_SPREAD_MARKET_SCRIPT,
                sorted(SUPPORTED_BOX_TITLES["spreads"]),
            ) is True
            if expanded:
                def spread_ready(active: Any) -> list[dict[str, Any]] | bool:
                    result = react_detail_ready(active)
                    return (
                        result
                        if result and any(
                            market.get("key") == "spreads"
                            for market in result
                        )
                        else False
                    )

                markets = active_wait_factory(driver, timeout).until(
                    spread_ready
                )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            pass
    if markets:
        return markets
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
            was_active = driver.execute_script(
                _IS_MARKET_TAB_ACTIVE_SCRIPT, token
            ) is True
            previous_signature = None
            if not was_active:
                previous_signature = market_signature(driver)
                if driver.execute_script(_CLICK_MARKET_TAB_SCRIPT, token) is not True:
                    continue
            active_wait_factory(driver, timeout).until(
                lambda active: (
                    signature
                    if (signature := market_signature(active))
                    and active.execute_script(
                        _IS_MARKET_TAB_ACTIVE_SCRIPT, token
                    ) is True
                    and (
                        was_active
                        or signature != previous_signature
                    )
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


def _snapshot_h2h_market(
    raw: Mapping[str, Any],
    *,
    home: str,
    away: str,
    home_id: str,
    away_id: str,
) -> dict[str, Any] | None:
    market = raw.get("market")
    odds = raw.get("odds")
    if not isinstance(market, Mapping) or not isinstance(odds, list):
        return None
    try:
        title = _required_text(market.get("name"), "market title")
    except (TypeError, ValueError):
        return None
    if title.casefold() not in SUPPORTED_BOX_TITLES["h2h"]:
        return None

    declared_ids = market.get("oddIds")
    allowed_ids = (
        {str(value) for value in declared_ids}
        if isinstance(declared_ids, list)
        else set()
    )
    outcomes: dict[str, dict[str, Any]] = {}
    conflicted: set[str] = set()
    for odd in odds:
        if not isinstance(odd, Mapping) or odd.get("oddStatus") not in (None, 0):
            continue
        odd_id = str(odd.get("id") or "").strip()
        if allowed_ids and odd_id not in allowed_ids:
            continue
        competitor_id = str(odd.get("competitorId") or "").strip()
        name = str(odd.get("name") or "").strip()
        if competitor_id == home_id and name.casefold() == home.casefold():
            key = "home"
            normalized_name = home
        elif competitor_id == away_id and name.casefold() == away.casefold():
            key = "away"
            normalized_name = away
        elif (
            not competitor_id
            and name.casefold() in {"empate", "draw"}
            and odd.get("typeId") == 2
        ):
            key = "draw"
            normalized_name = name
        else:
            continue
        candidate = {
            "key": key,
            "name": normalized_name,
            "price": odd.get("price"),
        }
        previous = outcomes.get(key)
        if previous is None:
            outcomes[key] = candidate
        elif previous != candidate:
            outcomes.pop(key, None)
            conflicted.add(key)

    if conflicted or not {"home", "away"}.issubset(outcomes):
        return None
    ordered = [
        outcomes[key] for key in ("home", "draw", "away") if key in outcomes
    ]
    return {
        "key": "h2h",
        "title": title,
        "period": "full_game",
        "scope": "event",
        "outcomes": ordered,
    }


def _raw_event_from_snapshot(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    event = raw.get("event")
    sport = raw.get("sport")
    championship = raw.get("championship")
    competitors = raw.get("competitors")
    if not all(
        isinstance(value, Mapping) for value in (event, sport, championship)
    ) or not isinstance(competitors, list):
        return None
    if event.get("status") not in (None, 0):
        return None
    try:
        event_id = _required_text(str(event.get("id") or ""), "event_id")
        event_name = _required_text(event.get("name"), "event name")
        start_text = _required_text(event.get("startDate"), "startDate")
        sport_name = _required_text(
            sport.get("iconName") or sport.get("name"), "sport"
        )
        league = _required_text(championship.get("name"), "league")
        starts_at = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
        if starts_at.tzinfo is None or starts_at.utcoffset() is None:
            return None
    except (TypeError, ValueError):
        return None

    identity = re.fullmatch(r"\s*(.+?)\s+vs\.?\s+(.+?)\s*", event_name, re.I)
    if identity is None:
        return None
    home, away = (part.strip() for part in identity.groups())
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    for competitor in competitors:
        if not isinstance(competitor, Mapping):
            continue
        name = competitor.get("name")
        if isinstance(name, str) and name.strip():
            by_name.setdefault(name.strip().casefold(), []).append(competitor)
    home_matches = by_name.get(home.casefold(), [])
    away_matches = by_name.get(away.casefold(), [])
    if len(home_matches) != 1 or len(away_matches) != 1:
        return None
    home_id = str(home_matches[0].get("id") or "").strip()
    away_id = str(away_matches[0].get("id") or "").strip()
    if not home_id or not away_id or home_id == away_id:
        return None

    normalized_markets = []
    raw_markets = raw.get("markets")
    if isinstance(raw_markets, list):
        for raw_market in raw_markets:
            if not isinstance(raw_market, Mapping):
                continue
            market = _snapshot_h2h_market(
                raw_market,
                home=home,
                away=away,
                home_id=home_id,
                away_id=away_id,
            )
            if market is not None:
                normalized_markets.append(market)

    mexico_start = starts_at.astimezone(MEXICO)
    return {
        "event_id": event_id,
        "sport": sport_name,
        "league": league,
        "home": home,
        "away": away,
        "date_label": mexico_start.strftime("%d/%m"),
        "time_label": mexico_start.strftime("%H:%M"),
        "markets": normalized_markets,
    }


def _enrich_event_from_detail(
    driver: Any,
    record: dict[str, Any],
    *,
    wait_factory: Any,
    timeout: float,
    detail_cache: dict[
        tuple[str, str, str], tuple[dict[str, Any], ...]
    ] | None,
    detail_observed_at: datetime | None,
) -> bool:
    """Add bounded detail markets to one canonical raw record.

    The return value reports whether the detail was entered and inspected.  A
    caller holding verified snapshot markets can safely keep them when this
    returns false; a summary without markets can be discarded by its caller.
    """

    event_id = str(record["event_id"]).strip()
    home = str(record["home"]).strip()
    away = str(record["away"]).strip()
    if detail_observed_at is not None:
        try:
            observed = _mexico_observation(detail_observed_at)
            starts_at = resolve_mexico_start(
                str(record.get("date_label") or ""),
                str(record.get("time_label") or ""),
                observed,
            )
        except (TypeError, ValueError, OverflowError):
            return False
        if not (
            observed + timedelta(minutes=5)
            < starts_at
            <= observed + timedelta(hours=48)
        ):
            return False
    cache_key = (event_id, home.casefold(), away.casefold())
    if detail_cache is not None and cache_key in detail_cache:
        existing = record.get("markets")
        if not isinstance(existing, list):
            existing = []
        record["markets"] = [
            *existing,
            *deepcopy(detail_cache[cache_key]),
        ]
        return True
    try:
        entered_detail = driver.execute_script(
            _CLICK_EVENT_SCRIPT, event_id, home, away
        ) is True
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return False
    if not entered_detail:
        return False

    inspected = False
    try:
        details = extract_supported_markets(
            driver,
            home,
            away,
            event_id=event_id,
            wait_factory=wait_factory,
            timeout=timeout,
        )
        existing = record.get("markets")
        if not isinstance(existing, list):
            existing = []
        record["markets"] = [
            *existing,
            *(dict(item) for item in details if isinstance(item, Mapping)),
        ]
        if detail_cache is not None:
            detail_cache[cache_key] = tuple(
                deepcopy(dict(item))
                for item in details
                if isinstance(item, Mapping)
            )
        inspected = True
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        inspected = False
    finally:
        try:
            driver.execute_script(_RETURN_TO_EVENTS_SCRIPT)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            pass
        try:
            active_wait_factory = wait_factory or WebDriverWait
            active_wait_factory(driver, timeout).until(
                lambda active: active.execute_script(
                    _EVENT_LIST_READY_SCRIPT
                ) is True
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            pass
    return inspected


def extract_playdoit_raw_events(
    driver: Any,
    *,
    wait_factory: Any = None,
    timeout: float = 8.0,
    rejections: list[str] | None = None,
    detail_cache: dict[
        tuple[str, str, str], tuple[dict[str, Any], ...]
    ] | None = None,
    detail_observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Capture structured raw records without positional prices or defaults."""

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
        if isinstance(summary, Mapping) and isinstance(summary.get("event"), Mapping):
            record = _raw_event_from_snapshot(summary)
            if record is None:
                continue
            _enrich_event_from_detail(
                driver,
                record,
                wait_factory=wait_factory,
                timeout=timeout,
                detail_cache=detail_cache,
                detail_observed_at=detail_observed_at,
            )
            records.append(record)
            continue
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
        if _enrich_event_from_detail(
            driver,
            record,
            wait_factory=wait_factory,
            timeout=timeout,
            detail_cache=detail_cache,
            detail_observed_at=detail_observed_at,
        ):
            records.append(record)
    return records
