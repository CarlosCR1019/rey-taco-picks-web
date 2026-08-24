from copy import deepcopy
from datetime import date, timedelta
import re


def expected_public_pick_count(total):
    """Return the exact free-pick count for a bounded daily batch."""
    if type(total) is not int or total < 1 or total > 6:
        return 0
    return 2 if total == 6 else 1


def _physical_event_identity(pick, index):
    source = pick.get("source")
    source_event_id = pick.get("source_event_id")
    if (
        isinstance(source, str)
        and source.strip()
        and isinstance(source_event_id, str)
        and source_event_id.strip()
    ):
        return ("source", source.strip().casefold(), source_event_id.strip())

    partido = pick.get("partido")
    if isinstance(partido, str) and partido.strip():
        return ("partido", " ".join(partido.casefold().split()))

    pick_id = pick.get("id")
    if isinstance(pick_id, (str, int)) and not isinstance(pick_id, bool):
        return ("id", str(pick_id))
    return ("row", index)


def assign_visibility(picks):
    """Apply the exact free allocation without repeating a physical match."""
    result = deepcopy(picks)
    public_target = expected_public_pick_count(len(result))
    public_events = set()
    for index, pick in enumerate(result):
        pick["visibility"] = "premium"
        event_identity = _physical_event_identity(pick, index)
        if (
            len(public_events) < public_target
            and not bool(pick.get("es_parlay"))
            and event_identity not in public_events
        ):
            pick["visibility"] = "public"
            public_events.add(event_identity)
    return result


def public_payload(picks):
    """Data that may safely be copied into the web server's public directory."""
    return [deepcopy(pick) for pick in picks if pick.get("visibility") == "public"]


def scheduled_event_date(label, generated_date):
    """Resolve the event's Mexico calendar date from the scraper label."""
    generated = date.fromisoformat(str(generated_date)[:10])
    text = str(label or "").lower()
    explicit = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if explicit:
        return explicit.group(0)
    day_month = re.search(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})(?!\d)", text)
    if day_month:
        day, month = (int(value) for value in day_month.groups())
        try:
            scheduled = date(generated.year, month, day)
            if scheduled < generated:
                scheduled = date(generated.year + 1, month, day)
            return scheduled.isoformat()
        except ValueError:
            pass
    if "mañana" in text or "manana" in text or "tomorrow" in text:
        return (generated + timedelta(days=1)).isoformat()
    return generated.isoformat()


def event_labels_share_date(labels, generated_date):
    """True only when every parlay leg resolves to one Mexico calendar day."""
    resolved = [scheduled_event_date(label, generated_date) for label in labels]
    return len(resolved) >= 2 and len(set(resolved)) == 1
