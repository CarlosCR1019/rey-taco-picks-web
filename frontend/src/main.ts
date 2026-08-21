import './style.css';
import type { User } from '@supabase/supabase-js';
import { renderShell } from './app/render';
import { visibleHistory } from './app/history';
import { initDailyVerseBanner } from './dailyVerse';
import { calculatePerformance } from './domain/metrics';
import { statusLabel, type PickStatus } from './domain/picks';
import { supabase } from './lib/supabase';
import { getAdConfig, mountAd } from './services/ads';
import { telegramLinkUrl } from './services/account';
import { trackConversion, trackWhenVisible } from './services/analytics';
import { escapeHtml, loadHistory, loadLocalPublicPicks, loadPublicPicks, loadSubscriberPicks, type PickRow } from './services/data';
import { isSubscriberRpcActive } from './services/membership';

type AppState = {
  picks: PickRow[];
  history: PickRow[];
  pickFilter: string;
  historyFilter: string;
  user: User | null;
  isVip: boolean;
};

const state: AppState = {
  picks: [], history: [], pickFilter: 'all', historyFilter: 'all', user: null, isVip: false,
};
let membershipGeneration = 0;

renderShell();
initDailyVerseBanner();

const byId = <T extends HTMLElement>(id: string) => document.getElementById(id) as T | null;

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

function pickCard(row: PickRow): string {
  const locked = row.visibility === 'premium' && !state.isVip;
  return `
    <article class="pick-card ${locked ? 'locked' : ''}">
      <div class="pick-meta"><span>${escapeHtml(row.categoria)}</span><span>${formatDate(row.fecha_evento || row.fecha_generacion)} · CDMX</span></div>
      <h3>${escapeHtml(row.partido)}</h3>
      ${locked ? '<div class="locked-pick"><strong>♛ Selección VIP</strong><span>Inicia sesión con una membresía activa para verla.</span></div>' : `
        <div class="selection-row"><span>Selección</span><strong>${escapeHtml(row.pick)}</strong><b>@ ${escapeHtml(row.cuota)}</b></div>
        <p>${escapeHtml(row.razonamiento)}</p>
      `}
      <div class="pick-footer"><span>Confianza: ${escapeHtml(row.confianza)}</span><span class="status status-${row.estado}">${statusLabel(row.estado as PickStatus)}</span></div>
    </article>`;
}

function renderPicks(): void {
  const root = byId('picks-container');
  if (!root) return;
  const rows = state.picks.filter(row => state.pickFilter === 'all' || categoryKey(row.categoria) === state.pickFilter);
  root.innerHTML = rows.length ? rows.map(pickCard).join('') : `
    <div class="state-card"><strong>No hay picks disponibles en este filtro.</strong><span>Vuelve más tarde; no publicamos selecciones solo para llenar espacio.</span></div>`;
  const updated = byId('picks-updated');
  if (updated) updated.textContent = state.isVip ? 'Cartera VIP activa' : rows.length ? '1 selección pública' : 'Sin selección disponible';
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
  if (record) record.textContent = `${metrics.wins}-${metrics.losses}`;
  if (units) units.textContent = `${metrics.units >= 0 ? '+' : ''}${metrics.units} u`;
  if (roi) roi.textContent = `${metrics.roi >= 0 ? '+' : ''}${metrics.roi}%`;
}

async function refreshData(): Promise<void> {
  if (!supabase) {
    state.picks = await loadLocalPublicPicks();
    state.history = [];
    renderPicks();
    renderHistory();
    return;
  }
  const [picks, history] = await Promise.all([loadPublicPicks(supabase), loadHistory(supabase)]);
  state.picks = picks;
  state.history = [...history, ...picks.filter(pick => !history.some(row => row.id === pick.id))];
  renderPicks();
  renderHistory();
  if (picks.length) trackConversion('free_pick_viewed');
  if (history.length) trackConversion('history_viewed');
}

