import { assertEquals } from "https://deno.land/std@0.224.0/assert/mod.ts";
import { shouldPersistSubscription, subscriptionPatch } from "./subscription.ts";


Deno.test("paid invoice activates access", () => {
  const patch = subscriptionPatch("invoice.paid", {
    customer: "cus_1",
    subscription: "sub_1",
    lines: { data: [{ period: { end: 4_102_444_800 } }] },
  });
  assertEquals(patch.status, "active");
  assertEquals(patch.provider_subscription_id, "sub_1");
});

Deno.test("failed invoice removes active access", () => {
  assertEquals(
    subscriptionPatch("invoice.payment_failed", { customer: "cus_1", subscription: "sub_1" }).status,
    "past_due",
  );
});

Deno.test("a delayed failed invoice cannot override Stripe's current active status", () => {
  assertEquals(subscriptionPatch("invoice.payment_failed", {
    customer: "cus_1", subscription: "sub_1", status: "active",
  }).status, "active");
});

Deno.test("deleted subscription is cancelled", () => {
  assertEquals(
    subscriptionPatch("customer.subscription.deleted", { customer: "cus_1", id: "sub_1" }).status,
    "canceled",
  );
});

Deno.test("checkout alone does not grant permanent access", () => {
  assertEquals(
    subscriptionPatch("checkout.session.completed", { customer: "cus_1", subscription: "sub_1" }).status,
    "incomplete",
  );
  assertEquals(shouldPersistSubscription("checkout.session.completed"), false);
});

Deno.test("paid weekly checkout grants seven days and uses the session as its idempotency key", () => {
  const created = 1_757_000_000;
  const patch = subscriptionPatch("checkout.session.completed", {
    id: "cs_weekly_1",
    customer: "cus_1",
    mode: "payment",
    payment_status: "paid",
    created,
    metadata: { user_id: "user-1" },
  });
  assertEquals(shouldPersistSubscription("checkout.session.completed", {
    mode: "payment", payment_status: "paid",
  }), true);
  assertEquals(patch.status, "active");
  assertEquals(patch.provider_subscription_id, "cs_weekly_1");
  assertEquals(patch.current_period_end, new Date((created + 7 * 24 * 60 * 60) * 1000).toISOString());
});
