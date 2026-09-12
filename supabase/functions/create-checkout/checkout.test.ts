import { assertEquals, assertThrows } from "jsr:@std/assert";
import { checkoutParams } from "./checkout.ts";

Deno.test("creates a monthly subscription bound to the signed-in user", () => {
  const params = checkoutParams("user-1", "cliente@example.com", "price_monthly", "https://reytacopicks.com", "subscription");
  assertEquals(params.mode, "subscription");
  assertEquals(params.client_reference_id, "user-1");
  assertEquals(params.subscription_data.metadata.user_id, "user-1");
  assertEquals(params.line_items, [{ price: "price_monthly", quantity: 1 }]);
});

Deno.test("creates a one-time weekly pass without subscription metadata", () => {
  const params = checkoutParams("user-1", "cliente@example.com", "price_weekly", "https://reytacopicks.com", "payment");
  assertEquals(params.mode, "payment");
  assertEquals(params.line_items, [{ price: "price_weekly", quantity: 1 }]);
  assertEquals(params.metadata, { user_id: "user-1" });
  assertEquals("subscription_data" in params, false);
});

Deno.test("refuses incomplete server configuration", () => {
  assertThrows(() => checkoutParams("", "a@b.com", "price_123", "https://reytacopicks.com", "subscription"));
  assertThrows(() => checkoutParams("user-1", "a@b.com", "", "https://reytacopicks.com", "subscription"));
  assertThrows(() => checkoutParams("user-1", "a@b.com", "price_123", "https://reytacopicks.com", "invalid" as never));
});
