export type SubscriptionRecord = {
  provider: "stripe";
  provider_customer_id: string;
  provider_subscription_id: string;
  status: "incomplete" | "trialing" | "active" | "past_due" | "canceled" | "expired";
  current_period_end: string | null;
};

export function shouldPersistSubscription(type: string, object: Record<string, unknown> = {}): boolean {
  // Access begins from a paid invoice or an authoritative subscription event.
  // Persisting checkout.completed could arrive after invoice.paid and downgrade access.
  if (type !== "checkout.session.completed") return true;
  return object.mode === "payment" && object.payment_status === "paid";
}


function unixPeriodEnd(object: Record<string, unknown>): number | null {
  if (typeof object.current_period_end === "number") return object.current_period_end;
  const lines = object.lines as { data?: Array<{ period?: { end?: number } }> } | undefined;
  return lines?.data?.[0]?.period?.end ?? null;
}

function unixWeeklyPeriodEnd(object: Record<string, unknown>): number | null {
  if (object.mode !== "payment" || object.payment_status !== "paid") return null;
  const created = typeof object.created === "number" ? object.created : null;
  return created === null ? null : created + 7 * 24 * 60 * 60;
}


function normalizedStatus(type: string, object: Record<string, unknown>): SubscriptionRecord["status"] {
  // The webhook handler retrieves the subscription again from Stripe. When
  // that authoritative object has a status, it wins over the delivery order
  // of invoice events.
  const stripeStatus = String(object.status ?? "");
  if (["trialing", "active", "past_due", "canceled", "incomplete"].includes(stripeStatus)) {
    return stripeStatus as SubscriptionRecord["status"];
  }
  if (["unpaid", "paused"].includes(stripeStatus)) return "past_due";
  if (stripeStatus === "incomplete_expired") return "expired";

  const eventStatus: Record<string, SubscriptionRecord["status"]> = {
    "checkout.session.completed": "incomplete",
    "invoice.paid": "active",
    "invoice.payment_failed": "past_due",
    "customer.subscription.deleted": "canceled",
  };
  if (eventStatus[type]) return eventStatus[type];

  return "incomplete";
}


export function subscriptionPatch(
  type: string,
  object: Record<string, unknown>,
): SubscriptionRecord {
  const periodEnd = unixPeriodEnd(object) ?? unixWeeklyPeriodEnd(object);
  return {
    provider: "stripe",
    provider_customer_id: String(object.customer ?? ""),
    provider_subscription_id: String(object.subscription ?? object.id ?? ""),
    status: type === "checkout.session.completed" && object.mode === "payment" && object.payment_status === "paid"
      ? "active"
      : normalizedStatus(type, object),
    current_period_end: periodEnd ? new Date(periodEnd * 1000).toISOString() : null,
  };
}
