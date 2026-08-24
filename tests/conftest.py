from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.scraper_domain import Event, Market, Outcome


MEXICO = ZoneInfo("America/Mexico_City")
OBSERVED = datetime(2026, 8, 20, 10, tzinfo=MEXICO)


@pytest.fixture
def event_fixture() -> Event:
    return Event(
        source="playdoit",
        source_event_id="event-1",
        sport="soccer",
        league="Liga MX",
        home_team="América",
        away_team="Tigres",
        starts_at=OBSERVED + timedelta(hours=8),
        observed_at=OBSERVED,
        markets=(
            Market(
                "h2h",
                "full_game",
                None,
                (
                    Outcome("home", "América", 1.72),
                    Outcome("draw", "Empate", 3.25),
                    Outcome("away", "Tigres", 2.35),
                ),
                bookmaker_key="playdoit",
            ),
        ),
    )


@pytest.fixture
def partial_market_event() -> Event:
    return Event(
        source="playdoit",
        source_event_id="event-2",
        sport="baseball",
        league="MLB",
        home_team="Dodgers",
        away_team="Padres",
        starts_at=OBSERVED + timedelta(hours=10),
        observed_at=OBSERVED,
        markets=(
            Market(
                "totals",
                "first_inning",
                0.5,
                (
                    Outcome("over", "Más de 0.5", 1.80),
                    Outcome("under", "Menos de 0.5", 2.00),
                ),
                bookmaker_key="playdoit",
            ),
        ),
    )
