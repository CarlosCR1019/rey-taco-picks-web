import './style.css';
import type { User } from '@supabase/supabase-js';
import { renderShell } from './app/render';
import { visibleHistory } from './app/history';
import { publicCounterLabel } from './app/picks';
import { renderTimeBoard } from './app/timeBoard';
import { renderVictoryWall, visibleTicketCount } from './app/victoryWall';
import { initDailyVerseBanner } from './dailyVerse';
import { calculatePerformance } from './domain/metrics';
import { currentMexicoBlockIndex, mexicoDateKey } from './domain/timeBlocks';
import { statusLabel, type PickStatus } from './domain/picks';
import { supabase } from './lib/supabase';
import { getAdConfig, mountAd } from './services/ads';
import { telegramLinkUrl } from './services/account';
import { initUmami, trackConversion, trackWhenVisible } from './services/analytics';
import { escapeHtml, loadActiveOfferCounts, loadDailyPublicPicks, loadHistory, loadLocalPublicPicks, loadSubscriberPicks, type ActiveOfferCounts, type PickRow } from './services/data';
import { isSubscriberRpcActive } from './services/membership';
import { loadTicketManifest } from './services/tickets';
import { initTelegramMiniApp, isTelegramMiniAppLocation } from './app/telegram';
import { clearCheckoutIntent, navigateWithCheckoutIntent, readCheckoutIntent, saveCheckoutIntent, type CheckoutPlan } from './services/checkoutIntent';
import { initQuiniela, type QuinielaAppClient } from './quiniela/controller';
import { renderQuinielaShell, renderQuinielaUnavailable } from './quiniela/render';

type AppState = {
  picks: PickRow[];
  publicBoard: PickRow[];
  history: PickRow[];
  offerCounts: ActiveOfferCounts | null;
  tickets: string[];
  visibleTickets: number;
  pickFilter: string;
  historyFilter: string;
  user: User | null;
  isVip: boolean;
};

const state: AppState = {
  picks: [], publicBoard: [], history: [], offerCounts: null, tickets: [], visibleTickets: 6,
  pickFilter: 'all', historyFilter: 'all', user: null, isVip: false,
};
let membershipGeneration = 0;
let offerCountsGeneration = 0;
let checkoutInFlight = false;
let checkoutAuthActive = false;
let authResumeInFlight = false;
const membershipLookups = new Map<string, Promise<boolean>>();
const WINDOW_SLOT_NAMES = ['12am', '6am', '12pm', '6pm'] as const;
export const CHECKOUT_RETRY_DELAYS = [1000, 2000, 4000, 8000] as const;

function mexicoWindowSignature(now: Date): string {
  return `${mexicoDateKey(now)}:${currentMexicoBlockIndex(now)}`;
}

function startWindowRefreshMonitor(refresh: () => Promise<void>): void {
  let observedWindow = mexicoWindowSignature(new Date());
  let refreshing = false;
  window.setInterval(() => {
    const nextWindow = mexicoWindowSignature(new Date());
    if (nextWindow === observedWindow || refreshing) return;
    observedWindow = nextWindow;
    refreshing = true;
    void refresh()
      .finally(() => { refreshing = false; });
  }, 60_000);
}

function offerCountsForDisplayedBlock(
  offerCounts: ActiveOfferCounts | null,
  now: Date,
): ActiveOfferCounts | null {
  if (!offerCounts) return null;
  const windowStart = new Date(offerCounts.windowStart);
  return mexicoDateKey(windowStart) === mexicoDateKey(now)
    && currentMexicoBlockIndex(windowStart) === currentMexicoBlockIndex(now)
    ? offerCounts
    : null;
}

function currentAnalyticsProperties() {
  const now = new Date();
  const offerCounts = offerCountsForDisplayedBlock(state.offerCounts, now);
  const publicCount = offerCounts?.publicCount
    ?? state.publicBoard.filter(row => row.visibility === 'public').length;
  return {
    surface: 'web' as const,
    window_slot: WINDOW_SLOT_NAMES[currentMexicoBlockIndex(now)],
    public_pick_count: publicCount,
    ...(offerCounts ? { premium_pick_count: offerCounts.premiumCount } : {}),
  };
}