async function checkMembership(user: User | null): Promise<void> {
  const generation = ++membershipGeneration;
  state.user = user;
  state.isVip = false;
  state.picks = state.picks.filter(pick => pick.visibility === 'public');
  renderPicks();
  if (user && supabase) {
    const response = await supabase.rpc('is_active_subscriber', { check_user: user.id });
    if (generation !== membershipGeneration) return;
    state.isVip = !response.error && isSubscriberRpcActive(response.data);
  }
  const login = byId<HTMLButtonElement>('login-button');
  if (login) login.textContent = user ? 'Mi cuenta' : 'Iniciar sesión';
  const vip = byId<HTMLButtonElement>('vip-button');
  if (vip) vip.textContent = state.isVip ? 'Administrar VIP' : 'VIP $299';
  const checkout = byId<HTMLButtonElement>('vip-checkout-button');
  if (checkout) checkout.textContent = state.isVip ? 'Administrar membresía' : 'Quiero ser VIP';
  byId('auth-form')?.classList.toggle('hidden', Boolean(user));
  byId('auth-dialog')?.querySelector('.auth-tabs')?.classList.toggle('hidden', Boolean(user));
  byId('account-tools')?.classList.toggle('hidden', !user);
  if (state.isVip && supabase) {
    trackConversion('subscription_confirmed');
    const premium = await loadSubscriberPicks(supabase);
    if (generation !== membershipGeneration) return;
    if (premium.length) state.picks = premium;
  } else {
    const publicPicks = supabase ? await loadPublicPicks(supabase) : await loadLocalPublicPicks();
    if (generation !== membershipGeneration) return;
    state.picks = publicPicks;
  }
  renderPicks();
}

const dialog = byId<HTMLDialogElement>('auth-dialog');
const openAuth = () => dialog?.showModal();

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
  openAuth();
});

byId('signout-button')?.addEventListener('click', async () => {
  if (supabase) await supabase.auth.signOut();
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
  if (!response.error && mode !== 'register') dialog?.close();
});

async function startVipCheckout(): Promise<void> {
  if (state.isVip && supabase) {
    const response = await supabase.functions.invoke('create-portal');
    const url = typeof response.data?.url === 'string' ? response.data.url : '';
    if (url) window.location.assign(url);
    else {
      openAuth();
      const message = byId('auth-message');
      if (message) message.textContent = 'No pudimos abrir la administración de Stripe. Escríbenos a soporte.';
    }
    return;
  }
  if (!state.user) {
    openAuth();
    const message = byId('auth-message');
    if (message) message.textContent = 'Crea una cuenta o inicia sesión antes de pagar.';
    return;
  }
  if (!supabase) return;
  trackConversion('checkout_started');
  const response = await supabase.functions.invoke('create-checkout', { body: { return_url: window.location.origin } });
  const url = typeof response.data?.url === 'string' ? response.data.url : '';
  if (url) window.location.assign(url);
  else {
    openAuth();
    const message = byId('auth-message');
    if (message) message.textContent = 'El pago con tarjeta está en preparación. Puedes solicitar revisión manual por SPEI en WhatsApp.';
  }
}

byId('vip-button')?.addEventListener('click', startVipCheckout);
byId('vip-checkout-button')?.addEventListener('click', startVipCheckout);

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

function updateStake(): void {
  const bankroll = Math.max(0, Number(byId<HTMLInputElement>('bankroll')?.value || 0));
  const percent = Number(byId<HTMLSelectElement>('risk-percent')?.value || 1);
  const result = byId<HTMLOutputElement>('stake-result');
  if (result) result.textContent = `Unidad sugerida: $${Math.round(bankroll * percent / 100).toLocaleString('es-MX')} MXN`;
}
byId('bankroll')?.addEventListener('input', updateStake);
byId('risk-percent')?.addEventListener('change', updateStake);
byId('telegram-cta')?.addEventListener('click', () => trackConversion('telegram_clicked'));
trackWhenVisible(document.querySelector('.vip-section'), 'vip_offer_viewed');

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
  supabase.auth.onAuthStateChange((_event, session) => void checkMembership(session?.user ?? null));
}
void (async () => {
  await refreshData();
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    await checkMembership(data.session?.user ?? null);
  }
})();
