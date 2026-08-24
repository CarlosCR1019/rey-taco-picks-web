import { assertEquals, assertThrows } from "jsr:@std/assert";
import { portalParams } from "./portal.ts";

Deno.test("builds a Stripe portal session for a known customer", () => {
  assertEquals(portalParams("cus_123", "https://reytacopicks.com/"), {
    customer: "cus_123",
    return_url: "https://reytacopicks.com",
  });
});

Deno.test("refuses a missing Stripe customer", () => {
  assertThrows(() => portalParams("", "https://reytacopicks.com"));
});