const isQuinielaRoute = window.location.pathname === '/quiniela'
  || window.location.pathname === '/quiniela/';

if (isQuinielaRoute) {
  try {
    initUmami();
  } catch {
    // Analytics must never block the promotion.
  }
  const root = document.getElementById('app');
  if (!root) throw new Error('Missing #app root');
  if (supabase) {
    void initQuiniela(root, supabase as unknown as QuinielaAppClient);
  } else {
    renderQuinielaShell(root);
    renderQuinielaUnavailable(root);
  }
} else {
renderShell();
const byId = <T extends HTMLElement>(id: string) => document.getElementById(id) as T | null;
const vipAccessLink = byId<HTMLAnchorElement>('telegram-access-link');
const configuredVipAccess = (import.meta.env.VITE_TELEGRAM_VIP_ACCESS_URL ?? '').trim();
const telegramBotUsername = (import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? '').trim().replace(/^@/, '');
const fallbackVipAccess = telegramBotUsername
  ? `https://t.me/${telegramBotUsername}?start=vip_access`
  : '';
const configuredVipAccessMatch = configuredVipAccess.match(/^https:\/\/t\.me\/([A-Za-z0-9_]+)\?start=[A-Za-z0-9_-]+$/);
const configuredTargetsOfficialBot = Boolean(
  telegramBotUsername
  && configuredVipAccessMatch?.[1].toLowerCase() === telegramBotUsername.toLowerCase(),
);
const safeVipAccess = configuredTargetsOfficialBot ? configuredVipAccess : fallbackVipAccess;
if (vipAccessLink && /^https:\/\/t\.me\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_-]+$/.test(safeVipAccess)) {
  vipAccessLink.href = safeVipAccess;
  vipAccessLink.classList.remove('hidden');
} else {
  vipAccessLink?.removeAttribute('href');
  vipAccessLink?.classList.add('hidden');
}
try {
  initUmami();
} catch {
  // Analytics must never block the application.
}
if (new URLSearchParams(window.location.search).get('checkout') === 'cancelled') {
  trackConversion('checkout_cancelled', currentAnalyticsProperties());
}
const telegramPath = import.meta.env.VITE_TELEGRAM_MINI_APP_PATH || '/?view=telegram';
const isTelegramMiniApp = isTelegramMiniAppLocation(window.location, telegramPath);

