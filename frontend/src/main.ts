import './style.css';
import type { User } from '@supabase/supabase-js';
import { renderShell } from './app/render';
import { visibleHistory } from './app/history';
import { initDailyVerseBanner } from './dailyVerse';
import { calculatePerformance } from './domain/metrics';
import { statusLabel, type PickStatus } from './domain/picks';
import { supabase } from './lib/supabase';
import { getAdConfig, mountAd } from './services/ads';
import { escapeHtml, loadHistory, loadPublicPicks, loadSubscriberPicks, type PickRow } from './services/data';
import { isMembershipActive, type Membership } from './services/membership';

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

renderShell();
initDailyVerseBanner();

const byId = <T extends HTMLElement>(id: string) => document.getElementById(id) as T | null;
const analytics = (event: string, detail: Record<string, string> = {}) => {
  const target = window as typeof window & { dataLayer?: Record<string, string>[] };
  (target.dataLayer ??= []).push({ event, ...detail });
};

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
      <div class="pick-meta"><span>${escapeHtml(row.categoria)}</span><span>${formatDate(row.fecha_generacion)} · CDMX</span></div>
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
    <tr><td>${formatDate(row.fecha_generacion)}</td><td>${escapeHtml(row.partido)}</td><td>${escapeHtml(row.pick)}</td><td>@ ${escapeHtml(row.cuota)}</td><td><span class="status status-${row.estado}">${statusLabel(row.estado as PickStatus)}</span></td></tr>
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
  const [picks, history] = await Promise.all([loadPublicPicks(supabase), loadHistory(supabase)]);
  state.picks = picks;
  state.history = history;
  renderPicks();
  renderHistory();
}

async function checkMembership(user: User | null): Promise<void> {
  state.user = user;
  state.isVip = false;
  if (user) {
    const response = await supabase.from('subscriptions')
      .select('status,current_period_end')
      .eq('user_id', user.id)
      .order('current_period_end', { ascending: false })
      .limit(1)
      .maybeSingle();
    state.isVip = !response.error && isMembershipActive(response.data as Membership | null);
  }
  const login = byId<HTMLButtonElement>('login-button');
  if (login) login.textContent = user ? 'Mi cuenta' : 'Iniciar sesión';
  const vip = byId<HTMLButtonElement>('vip-button');
  if (vip) vip.textContent = state.isVip ? 'VIP activo' : 'VIP $299';
  if (state.isVip) {
    const premium = await loadSubscriberPicks(supabase);
    if (premium.length) state.picks = premium;
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
  if (!state.user) return openAuth();
  if (window.confirm('¿Quieres cerrar tu sesión?')) await supabase.auth.signOut();
});

byId<HTMLFormElement>('auth-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const email = byId<HTMLInputElement>('auth-email')?.value.trim() ?? '';
  const password = byId<HTMLInputElement>('auth-password')?.value ?? '';
  const mode = document.querySelector<HTMLButtonElement>('[data-auth-mode].active')?.dataset.authMode;
  const message = byId('auth-message');
  if (message) message.textContent = 'Procesando…';
  const response = mode === 'register'
    ? await supabase.auth.signUp({ email, password })
    : await supabase.auth.signInWithPassword({ email, password });
  if (message) message.textContent = response.error ? response.error.message : mode === 'register' ? 'Revisa tu correo para confirmar la cuenta.' : 'Sesión iniciada.';
  if (!response.error) {
    analytics(mode === 'register' ? 'sign_up' : 'login');
    if (mode !== 'register') dialog?.close();
  }
});

async function startVipCheckout(): Promise<void> {
  analytics('begin_checkout', { product: 'vip_monthly' });
  if (state.isVip) {
    location.hash = '#picks';
    return;
  }
  if (!state.user) {
    openAuth();
    const message = byId('auth-message');
    if (message) message.textContent = 'Crea una cuenta o inicia sesión antes de pagar.';
    return;
  }
  const directUrl = import.meta.env.VITE_STRIPE_CHECKOUT_URL?.trim();
  if (directUrl) {
    window.location.assign(directUrl);
    return;
  }
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
  analytics('filter_picks', { filter: state.pickFilter });
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

supabase.auth.onAuthStateChange((_event, session) => void checkMembership(session?.user ?? null));
void supabase.auth.getSession().then(({ data }) => checkMembership(data.session?.user ?? null));
void refreshData();
