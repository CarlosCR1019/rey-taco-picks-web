import { currentMexicoBlockIndex, mexicoDateKey } from '../domain/timeBlocks';

export type MiniAppStatus = 'Cerrado' | 'En curso' | 'Próximo' | 'Sin selección';
export type MiniAppSlot = 0 | 1 | 2 | 3;

export type MiniAppPick = Readonly<{
  partido: string;
  pick: string;
  cuota: string | number;
  categoria: string;
  estado: string;
  source_starts_at: string;
}>;

export type MiniAppWindowSeed = Readonly<{
  slot: MiniAppSlot;
  picks: readonly Record<string, unknown>[];
  vip_count?: number;
}>;

export type MiniAppWindow = Readonly<{
  slot: MiniAppSlot;
  label: string;
  status: MiniAppStatus;
  picks: readonly MiniAppPick[];
  vip_count: number;
}>;

export type MiniAppDto = Readonly<{
  date: string;
  windows: readonly MiniAppWindow[];
  history: readonly MiniAppPick[];
  linked: boolean;
  is_vip: boolean;
  vip_count: number;
}>;

type MiniAppInput = Readonly<{
  date: string;
  windows: readonly MiniAppWindowSeed[];
  history?: readonly Record<string, unknown>[];
  linked?: boolean;
  is_vip?: boolean;
  vip_count?: number;
}>;

const WINDOW_LABELS = ['12am–6am', '6am–12pm', '12pm–6pm', '6pm–12am'] as const;
const PUBLIC_PICK_FIELDS = ['partido', 'pick', 'cuota', 'categoria', 'estado', 'source_starts_at'] as const;

export function isTelegramMiniAppLocation(
  location: Pick<Location, 'pathname' | 'search' | 'hash'> | URL,
  configuredRoute = '/telegram',
): boolean {
  const query = new URLSearchParams(location.search);
  if (query.get('view') === 'telegram' || location.hash === '#telegram') return true;
  const configured = new URL(configuredRoute || '/telegram', 'https://reytacopicks.com');
  const currentPath = location.pathname.replace(/\/$/, '') || '/';
  const configuredPath = configured.pathname.replace(/\/$/, '') || '/';
  return currentPath === configuredPath && (!configured.search || location.search === configured.search);
}

function isSlot(value: unknown): value is MiniAppSlot {
  return value === 0 || value === 1 || value === 2 || value === 3;
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

function publicPick(value: Record<string, unknown>): MiniAppPick | null {
  if (value.visibility === 'premium') return null;
  return {
    partido: text(value.partido, 'Evento por confirmar'),
    pick: text(value.pick, 'Selección por confirmar'),
    cuota: typeof value.cuota === 'string' || typeof value.cuota === 'number' ? value.cuota : '—',
    categoria: text(value.categoria, 'Deportes'),
    estado: text(value.estado, 'pendiente'),
    source_starts_at: text(value.source_starts_at),
  };
}

function normalizedPicks(values: readonly Record<string, unknown>[]): MiniAppPick[] {
  return values.map(publicPick).filter((value): value is MiniAppPick => value !== null);
}

function safeCount(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : 0;
}

export function miniAppWindowState(nowIso: string, dateKey: string, slotIndex: number): MiniAppStatus {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey) || !isSlot(slotIndex)) return 'Sin selección';
  const now = new Date(nowIso);
  if (Number.isNaN(now.getTime())) return 'Sin selección';
  const nowDate = mexicoDateKey(now);
  if (dateKey < nowDate) return 'Cerrado';
  if (dateKey > nowDate) return 'Próximo';
  const current = currentMexicoBlockIndex(now);
  if (slotIndex < current) return 'Cerrado';
  if (slotIndex === current) return 'En curso';
  return 'Próximo';
}

export function publicMiniAppDto(input: MiniAppInput, nowIso = new Date().toISOString()): MiniAppDto {
  const bySlot = new Map<MiniAppSlot, MiniAppWindowSeed>();
  for (const seed of input.windows) {
    if (isSlot(seed.slot) && !bySlot.has(seed.slot)) bySlot.set(seed.slot, seed);
  }
  const windows = ([0, 1, 2, 3] as MiniAppSlot[]).map((slot) => {
    const seed = bySlot.get(slot);
    const picks = normalizedPicks(seed?.picks ?? []);
    return {
      slot,
      label: WINDOW_LABELS[slot],
      status: picks.length ? miniAppWindowState(nowIso, input.date, slot) : 'Sin selección' as const,
      picks,
      vip_count: safeCount(seed?.vip_count),
    };
  });
  const history = normalizedPicks(input.history ?? []).slice(0, 10);
  return {
    date: input.date,
    windows,
    history,
    linked: input.linked === true,
    is_vip: input.is_vip === true,
    vip_count: safeCount(input.vip_count) || windows.reduce((total, window) => total + window.vip_count, 0),
  };
}