if (isTelegramMiniApp) {
  trackConversion('miniapp_opened', { surface: 'telegram_miniapp' });
  document.querySelector('.site-shell')?.classList.add('hidden');
  const root = byId('telegram-mini-app');
  root?.classList.remove('hidden');
  if (root) {
    void initTelegramMiniApp(root, {
      botUsername: import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? '',
      endpoint: import.meta.env.VITE_TELEGRAM_MINI_APP_ENDPOINT,
    });
  }
} else {
initDailyVerseBanner();

function categoryKey(value: string): string {
  const text = value.toLowerCase();
  if (text.includes('liga mx')) return 'ligamx';
  if (text.includes('mlb')) return 'mlb';
  return 'futbol';
}

function formatDate(value: string): string {
  if (!value) return '—';
  const date = new Date(`${value}T12:00:00-06:00`);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : new Intl.DateTimeFormat('es-MX', {
    day: '2-digit', month: 'short', timeZone: 'America/Mexico_City',
  }).format(date);
}

function renderPicks(): void {
  const root = byId('picks-container');
  if (!root) return;
  const rows = state.picks.filter(row => state.pickFilter === 'all' || categoryKey(row.categoria) === state.pickFilter);
  const now = new Date();
  const offerCounts = offerCountsForDisplayedBlock(state.offerCounts, now);
  root.innerHTML = renderTimeBoard(rows, {
    dateKey: mexicoDateKey(now),
    activeBlock: currentMexicoBlockIndex(now),
    isVip: state.isVip,
    offerCounts,
  });
  const updated = byId('picks-updated');
  if (updated) {
    const pendingPublic = rows.filter(row => row.estado === 'pendiente' && row.visibility === 'public').length;
    updated.textContent = state.isVip ? 'Cartera VIP activa' : publicCounterLabel(pendingPublic);
  }
  byId<HTMLButtonElement>('inline-vip-button')?.addEventListener('click', () => startVipCheckout('monthly'));
}

function renderHistory(): void {
  const root = byId<HTMLTableSectionElement>('history-container');
  if (!root) return;
  const rows = visibleHistory(state.history).filter(row => state.historyFilter === 'all' || row.estado === state.historyFilter);
  root.innerHTML = rows.length ? rows.map(row => `
    <tr><td>${formatDate(row.fecha_evento || row.fecha_generacion)}</td><td>${escapeHtml(row.partido)}</td><td>${escapeHtml(row.pick)}</td><td>@ ${escapeHtml(row.cuota)}</td><td><span class="status status-${row.estado}">${statusLabel(row.estado as PickStatus)}</span></td></tr>
  `).join('') : '<tr><td colspan="5">Todavía no hay resultados en este filtro.</td></tr>';

  const metrics = calculatePerformance(state.history);
  const record = byId('metric-record');
  const units = byId('metric-units');
  const roi = byId('metric-roi');
  const streakEl = byId('metric-streak');

  if (record) record.textContent = `${metrics.wins}-${metrics.losses}`;
  if (units) units.textContent = `${metrics.units >= 0 ? '+' : ''}${metrics.units} u`;
  if (roi) roi.textContent = `${metrics.roi >= 0 ? '+' : ''}${metrics.roi}%`;

  if (streakEl) {
    let currentStreak = 0;
    let streakType: 'win' | 'loss' | 'none' = 'none';
    for (const row of state.history) {
      if (row.estado === 'ganado') {
        if (streakType === 'none' || streakType === 'win') {
          streakType = 'win';
          currentStreak++;
        } else {
          break;
        }
      } else if (row.estado === 'perdido') {
        if (streakType === 'none' || streakType === 'loss') {
          streakType = 'loss';
          currentStreak++;
        } else {
          break;
        }
      }
    }
    if (streakType === 'win' && currentStreak > 0) {
      streakEl.textContent = `🔥 Racha: ${currentStreak} Acierto${currentStreak > 1 ? 's' : ''} Consecutivo${currentStreak > 1 ? 's' : ''}`;
      streakEl.className = 'streak-pill streak-win';
    } else if (streakType === 'loss' && currentStreak > 0) {
      streakEl.textContent = `🛡️ Varianza: ${currentStreak} Caída${currentStreak > 1 ? 's' : ''} (Disciplina +EV)`;
      streakEl.className = 'streak-pill streak-loss';
    } else {
      streakEl.textContent = `💎 Auditoría SHA-256 Verificada`;
      streakEl.className = 'streak-pill';
    }
  }
}

function renderTickets(): void {
  const root = byId('victory-wall');
  if (!root) return;
  root.innerHTML = renderVictoryWall(state.tickets, state.visibleTickets);
}

async function refreshTickets(): Promise<void> {
  state.tickets = await loadTicketManifest();
  state.visibleTickets = 6;
  renderTickets();
}

function refreshOfferCounts(): void {
  const generation = ++offerCountsGeneration;
  state.offerCounts = null;
  void loadActiveOfferCounts(supabase!)
    .then(offerCounts => {
      if (generation !== offerCountsGeneration || !offerCounts) return;
      state.offerCounts = offerCounts;
      renderPicks();
    })
    .catch(() => undefined);
}

async function refreshData(): Promise<void> {
  if (!supabase) {
    state.offerCounts = null;
    state.picks = await loadLocalPublicPicks();
    state.publicBoard = state.picks;
    state.history = [];
    renderPicks();
    renderHistory();
    return;
  }
  const now = new Date();
  refreshOfferCounts();
  const [board, history] = await Promise.all([
    loadDailyPublicPicks(supabase, mexicoDateKey(now)),
    loadHistory(supabase),
  ]);
  state.publicBoard = board;
  state.picks = board;
  state.history = history;
  renderPicks();
  renderHistory();
  if (board.some(row => row.estado === 'pendiente')) trackConversion('free_pick_viewed', currentAnalyticsProperties());
  if (history.length) trackConversion('history_viewed', currentAnalyticsProperties());
}

function lookupMembership(user: User): Promise<boolean> {
  const existing = membershipLookups.get(user.id);
  if (existing) return existing;
  const lookup = supabase
    ? Promise.resolve(supabase.rpc('is_active_subscriber', { check_user: user.id }))
      .then(response => !response.error && isSubscriberRpcActive(response.data))
      .catch(() => false)
    : Promise.resolve(false);
  membershipLookups.set(user.id, lookup);
  void lookup.then(() => { if (membershipLookups.get(user.id) === lookup) membershipLookups.delete(user.id); });
  return lookup;
}

async function checkMembership(user: User | null): Promise<boolean> {
  const generation = ++membershipGeneration;
  state.user = user;
  state.isVip = false;
  byId('vip-access-panel')?.classList.add('hidden');
  state.picks = state.publicBoard;
  renderPicks();
  if (user && supabase) {
    const isVip = await lookupMembership(user);
    if (generation !== membershipGeneration) return isVip;
    state.isVip = isVip;
  }
  byId('vip-access-panel')?.classList.toggle('hidden', !state.isVip);
  const login = byId<HTMLButtonElement>('login-button');
  if (login) login.textContent = user ? 'Mi cuenta' : 'Iniciar sesión';
  const vip = byId<HTMLButtonElement>('vip-button');
  if (vip) vip.textContent = state.isVip ? 'Administrar VIP' : 'VIP $349/mes';
  const checkout = byId<HTMLButtonElement>('vip-checkout-button');
  if (checkout) checkout.textContent = state.isVip ? 'Administrar membresía' : 'Suscribirme al VIP';
  const weekly = byId<HTMLButtonElement>('vip-weekly-button');
  if (weekly) weekly.textContent = state.isVip ? 'Administrar membresía' : 'Probar 7 días';
  byId('auth-form')?.classList.toggle('hidden', Boolean(user));
  byId('auth-dialog')?.querySelector('.auth-tabs')?.classList.toggle('hidden', Boolean(user));
  byId('account-tools')?.classList.toggle('hidden', !user);
  if (state.isVip && supabase) {
    trackConversion('subscription_confirmed', currentAnalyticsProperties());
    const premium = await loadSubscriberPicks(supabase);
    if (generation !== membershipGeneration) return state.isVip;
    state.picks = [
      ...state.publicBoard,
      ...premium.filter(pick => !state.publicBoard.some(row => row.id === pick.id)),
    ];
  } else {
    state.picks = state.publicBoard;
  }
  renderPicks();
  return state.isVip;
}

async function confirmCheckoutMembership(user: User, initialStatus: boolean): Promise<void> {
  const message = byId('checkout-status');
  const stopForChangedSession = (): boolean => {
    if (state.user?.id === user.id) return false;
    if (message) message.textContent = 'La confirmación se pausó porque cambió tu sesión. Inicia sesión para continuar.';
    return true;
  };
  if (stopForChangedSession()) return;
  if (initialStatus) {
    if (message) message.textContent = 'Pago confirmado. Tu acceso VIP está listo.';
    return;
  }
  if (message) message.textContent = 'Confirmando pago…';
  for (let attempt = 0; attempt < CHECKOUT_RETRY_DELAYS.length; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, CHECKOUT_RETRY_DELAYS[attempt]));
    if (stopForChangedSession()) return;
    const isVip = await checkMembership(user);
    if (stopForChangedSession()) return;
    if (isVip) {
      if (message) message.textContent = 'Pago confirmado. Tu acceso VIP está listo.';
      return;
    }
  }
  if (message) message.textContent = 'No pudimos confirmar el pago todavía. Escríbenos a soporte y revisaremos tu membresía.';
}

