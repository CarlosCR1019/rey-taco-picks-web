from datetime import datetime, timedelta, timezone


def _as_utc(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_active_subscription(record, now=None):
    now = _as_utc(now) or datetime.now(timezone.utc)
    period_end = _as_utc(record.get("current_period_end")) if record else None
    return bool(
        record
        and record.get("status") in {"active", "trialing"}
        and period_end
        and period_end > now
    )


def spei_subscription_record(user_id, existing_end=None, now=None):
    if not user_id:
        raise ValueError("user_id is required")
    now = _as_utc(now) or datetime.now(timezone.utc)
    current_end = _as_utc(existing_end)
    starts_at = current_end if current_end and current_end > now else now
    return {
        "user_id": user_id,
        "provider": "spei",
        "provider_subscription_id": f"spei-{user_id}",
        "status": "active",
        "current_period_end": (starts_at + timedelta(days=30)).isoformat(),
        "updated_at": now.isoformat(),
    }
