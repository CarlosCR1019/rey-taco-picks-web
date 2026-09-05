import {
  assertEquals,
  assertRejects,
} from "https://deno.land/std@0.224.0/assert/mod.ts";
import {
  buildTelegramDataCheckString,
  createTelegramMiniAppHandler,
  verifyTelegramInitData,
} from "./index.ts";

function bytes(value: Uint8Array): ArrayBuffer {
  return value.buffer.slice(
    value.byteOffset,
    value.byteOffset + value.byteLength,
  ) as ArrayBuffer;
}

async function signature(
  keyValue: string | Uint8Array,
  message: string,
): Promise<string> {
  const encoder = new TextEncoder();
  const keyBytes = typeof keyValue === "string"
    ? encoder.encode(keyValue)
    : keyValue;
  const key = await crypto.subtle.importKey(
    "raw",
    bytes(keyBytes),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const result = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return [...new Uint8Array(result)].map((byte) =>
    byte.toString(16).padStart(2, "0")
  ).join("");
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
  params.set(
    "hash",
    await signature(
      new Uint8Array(
        secret.match(/../g)!.map((part) => Number.parseInt(part, 16)),
      ),
      buildTelegramDataCheckString(params.toString()),
    ),
  );
  const identity = await verifyTelegramInitData(
    params.toString(),
    botToken,
    1000,
  );
  assertEquals(identity, { id: "123", username: "tester" });
});

async function signedInitData(
  userId: string,
  botToken: string,
  authDate = "1000",
): Promise<string> {
  const params = new URLSearchParams({
    auth_date: authDate,
    user: JSON.stringify({ id: userId }),
  });
  const secret = await signature("WebAppData", botToken);
  params.set(
    "hash",
    await signature(
      new Uint8Array(
        secret.match(/../g)!.map((part) => Number.parseInt(part, 16)),
      ),
      buildTelegramDataCheckString(params.toString()),
    ),
  );
  return params.toString();
}

Deno.test("rejects a correctly signed but expired payload", async () => {
  const value = await signedInitData("123", "bot-secret", "1000");
  await assertRejects(
    () => verifyTelegramInitData(value, "bot-secret", 5000),
    Error,
    "invalid telegram init data",
  );
});

function fakeAdmin(options: { linked: boolean; vip: boolean }) {
  let premiumSelect = "";
  const publicRows = [{
    partido: "Public A vs B",
    pick: "Public A",
    cuota: "1.80",
    categoria: "Futbol",
    estado: "pendiente",
    fecha_evento: "1970-01-01",
    source_starts_at: "1970-01-01T18:00:00.000Z",
  }];
  const premiumRows = [{
    partido: "Private C vs D",
    pick: "Private C",
    cuota: "1.90",
    categoria: "Beisbol",
    estado: "pendiente",
    fecha_evento: "1970-01-01",
    source_starts_at: "1970-01-01T18:00:00.000Z",
    horario: "12:00",
  }];
  const chain = (
    result: unknown,
    maybeSingle = false,
    trackPremium = false,
  ) => {
    const value = {
      select(fields: string) {
        if (trackPremium) premiumSelect = fields;
        return value;
      },
      eq() {
        return value;
      },
      in() {
        return value;
      },
      order() {
        return value;
      },
      limit() {
        return Promise.resolve(result);
      },
      maybeSingle() {
        return Promise.resolve(
          maybeSingle ? result : { data: null, error: null },
        );
      },
    };
    return value;
  };
  const admin = {
    from(table: string) {
      if (table === "profiles") {
        return chain({
          data: options.linked
            ? { id: "11111111-1111-1111-1111-111111111111" }
            : null,
          error: null,
        }, true);
      }
      if (table === "public_picks") {
        return chain({ data: publicRows, error: null });
      }
      if (table === "picks") {
        return chain({ data: premiumRows, error: null }, false, true);
      }
      throw new Error("unexpected table");
    },
    rpc() {
      return Promise.resolve({ data: options.vip, error: null });
    },
  };
  return { admin, premiumSelect: () => premiumSelect };
}

function miniAppRequest(initData: string): Request {
  return new Request(
    "https://example.supabase.co/functions/v1/telegram-mini-app",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "origin": "https://reytacopicks.com",
      },
      body: JSON.stringify({ initData }),
    },
  );
}

const TEST_ENV: Record<string, string> = {
  SITE_URL: "https://reytacopicks.com",
  TELEGRAM_BOT_TOKEN: "bot-secret",
  SUPABASE_URL: "https://example.supabase.co",
  SUPABASE_SERVICE_ROLE_KEY: "service-role",
};

Deno.test("unlinked users receive only a premium count", async () => {
  const fake = fakeAdmin({ linked: false, vip: false });
  const handler = createTelegramMiniAppHandler({
    createAdminClient: () => fake.admin,
    env: (name: string) => TEST_ENV[name],
    now: () => new Date("1970-01-01T12:00:00.000Z"),
    nowSeconds: () => 1000,
  });
  const response = await handler(
    miniAppRequest(await signedInitData("123", "bot-secret")),
  );
  const body = await response.json();
  assertEquals(response.status, 200);
  assertEquals(body.linked, false);
  assertEquals(body.is_vip, false);
  assertEquals(body.vip_count, 1);
  assertEquals(JSON.stringify(body).includes("Private C vs D"), false);
  assertEquals(fake.premiumSelect(), "source_starts_at,horario");
});

Deno.test("verified VIP users receive their premium rows", async () => {
  const fake = fakeAdmin({ linked: true, vip: true });
  const handler = createTelegramMiniAppHandler({
    createAdminClient: () => fake.admin,
    env: (name: string) => TEST_ENV[name],
    now: () => new Date("1970-01-01T12:00:00.000Z"),
    nowSeconds: () => 1000,
  });
  const response = await handler(
    miniAppRequest(await signedInitData("123", "bot-secret")),
  );
  const body = await response.json();
  assertEquals(response.status, 200);
  assertEquals(body.linked, true);
  assertEquals(body.is_vip, true);
  assertEquals(JSON.stringify(body).includes("Private C vs D"), true);
  assertEquals(fake.premiumSelect().includes("partido,pick,cuota"), true);
});