const dialog = byId<HTMLDialogElement>('auth-dialog');
const openAuth = () => { if (dialog && !dialog.open && typeof dialog.showModal === 'function') dialog.showModal(); };
const clearCheckoutAuth = () => { checkoutAuthActive = false; clearCheckoutIntent(); };
dialog?.addEventListener('cancel', clearCheckoutAuth);
dialog?.addEventListener('close', () => { if (checkoutAuthActive) clearCheckoutAuth(); });

document.querySelectorAll<HTMLButtonElement>('[data-auth-mode]').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('[data-auth-mode]').forEach(item => item.classList.toggle('active', item === button));
    const register = button.dataset.authMode === 'register';
    const submit = byId<HTMLButtonElement>('auth-submit');
    const password = byId<HTMLInputElement>('auth-password');
    if (submit) submit.textContent = register ? 'Crear cuenta' : 'Iniciar sesión';
    if (password) password.autocomplete = register ? 'new-password' : 'current-password';
  });
});

byId('login-button')?.addEventListener('click', async () => {
  clearCheckoutAuth();
  openAuth();
});

byId('signout-button')?.addEventListener('click', async () => {
  if (supabase) await supabase.auth.signOut();
  clearCheckoutAuth();
  dialog?.close();
});

byId('telegram-link-button')?.addEventListener('click', async () => {
  const message = byId('auth-message');
  if (!supabase || !state.user) return;
  if (message) message.textContent = 'Generando enlace seguro…';
  const result = await supabase.rpc('create_telegram_link_token');
  const url = !result.error && typeof result.data === 'string'
    ? telegramLinkUrl(import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? '', result.data)
    : '';
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
  if (message) message.textContent = url ? 'Abre Telegram y confirma el enlace antes de 10 minutos.' : 'No pudimos generar el enlace. Intenta de nuevo.';
});

