from copy import deepcopy
from datetime import date, timedelta
import re


def assign_visibility(picks):
    """Return picks with one useful free selection and every other pick premium."""
    result = deepcopy(picks)
    public_assigned = False
    for pick in result:
        is_public = not public_assigned and not bool(pick.get("es_parlay"))
        pick["visibility"] = "public" if is_public else "premium"
        public_assigned = public_assigned or is_public
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
