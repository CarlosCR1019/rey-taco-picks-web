import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.112.3";

export type TelegramIdentity = Readonly<{ id: string; username?: string }>;

const MAX_AGE_SECONDS = 60 * 60;
const MAX_FUTURE_SKEW_SECONDS = 60;
const PICK_FIELDS = "partido,pick,cuota,categoria,estado,source_starts_at,fecha_evento,horario";
const WINDOW_SLOTS = [0, 1, 2, 3] as const;

function invalidInitData(): never {
  throw new Error("invalid telegram init data");
}

export function buildTelegramDataCheckString(initData: string): string {
  if (typeof initData !== "string" || !initData) invalidInitData();
  return [...new URLSearchParams(initData).entries()]
    .filter(([key]) => key !== "hash")
    .sort(([leftKey, leftValue], [rightKey, rightValue]) => {
      if (leftKey !== rightKey) return leftKey < rightKey ? -1 : 1;
      if (leftValue === rightValue) return 0;
      return leftValue < rightValue ? -1 : 1;
    })
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

function hex(value: ArrayBuffer): string {
  return [...new Uint8Array(value)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function equalHex(left: string, right: string): boolean {
  if (!/^[0-9a-f]{64}$/i.test(left) || !/^[0-9a-f]{64}$/i.test(right)) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

async function signHmac(keyBytes: Uint8Array, message: string): Promise<ArrayBuffer> {
  const stableKey = new Uint8Array(keyBytes.byteLength);
  stableKey.set(keyBytes);
  const key = await crypto.subtle.importKey(
    "raw",
    stableKey.buffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
}

export async function verifyTelegramInitData(
  initData: string,
  botToken: string,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<TelegramIdentity> {
  try {
    if (typeof initData !== "string" || !initData || typeof botToken !== "string" || !botToken) invalidInitData();
    const params = new URLSearchParams(initData);
    const hash = params.get("hash") ?? "";
    const authDate = params.get("auth_date") ?? "";
    if (params.getAll("hash").length !== 1 || params.getAll("auth_date").length !== 1 || !/^\d+$/.test(authDate)) invalidInitData();
    const authTimestamp = Number(authDate);
    if (!Number.isSafeInteger(authTimestamp) || authTimestamp <= 0 || nowSeconds - authTimestamp > MAX_AGE_SECONDS || authTimestamp - nowSeconds > MAX_FUTURE_SKEW_SECONDS) invalidInitData();
    const secret = new Uint8Array(await signHmac(new TextEncoder().encode("WebAppData"), botToken));
    const expected = hex(await signHmac(secret, buildTelegramDataCheckString(initData)));
    if (!equalHex(hash, expected)) invalidInitData();
    const userValue = params.get("user");
    if (!userValue) invalidInitData();
    const user = JSON.parse(userValue) as { id?: unknown; username?: unknown };
    if (!user || (typeof user.id !== "string" && typeof user.id !== "number") || String(user.id).trim() === "") invalidInitData();
    return {
      id: String(user.id),
      ...(typeof user.username === "string" && user.username ? { username: user.username } : {}),
    };
  } catch {
    throw new Error("invalid telegram init data");
  }
}

function mexicoDateKey(now: Date): string {
  const values = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Mexico_City",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function slotFromRow(row: Record<string, unknown>): number | null {
  const source = typeof row.source_starts_at === "string" ? new Date(row.source_starts_at) : null;
  if (source && !Number.isNaN(source.getTime())) {
    const hour = Number(new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Mexico_City",
      hour: "2-digit",
      hourCycle: "h23",
    }).format(source));
    return Math.min(3, Math.floor(hour / 6));
  }
  const match = /^(?:[01]\d|2[0-3]):[0-5]\d$/.exec(String(row.horario ?? ""));
  return match ? Math.min(3, Math.floor(Number(String(row.horario).slice(0, 2)) / 6)) : null;
}

function safePick(row: Record<string, unknown>): Record<string, unknown> {
  return {
    partido: String(row.partido ?? "Evento por confirmar"),
    pick: String(row.pick ?? "Selección por confirmar"),
    cuota: row.cuota ?? "—",
    categoria: String(row.categoria ?? "Deportes"),
    estado: String(row.estado ?? "pendiente"),
    source_starts_at: String(row.source_starts_at ?? ""),
  };
}

function publicOrigin(request: Request, siteUrl: string): string {
  const origin = request.headers.get("Origin") ?? "";
  if (!origin) return siteUrl;
  const allowed = new Set([siteUrl, "https://telegram.org", "https://web.telegram.org"]);
  return allowed.has(origin) ? origin : "";
}

function headers(request: Request, siteUrl: string): Headers {
  const origin = publicOrigin(request, siteUrl);
  return new Headers({
    "Access-Control-Allow-Origin": origin || siteUrl,
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
    "Content-Type": "application/json; charset=utf-8",
  });
}

function jsonResponse(request: Request, siteUrl: string, value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: headers(request, siteUrl) });
}

function groupRows(rows: Record<string, unknown>[], date: string) {
  const windows = WINDOW_SLOTS.map((slot) => ({ slot, picks: [] as Record<string, unknown>[], vip_count: 0 }));
  for (const row of rows) {
    if (String(row.fecha_evento ?? date) !== date) continue;
    const slot = slotFromRow(row);
    if (slot !== null) windows[slot].picks.push(safePick(row));
  }
  return windows;
}

function countPremiumBySlot(rows: Record<string, unknown>[]) {
  const windows = WINDOW_SLOTS.map(() => 0);
  for (const row of rows) {
    const slot = slotFromRow(row);
    if (slot !== null) windows[slot] += 1;
  }
  return windows;
}

async function handle(request: Request): Promise<Response> {
  const siteUrl = (Deno.env.get("SITE_URL") ?? "https://reytacopicks.com").replace(/\/$/, "");
  const responseHeaders = headers(request, siteUrl);
  const origin = request.headers.get("Origin");
  if (origin && !publicOrigin(request, siteUrl)) return new Response("Request rejected", { status: 403, headers: responseHeaders });
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: responseHeaders });
  if (request.method !== "POST" || !(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/json")) {
    return new Response("Request rejected", { status: 405, headers: responseHeaders });
  }

  try {
    const body = await request.json() as { initData?: unknown };
    if (typeof body.initData !== "string") throw new Error("invalid request");
    const identity = await verifyTelegramInitData(body.initData, Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "");
    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
    if (!supabaseUrl || !serviceRoleKey) throw new Error("server configuration unavailable");
    const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false } });
    const date = mexicoDateKey(new Date());

    const profile = await admin.from("profiles").select("id").eq("telegram_id", identity.id).maybeSingle();
    const linked = !profile.error && Boolean(profile.data?.id);
    let isVip = false;
    if (linked) {
      const membership = await admin.rpc("is_active_subscriber", { check_user: profile.data!.id });
      isVip = !membership.error && membership.data === true;
    }

    const publicResult = await admin.from("public_picks")
      .select(PICK_FIELDS)
      .eq("fecha_evento", date)
      .eq("estado", "pendiente")
      .eq("active", true)
      .order("source_starts_at", { ascending: true })
      .limit(24);
    if (publicResult.error) throw new Error("public picks unavailable");

    const premiumResult = await admin.from("picks")
      .select(isVip ? PICK_FIELDS : "source_starts_at,horario")
      .eq("fecha_evento", date)
      .eq("estado", "pendiente")
      .eq("visibility", "premium")
      .eq("active", true)
      .order("source_starts_at", { ascending: true })
      .limit(24);
    if (premiumResult.error) throw new Error("premium count unavailable");

    const premiumRows = (premiumResult.data ?? []) as unknown as Record<string, unknown>[];
    const windows = groupRows((publicResult.data ?? []) as Record<string, unknown>[], date);
    const premiumCounts = countPremiumBySlot(premiumRows);
    for (const slot of WINDOW_SLOTS) {
      windows[slot].vip_count = premiumCounts[slot];
      if (isVip) windows[slot].picks.push(...premiumRows.filter((row) => slotFromRow(row) === slot).map(safePick));
    }

    const historyResult = await admin.from("public_picks")
      .select(PICK_FIELDS)
      .in("estado", ["ganado", "perdido", "void", "revision_pendiente"])
      .order("id", { ascending: false })
      .limit(10);
    if (historyResult.error) throw new Error("history unavailable");

    return jsonResponse(request, siteUrl, {
      date,
      windows,
      history: ((historyResult.data ?? []) as Record<string, unknown>[]).map(safePick),
      linked,
      is_vip: isVip,
      vip_count: premiumRows.length,
    });
  } catch {
    return new Response("Unable to load mini app", { status: 400, headers: responseHeaders });
  }
}

if (import.meta.main) serve(handle);

export { handle };