byId<HTMLFormElement>('promo-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const message = byId('auth-message');
  const code = byId<HTMLInputElement>('promo-code')?.value.trim() ?? '';
  if (!supabase || !state.user || !code) return;
  if (message) message.textContent = 'Validando código…';
  const result = await supabase.rpc('redeem_promo_code', { raw_code: code });
  if (message) message.textContent = result.error ? 'El código no es válido, expiró o ya fue utilizado.' : 'Código aplicado. Tu acceso VIP ya está activo.';
  if (!result.error) await checkMembership(state.user);
});

byId<HTMLFormElement>('auth-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const email = byId<HTMLInputElement>('auth-email')?.value.trim() ?? '';
  const password = byId<HTMLInputElement>('auth-password')?.value ?? '';
  const mode = document.querySelector<HTMLButtonElement>('[data-auth-mode].active')?.dataset.authMode;
  const message = byId('auth-message');
  if (!supabase) {
    if (message) message.textContent = 'La cuenta requiere configurar Supabase en este despliegue.';
    return;
  }
  if (message) message.textContent = 'Procesando…';
  const response = mode === 'register'
    ? await supabase.auth.signUp({ email, password })
    : await supabase.auth.signInWithPassword({ email, password });
  if (message) message.textContent = response.error ? response.error.message : mode === 'register' ? 'Revisa tu correo para confirmar la cuenta.' : 'Sesión iniciada.';
  if (!response.error && mode !== 'register') {
    const shouldResume = checkoutAuthActive;
    const intent = readCheckoutIntent();
    checkoutAuthActive = false;
    dialog?.close();
    if (shouldResume && response.data.user && state.user && state.user.id !== response.data.user.id) return;
    let authoritativeIsVip = false;
    if (response.data.user) {
      authoritativeIsVip = await checkMembership(response.data.user);
    }
    if (shouldResume && intent && response.data.user) {
      void resumeCheckoutAfterAuth(response.data.user, authoritativeIsVip, intent);
    }
  }
});

type VipPlan = CheckoutPlan;

function validatedCheckoutUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && (url.hostname === 'stripe.com' || url.hostname.endsWith('.stripe.com')) ? url.href : null;
  } catch {
    return null;
  }
}

function checkoutAnalyticsProperties(plan: VipPlan) {
  return {
    ...currentAnalyticsProperties(),
    plan,
    billing_mode: plan === 'weekly' ? 'payment' as const : 'subscription' as const,
  };
}

