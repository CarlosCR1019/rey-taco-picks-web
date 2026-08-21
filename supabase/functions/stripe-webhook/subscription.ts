export type SubscriptionRecord = {
  provider: "stripe";
  provider_customer_id: string;
  provider_subscription_id: string;
  status: "incomplete" | "trialing" | "active" | "past_due" | "canceled" | "expired";
  current_period_end: string | null;
};


function unixPeriodEnd(object: Record<string, unknown>): number | null {
  if (typeof object.current_period_end === "number") return object.current_period_end;
  const lines = object.lines as { data?: Array<{ period?: { end?: number } }> } | undefined;
  return lines?.data?.[0]?.period?.end ?? null;
}


function normalizedStatus(type: string, object: Record<string, unknown>): SubscriptionRecord["status"] {
  const eventStatus: Record<string, SubscriptionRecord["status"]> = {
    "checkout.session.completed": "incomplete",
    "invoice.paid": "active",
    "invoice.payment_failed": "past_due",
    "customer.subscription.deleted": "canceled",
  };
  if (eventStatus[type]) return eventStatus[type];

  const stripeStatus = String(object.status ?? "incomplete");
  if (["trialing", "active", "past_due", "canceled", "incomplete"].includes(stripeStatus)) {
    return stripeStatus as SubscriptionRecord["status"];
  }
  if (["unpaid", "paused"].includes(stripeStatus)) return "past_due";
  if (stripeStatus === "incomplete_expired") return "expired";
  return "incomplete";
}


export function subscriptionPatch(
  type: string,
  object: Record<string, unknown>,
): SubscriptionRecord {
  const periodEnd = unixPeriodEnd(object);
  return {
    provider: "stripe",
    provider_customer_id: String(object.customer ?? ""),
    provider_subscription_id: String(object.subscription ?? object.id ?? ""),
    status: normalizedStatus(type, object),
    current_period_end: periodEnd ? new Date(periodEnd * 1000).toISOString() : null,
  };
}