function escapeHtml(value: unknown): string {
  return text(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function pickMarkup(pick: MiniAppPick): string {
  return `<article class="telegram-pick-card"><span>${escapeHtml(pick.categoria)}</span><h3>${escapeHtml(pick.partido)}</h3><div><strong>${escapeHtml(pick.pick)}</strong><b>@ ${escapeHtml(pick.cuota)}</b></div></article>`;
}

export function renderTelegramMiniApp(dto: MiniAppDto, botUsername = ''): string {
  const bot = botUsername.trim().replace(/^@/, '');
  const cta = bot ? `https://t.me/${encodeURIComponent(bot)}?startapp=${encodeURIComponent('telegram')}` : '#telegram-mini-app';
  const windows = dto.windows.map((window) => `
    <article class="telegram-window telegram-window-${window.slot}">
      <header><div><span>Ventana ${window.slot + 1}</span><h3>${escapeHtml(window.label)}</h3></div><strong>${escapeHtml(window.status)}</strong></header>
      <div class="telegram-pick-list">${window.picks.length ? window.picks.map(pickMarkup).join('') : '<p class="telegram-empty">Sin selección todavía.</p>'}</div>
    </article>`).join('');
  const history = dto.history.length
    ? dto.history.map((pick) => `<li><span>${escapeHtml(pick.partido)}</span><strong>${escapeHtml(pick.estado)}</strong></li>`).join('')
    : '<li class="telegram-empty">Aún no hay resultados para mostrar.</li>';
  const vipCopy = dto.is_vip ? 'Acceso VIP activo' : `${dto.vip_count} selecciones premium preparadas`;
  return `<section class="telegram-app" aria-labelledby="telegram-app-title">
    <header class="telegram-app-header"><a href="/" aria-label="Volver a Rey Taco Picks">←</a><div><span>REY TACO PICKS</span><h1 id="telegram-app-title">Tu cartelera, de un vistazo</h1></div><span class="telegram-live-pill">+18</span></header>
    <div class="telegram-current"><span class="telegram-kicker">Hoy · CDMX</span><strong>${escapeHtml(dto.date)}</strong><p>Cuatro ventanas para consultar qué está listo y qué ya cerró.</p></div>
    <div class="telegram-windows">${windows}</div>
    <section class="telegram-vip-card"><div><span class="telegram-kicker">Cartera completa</span><h2>${escapeHtml(vipCopy)}</h2><p>${dto.is_vip ? 'Tus selecciones premium aparecen en sus ventanas.' : 'Vincula tu cuenta y conoce la cartera premium cuando corresponda.'}</p></div><a href="${escapeHtml(cta)}" target="_blank" rel="noopener noreferrer">${dto.is_vip ? 'Abrir canal VIP' : 'Conocer VIP'}</a></section>
    <section class="telegram-history"><div><span class="telegram-kicker">Transparencia</span><h2>Últimos resultados</h2></div><ul>${history}</ul></section>
    <footer class="telegram-footer"><span>Juego responsable · No garantizamos ganancias.</span><a href="${escapeHtml(cta)}" target="_blank" rel="noopener noreferrer">Abrir Telegram</a></footer>
  </section>`;
}

type TelegramWebApp = { initData?: string; ready?: () => void };

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

type MiniAppInitOptions = Readonly<{
  endpoint?: string;
  botUsername?: string;
  initData?: string;
  fetchImpl?: typeof fetch;
  sdkLoader?: () => Promise<void>;
}>;

const TELEGRAM_SDK_ID = 'telegram-web-app-sdk';
const TELEGRAM_SDK_URL = 'https://telegram.org/js/telegram-web-app.js?63';
let telegramSdkPromise: Promise<void> | null = null;

export function loadTelegramWebAppSdk(): Promise<void> {
  if (window.Telegram?.WebApp) return Promise.resolve();
  if (telegramSdkPromise) return telegramSdkPromise;
  telegramSdkPromise = new Promise((resolve) => {
    const existing = document.getElementById(TELEGRAM_SDK_ID) as HTMLScriptElement | null;
    const script = existing ?? document.createElement('script');
    const finish = () => resolve();
    script.addEventListener('load', finish, { once: true });
    script.addEventListener('error', finish, { once: true });
    if (!existing) {
      script.id = TELEGRAM_SDK_ID;
      script.src = TELEGRAM_SDK_URL;
      document.head.appendChild(script);
    }
  });
  return telegramSdkPromise;
}

function unavailableMarkup(botUsername: string): string {
  const dto = publicMiniAppDto({ date: mexicoDateKey(new Date()), windows: [] });
  return `${renderTelegramMiniApp(dto, botUsername)}<p class="telegram-auth-note">Abre esta vista desde Telegram para cargar tu cartelera.</p>`;
}

export async function initTelegramMiniApp(root: HTMLElement, options: MiniAppInitOptions = {}): Promise<MiniAppDto | null> {
  if (!options.initData) await (options.sdkLoader ?? loadTelegramWebAppSdk)();
  const webApp = window.Telegram?.WebApp;
  webApp?.ready?.();
  const initData = options.initData ?? webApp?.initData ?? '';
  if (!initData) {
    root.innerHTML = unavailableMarkup(options.botUsername ?? '');
    return null;
  }
  const endpoint = options.endpoint || `${import.meta.env.VITE_SUPABASE_URL ?? ''}/functions/v1/telegram-mini-app`;
  if (!endpoint || endpoint.startsWith('/functions') === false && !/^https?:\/\//.test(endpoint)) {
    root.innerHTML = '<p class="telegram-auth-note">La Mini App no está configurada todavía.</p>';
    return null;
  }
  try {
    const response = await (options.fetchImpl ?? fetch)(endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ initData }),
    });
    if (!response.ok) throw new Error('mini app request failed');
    const raw = await response.json() as MiniAppInput;
    const dto = publicMiniAppDto(raw);
    root.innerHTML = renderTelegramMiniApp(dto, options.botUsername ?? '');
    return dto;
  } catch {
    root.innerHTML = '<p class="telegram-auth-note">No pudimos cargar la cartelera. Intenta de nuevo desde Telegram.</p>';
    return null;
  }
}

export const MINI_APP_PUBLIC_PICK_FIELDS = PUBLIC_PICK_FIELDS;