async function startVipCheckout(plan: VipPlan = 'monthly', authoritativeIsVip?: boolean): Promise<void> {
  if (checkoutInFlight) return;
  const isVip = authoritativeIsVip ?? state.isVip;
  if (!isVip) trackConversion('vip_plan_selected', checkoutAnalyticsProperties(plan));
  if (isVip && supabase) {
    checkoutInFlight = true;
    try {
      const response = await supabase.functions.invoke('create-portal');
      const url = validatedCheckoutUrl(response.data?.url);
      if (!url) throw new Error('invalid portal URL');
      try { window.location.assign(url); } catch { checkoutInFlight = false; showCheckoutRecovery(); }
    } catch { checkoutInFlight = false; showCheckoutRecovery(); }
    return;
  }
  if (!state.user) {
    saveCheckoutIntent(plan);
    checkoutAuthActive = true;
    trackConversion('vip_auth_required', checkoutAnalyticsProperties(plan));
    openAuth();
    const message = byId('auth-message');
    if (message) message.textContent = 'Crea una cuenta o inicia sesión antes de pagar.';
    return;
  }
  if (!supabase) return;
  checkoutInFlight = true;
  trackConversion('checkout_started', checkoutAnalyticsProperties(plan));
  let redirectStarted = false;
  try {
    const response = await supabase.functions.invoke('create-checkout', { body: { plan, return_url: window.location.origin } });
    const url = validatedCheckoutUrl(response.data?.url);
    if (url) {
      redirectStarted = true;
      if (!navigateWithCheckoutIntent(url, plan, target => window.location.assign(target))) {
        checkoutInFlight = false; redirectStarted = false; showCheckoutRecovery();
      }
    } else {
      checkoutInFlight = false;
      showCheckoutRecovery();
    }
  } catch {
    checkoutInFlight = false;
    showCheckoutRecovery();
  } finally {
    if (!redirectStarted) checkoutInFlight = false;
  }
}

async function resumeCheckoutAfterAuth(user: User, authoritativeIsVip: boolean, intent: VipPlan): Promise<void> {
  if (authResumeInFlight || state.user?.id !== user.id) return;
  authResumeInFlight = true;
  checkoutAuthActive = false;
  try {
    await startVipCheckout(intent, authoritativeIsVip);
  } finally {
    authResumeInFlight = false;
  }
}

function showCheckoutRecovery(): void {
  openAuth();
  const message = byId('auth-message');
  if (message) message.textContent = 'No pudimos abrir Stripe. Intenta de nuevo o escríbenos a soporte.';
}

byId('vip-primary-button')?.addEventListener('click', () => {
  trackConversion('vip_primary_clicked', currentAnalyticsProperties());
  void startVipCheckout('monthly');
});
document.querySelectorAll<HTMLButtonElement>('[data-plan]').forEach(button => {
  button.addEventListener('click', () => startVipCheckout(button.dataset.plan === 'weekly' ? 'weekly' : 'monthly'));
});

byId('filter-row')?.addEventListener('click', event => {
  const target = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-filter]');
  if (!target) return;
  state.pickFilter = target.dataset.filter ?? 'all';
  document.querySelectorAll('[data-filter]').forEach(item => item.classList.toggle('active', item === target));
  renderPicks();
});

byId('history-filters')?.addEventListener('click', event => {
  const target = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-status]');
  if (!target) return;
  state.historyFilter = target.dataset.status ?? 'all';
  document.querySelectorAll('[data-status]').forEach(item => item.classList.toggle('active', item === target));
  renderHistory();
});

const victoryDialog = byId<HTMLDialogElement>('victory-dialog');
const victoryDialogImage = byId<HTMLImageElement>('victory-dialog-image');
const clearVictoryDialogImage = () => victoryDialogImage?.removeAttribute('src');

