import { assertEquals, assertThrows } from "jsr:@std/assert";
import { checkoutParams } from "./checkout.ts";

Deno.test("creates a monthly subscription bound to the signed-in user", () => {
  const params = checkoutParams("user-1", "cliente@example.com", "price_123", "https://reytacopicks.com");
  assertEquals(params.mode, "subscription");
  assertEquals(params.client_reference_id, "user-1");
  assertEquals(params.subscription_data.metadata.user_id, "user-1");
  assertEquals(params.line_items, [{ price: "price_123", quantity: 1 }]);
});

Deno.test("refuses incomplete server configuration", () => {
  assertThrows(() => checkoutParams("", "a@b.com", "price_123", "https://reytacopicks.com"));
  assertThrows(() => checkoutParams("user-1", "a@b.com", "", "https://reytacopicks.com"));
});
