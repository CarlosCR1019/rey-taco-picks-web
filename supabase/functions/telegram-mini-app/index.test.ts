import { assertEquals, assertRejects } from "https://deno.land/std@0.224.0/assert/mod.ts";
import { buildTelegramDataCheckString, verifyTelegramInitData } from "./index.ts";

function bytes(value: Uint8Array): ArrayBuffer {
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer;
}

async function signature(keyValue: string | Uint8Array, message: string): Promise<string> {
  const encoder = new TextEncoder();
  const keyBytes = typeof keyValue === "string" ? encoder.encode(keyValue) : keyValue;
  const key = await crypto.subtle.importKey("raw", bytes(keyBytes), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const result = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return [...new Uint8Array(result)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

Deno.test("sorts fields and ignores hash while building the check string", () => {
  assertEquals(
    buildTelegramDataCheckString("z=2&auth_date=10&hash=ignored&a=1"),
    "a=1\nauth_date=10\nz=2",
  );
});

Deno.test("rejects stale or tampered payloads", async () => {
  await assertRejects(
    () => verifyTelegramInitData("auth_date=1&hash=bad", "bot-secret", 1000),
    Error,
    "invalid telegram init data",
  );
});

Deno.test("accepts a correctly signed user without returning initData", async () => {
  const botToken = "test-bot-token";
  const params = new URLSearchParams({
    auth_date: "1000",
    user: JSON.stringify({ id: 123, username: "tester" }),
  });
  const secret = await signature("WebAppData", botToken);
  params.set("hash", await signature(new Uint8Array(secret.match(/../g)!.map((part) => Number.parseInt(part, 16))), buildTelegramDataCheckString(params.toString())));
  const identity = await verifyTelegramInitData(params.toString(), botToken, 1000);
  assertEquals(identity, { id: "123", username: "tester" });
});