byId('victory-wall')?.addEventListener('click', event => {
  const target = event.target as HTMLElement;
  if (target.closest('#victory-load-more')) {
    state.visibleTickets = visibleTicketCount(state.visibleTickets, state.tickets.length);
    renderTickets();
    return;
  }
  const ticket = target.closest<HTMLButtonElement>('[data-ticket-url]');
  const url = ticket?.dataset.ticketUrl ?? '';
  if (!victoryDialog || !victoryDialogImage || !/^\/tickets\/ticket_[0-9]{1,20}[.]jpg$/.test(url)) return;
  victoryDialogImage.src = url;
  victoryDialog.showModal();
});

byId('victory-wall')?.addEventListener('error', event => {
  const image = event.target as HTMLElement;
  if (!(image instanceof HTMLImageElement)) return;
  const card = image.closest<HTMLButtonElement>('.victory-card');
  if (!card) return;
  card.disabled = true;
  card.classList.add('failed');
  image.remove();
  const label = card.querySelector('span');
  if (label) label.textContent = 'Evidencia temporalmente no disponible';
}, true);

byId('victory-dialog-close')?.addEventListener('click', () => {
  victoryDialog?.close();
  clearVictoryDialogImage();
});
victoryDialog?.addEventListener('close', clearVictoryDialogImage);

function updateStake(): void {
  const bankroll = Math.max(0, Number(byId<HTMLInputElement>('bankroll')?.value || 0));
  const percent = Number(byId<HTMLSelectElement>('risk-percent')?.value || 1.5);
  const unitVal = Math.round(bankroll * percent / 100);
  const maxStake = Math.round(unitVal * 2);

  const unitValEl = byId('unit-val-display');
  const maxStakeEl = byId('max-stake-display');
  const result = byId<HTMLOutputElement>('stake-result');

  if (unitValEl) unitValEl.textContent = `$${unitVal.toLocaleString('es-MX')} MXN`;
  if (maxStakeEl) maxStakeEl.textContent = `$${maxStake.toLocaleString('es-MX')} MXN`;
  if (result) {
    result.textContent = bankroll > 0
      ? `Unidad sugerida: $${unitVal.toLocaleString('es-MX')} MXN`
      : `Introduce tu banca disponible en Playdoit para calcular el tamaño de apuesta.`;
  }
}
byId('bankroll')?.addEventListener('input', updateStake);
byId('risk-percent')?.addEventListener('change', updateStake);
updateStake();
byId('telegram-cta')?.addEventListener('click', () => trackConversion('telegram_clicked', currentAnalyticsProperties()));

const cookie = byId('cookie-notice');
const adConfig = getAdConfig(import.meta.env.VITE_ADSENSE_SLOT, import.meta.env.VITE_ADSENSE_CLIENT);
const mountConfiguredAd = () => mountAd(byId('ad-slot-feed')!, adConfig);
if (!localStorage.getItem('rey-taco-cookie-notice')) cookie?.classList.remove('hidden');
else mountConfiguredAd();
byId('cookie-accept')?.addEventListener('click', () => {
  localStorage.setItem('rey-taco-cookie-notice', 'accepted');
  cookie?.classList.add('hidden');
  mountConfiguredAd();
});

if (supabase) {
  supabase.auth.onAuthStateChange(async (event, session) => {
    const user = session?.user ?? null;
    const status = await checkMembership(user);
    const intent = event === 'SIGNED_IN' ? readCheckoutIntent() : null;
    if (event === 'SIGNED_IN' && intent && user) {
      void resumeCheckoutAfterAuth(user, status, intent);
    }
  });
}
void refreshTickets();
void (async () => {
  await refreshData();
  startWindowRefreshMonitor(async () => {
    await refreshData();
    await checkMembership(state.user);
  });
  trackWhenVisible(document.querySelector('.vip-section'), 'vip_offer_viewed', currentAnalyticsProperties);
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    const initialMembership = await checkMembership(data.session?.user ?? null);
    if (new URLSearchParams(window.location.search).get('checkout') === 'success' && data.session?.user) {
      void confirmCheckoutMembership(data.session.user, initialMembership);
    } else if (new URLSearchParams(window.location.search).get('checkout') === 'success') {
      const message = byId('checkout-status');
      if (message) message.textContent = 'Inicia sesión para confirmar tu pago y habilitar el acceso VIP.';
    }
  }
})();
}
}
