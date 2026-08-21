import { assertEquals } from "https://deno.land/std@0.224.0/assert/mod.ts";
import { subscriptionPatch } from "./subscription.ts";


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
});
