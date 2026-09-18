import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PickRow } from './services/data';

const mocks = vi.hoisted(() => ({
  loadActiveOfferCounts: vi.fn(),
  loadDailyPublicPicks: vi.fn(),
  loadHistory: vi.fn(),
  loadLocalPublicPicks: vi.fn(),
  loadSubscriberPicks: vi.fn(),
  loadTicketManifest: vi.fn(),
  initUmami: vi.fn(),
  trackConversion: vi.fn(),
  trackWhenVisible: vi.fn(),
  getSession: vi.fn(),
  rpc: vi.fn(),
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  invoke: vi.fn(),
  initQuiniela: vi.fn(),
  authCallback: undefined as ((event: string, session: unknown) => void) | undefined,
}));

vi.mock('./lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: mocks.getSession,
      onAuthStateChange: (callback: (event: string, session: unknown) => void) => { mocks.authCallback = callback; },
      signInWithPassword: mocks.signInWithPassword,
      signOut: vi.fn(),
      signUp: mocks.signUp,
    },
    functions: { invoke: mocks.invoke },
    rpc: mocks.rpc,
  },
}));
vi.mock('./services/data', async importOriginal => ({
  ...await importOriginal<typeof import('./services/data')>(),
  loadActiveOfferCounts: mocks.loadActiveOfferCounts,
  loadDailyPublicPicks: mocks.loadDailyPublicPicks,
  loadHistory: mocks.loadHistory,
  loadLocalPublicPicks: mocks.loadLocalPublicPicks,
  loadSubscriberPicks: mocks.loadSubscriberPicks,
}));
vi.mock('./services/analytics', () => ({
  initUmami: mocks.initUmami,
  trackConversion: mocks.trackConversion,
  trackWhenVisible: mocks.trackWhenVisible,
}));
vi.mock('./services/tickets', () => ({ loadTicketManifest: mocks.loadTicketManifest }));
vi.mock('./dailyVerse', () => ({ initDailyVerseBanner: vi.fn() }));
vi.mock('./quiniela/controller', () => ({ initQuiniela: mocks.initQuiniela }));

const publicPick: PickRow = {
  id: 1,
  categoria: 'Fútbol',
  partido: 'Partido público',
  pick: 'Selección pública',
  cuota: '1.80',
  confianza: '65%',
  razonamiento: '',
  fecha_generacion: '2026-09-10',
  fecha_evento: '2026-09-10',
  horario: '12:00',
  estado: 'pendiente',
  es_parlay: false,
  visibility: 'public',
};

async function mountMain(): Promise<typeof import('./main')> {
  document.body.innerHTML = '<div id="app"></div><div id="telegram-mini-app" class="hidden"></div>';
  const app = await import('./main');
  await vi.waitFor(() => expect(mocks.loadHistory).toHaveBeenCalled());
  return app;
}

describe('active offer integration', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.useFakeTimers();
    vi.clearAllTimers();
    vi.setSystemTime(new Date('2026-09-10T17:59:59.999Z'));
    vi.resetModules();
    vi.clearAllMocks();
    mocks.initUmami.mockReset();
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState({}, '', '/');
    mocks.loadDailyPublicPicks.mockResolvedValue([publicPick]);
    mocks.loadActiveOfferCounts.mockResolvedValue(null);
    mocks.loadHistory.mockResolvedValue([]);
    mocks.loadSubscriberPicks.mockResolvedValue([]);
    mocks.loadTicketManifest.mockResolvedValue([]);
    mocks.getSession.mockResolvedValue({ data: { session: null } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
    mocks.signInWithPassword.mockResolvedValue({ data: { user: { id: 'user' } }, error: null });
    mocks.signUp.mockResolvedValue({ data: { user: null }, error: null });
    mocks.authCallback = undefined;
  });

  it('dispatches /quiniela without loading the picks or checkout application', async () => {
    window.history.replaceState({}, '', '/quiniela');
    document.body.innerHTML = '<div id="app"></div><div id="telegram-mini-app" class="hidden"></div>';

    await import('./main');

    await vi.waitFor(() => expect(mocks.initQuiniela).toHaveBeenCalledTimes(1));
    expect(mocks.loadDailyPublicPicks).not.toHaveBeenCalled();
    expect(mocks.loadActiveOfferCounts).not.toHaveBeenCalled();
    expect(mocks.loadHistory).not.toHaveBeenCalled();
    expect(mocks.loadSubscriberPicks).not.toHaveBeenCalled();
    expect(mocks.loadTicketManifest).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('loads active offer counts and renders their truthful headline', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T12:00:00.000Z', publicCount: 1, premiumCount: 3,
    });

    await mountMain();

    expect(mocks.initUmami).toHaveBeenCalledTimes(1);
    expect(mocks.loadActiveOfferCounts).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => {
      expect(document.querySelector('.vip-discovery strong')?.textContent).toContain('1 gratis y 3 en VIP');
    });
    expect(mocks.trackConversion).toHaveBeenCalledWith('free_pick_viewed', expect.objectContaining({
      public_pick_count: 1,
      premium_pick_count: 3,
    }));
  });

  it('mounts and loads data when Umami initialization throws', async () => {
    mocks.initUmami.mockImplementation(() => { throw new Error('analytics unavailable'); });

    await mountMain();

    expect(document.body.textContent).toContain('Partido público');
    expect(mocks.loadHistory).toHaveBeenCalledTimes(1);
  });

  it('ignores offer counts from a different six-hour Mexico block', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T18:00:00.000Z', publicCount: 1, premiumCount: 3,
    });

    await mountMain();

    await vi.waitFor(() => {
      expect(document.querySelector('.vip-discovery strong')?.textContent)
        .toContain('Más selecciones disponibles en VIP');
    });
    expect(mocks.trackConversion).toHaveBeenCalledWith(
      'free_pick_viewed',
      expect.not.objectContaining({ premium_pick_count: expect.anything() }),
    );
  });

  it('switches offer counts at the exact Mexico block boundary', async () => {
    vi.setSystemTime(new Date('2026-09-10T18:00:00.000Z'));
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T18:00:00.000Z', publicCount: 1, premiumCount: 3,
    });

    await mountMain();

    await vi.waitFor(() => {
      expect(document.querySelector('.vip-discovery strong')?.textContent).toContain('1 gratis y 3 en VIP');
    });
    expect(mocks.trackConversion).toHaveBeenCalledWith('free_pick_viewed', expect.objectContaining({
      window_slot: '12pm',
      premium_pick_count: 3,
    }));
  });

  it('reloads the daily board and offer counts after crossing a Mexico window boundary', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T12:00:00.000Z', publicCount: 1, premiumCount: 3,
    });

    await mountMain();

    const nextPick = { ...publicPick, id: 2, partido: 'Partido de la ventana nueva', horario: '18:00' };
    mocks.loadDailyPublicPicks.mockResolvedValue([nextPick]);
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T18:00:00.000Z', publicCount: 1, premiumCount: 2,
    });

    await vi.advanceTimersByTimeAsync(60_000);

    await vi.waitFor(() => {
      expect(mocks.loadDailyPublicPicks).toHaveBeenCalledTimes(2);
      expect(mocks.loadActiveOfferCounts).toHaveBeenCalledTimes(2);
      expect(document.body.textContent).toContain('Partido de la ventana nueva');
    });
  });

  it('ignores an older offer-count response that arrives after the new window response', async () => {
    let resolveOld!: (value: unknown) => void;
    let resolveNew!: (value: unknown) => void;
    mocks.loadActiveOfferCounts
      .mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }))
      .mockReturnValueOnce(new Promise(resolve => { resolveNew = resolve; }));

    await mountMain();
    await vi.advanceTimersByTimeAsync(60_000);
    resolveNew({ windowStart: '2026-09-10T18:00:00.000Z', publicCount: 1, premiumCount: 2 });
    await vi.waitFor(() => {
      expect(document.querySelector('.vip-discovery strong')?.textContent).toContain('1 gratis y 2 en VIP');
    });

    resolveOld({ windowStart: '2026-09-10T12:00:00.000Z', publicCount: 1, premiumCount: 5 });
    await Promise.resolve();

    expect(document.querySelector('.vip-discovery strong')?.textContent).toContain('1 gratis y 2 en VIP');
  });

  it('registers vip_offer_viewed once with counts loaded by the initial refresh', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T12:00:00.000Z', publicCount: 1, premiumCount: 3,
    });

    await mountMain();

    expect(mocks.trackWhenVisible).toHaveBeenCalledTimes(1);
    expect(mocks.trackWhenVisible).toHaveBeenCalledWith(
      document.querySelector('.vip-section'),
      'vip_offer_viewed',
      expect.any(Function),
    );
  });

  it('expires loaded counts for rerenders, checkout analytics, and delayed visibility', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T12:00:00.000Z', publicCount: 1, premiumCount: 3,
    });
    await mountMain();
    const propertiesFactory = mocks.trackWhenVisible.mock.calls[0]?.[2] as (() => Record<string, unknown>);

    vi.setSystemTime(new Date('2026-09-10T18:00:00.000Z'));
    document.querySelector<HTMLButtonElement>('[data-filter="all"]')?.click();
    Object.assign(document.querySelector<HTMLDialogElement>('#auth-dialog')!, { showModal: vi.fn() });
    document.querySelector<HTMLButtonElement>('#vip-button')?.click();

    expect(document.querySelector('.vip-discovery strong')?.textContent)
      .toContain('Más selecciones disponibles en VIP');
    expect(mocks.trackConversion).toHaveBeenCalledWith('vip_auth_required', expect.objectContaining({
      window_slot: '12pm',
    }));
    expect(mocks.trackConversion).toHaveBeenCalledWith(
      'vip_auth_required',
      expect.not.objectContaining({ premium_pick_count: expect.anything() }),
    );
    expect(propertiesFactory()).toEqual(expect.objectContaining({ window_slot: '12pm' }));
    expect(propertiesFactory()).not.toEqual(expect.objectContaining({ premium_pick_count: expect.anything() }));
  });

  it('renders the exact generic fallback when active counts are unavailable', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue(null);

    await mountMain();

    await vi.waitFor(() => {
      expect(document.querySelector('.vip-discovery strong')?.textContent).toContain('Más selecciones disponibles en VIP');
    });
  });

  it('renders board and continues session flow while active counts remain pending', async () => {
    mocks.loadActiveOfferCounts.mockReturnValue(new Promise(() => undefined));
    mocks.loadHistory.mockResolvedValue([{ ...publicPick, id: 2, partido: 'Partido histórico', estado: 'ganado' }]);

    await mountMain();

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('Partido público');
      expect(document.body.textContent).toContain('Partido histórico');
      expect(document.querySelector('.vip-discovery strong')?.textContent)
        .toContain('Más selecciones disponibles en VIP');
      expect(mocks.getSession).toHaveBeenCalledTimes(1);
    });
  });

  it('renders board and continues session flow when active counts reject', async () => {
    mocks.loadActiveOfferCounts.mockRejectedValue(new Error('counts unavailable'));

    await mountMain();

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('Partido público');
      expect(document.querySelector('.vip-discovery strong')?.textContent)
        .toContain('Más selecciones disponibles en VIP');
      expect(mocks.getSession).toHaveBeenCalledTimes(1);
    });
  });

  it('never infers a premium analytics count from VIP-visible picks', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue(null);
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'vip-user' } } } });
    mocks.rpc.mockResolvedValue({ data: true, error: null });
    mocks.loadSubscriberPicks.mockResolvedValue([{
      ...publicPick,
      id: 2,
      partido: 'Partido VIP',
      visibility: 'premium',
    }]);

    await mountMain();

    await vi.waitFor(() => expect(mocks.trackConversion).toHaveBeenCalledWith(
      'subscription_confirmed',
      expect.not.objectContaining({ premium_pick_count: expect.anything() }),
    ));
  });

  it('keeps the selected weekly plan while requesting authentication', async () => {
    await mountMain();
    const dialog = document.querySelector<HTMLDialogElement>('#auth-dialog')!;
    dialog.showModal = vi.fn();
    dialog.close = vi.fn();
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    expect(sessionStorage.getItem('rey_taco_checkout_plan')).toBe('weekly');
    expect(dialog.showModal).toHaveBeenCalledTimes(1);
    expect(mocks.trackConversion).toHaveBeenCalledWith('vip_auth_required', expect.anything());
    expect(mocks.trackConversion).toHaveBeenCalledWith('vip_auth_required', expect.objectContaining({ plan: 'weekly', billing_mode: 'payment' }));
    expect(mocks.trackConversion).toHaveBeenCalledWith('vip_plan_selected', expect.objectContaining({ plan: 'weekly', billing_mode: 'payment' }));
  });

  it('retains the monthly plan after sign-up while waiting for confirmation', async () => {
    await mountMain();
    const dialog = document.querySelector<HTMLDialogElement>('#auth-dialog')!;
    dialog.showModal = vi.fn();
    dialog.close = vi.fn();
    document.querySelector<HTMLButtonElement>('[data-plan="monthly"]')?.click();
    document.querySelector<HTMLButtonElement>('[data-auth-mode="register"]')?.click();
    document.querySelector<HTMLInputElement>('#auth-email')!.value = 'a@b.com';
    document.querySelector<HTMLInputElement>('#auth-password')!.value = 'secret';
    document.querySelector<HTMLFormElement>('#auth-form')?.requestSubmit();
    await vi.waitFor(() => expect(mocks.signUp).toHaveBeenCalled());
    expect(sessionStorage.getItem('rey_taco_checkout_plan')).toBe('monthly');
    expect(document.querySelector('#auth-message')?.textContent).toContain('Revisa tu correo');
  });

  it('resumes a fresh sign-up intent after the confirmation page reloads', async () => {
    mocks.invoke.mockResolvedValue({ data: {}, error: null });
    await mountMain();
    document.querySelector<HTMLButtonElement>('[data-plan="monthly"]')?.click();
    document.querySelector<HTMLButtonElement>('[data-auth-mode="register"]')?.click();
    document.querySelector<HTMLInputElement>('#auth-email')!.value = 'a@b.com';
    document.querySelector<HTMLInputElement>('#auth-password')!.value = 'secret';
    document.querySelector<HTMLFormElement>('#auth-form')?.requestSubmit();
    await vi.waitFor(() => expect(mocks.signUp).toHaveBeenCalled());

    vi.resetModules();
    await mountMain();
    mocks.authCallback?.('SIGNED_IN', { user: { id: 'confirmed' } });

    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('create-checkout', {
      body: { plan: 'monthly', return_url: window.location.origin },
    }));
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
  });

  it('does not resume an expired intent from a signed-in callback', async () => {
    sessionStorage.setItem('rey_taco_checkout_plan', 'weekly');
    sessionStorage.setItem('rey_taco_checkout_plan_at', String(Date.now() - 31 * 60 * 1000));
    await mountMain();

    mocks.authCallback?.('SIGNED_IN', { user: { id: 'confirmed' } });

    await vi.waitFor(() => expect(sessionStorage.getItem('rey_taco_checkout_plan')).toBeNull());
    expect(mocks.invoke).not.toHaveBeenCalled();
  });


  it('resumes the selected weekly checkout after password login', async () => {
    mocks.invoke.mockResolvedValue({ data: {}, error: null });
    await mountMain();
    const dialog = document.querySelector<HTMLDialogElement>('#auth-dialog')!;
    dialog.showModal = vi.fn();
    dialog.close = vi.fn();
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    document.querySelector<HTMLInputElement>('#auth-email')!.value = 'a@b.com';
    document.querySelector<HTMLInputElement>('#auth-password')!.value = 'secret';
    document.querySelector<HTMLFormElement>('#auth-form')?.requestSubmit();
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('create-checkout', {
      body: { plan: 'weekly', return_url: window.location.origin },
    }));
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
  });

  it('does not create duplicate checkout requests for duplicate clicks', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'user' } } } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
    mocks.invoke.mockReturnValue(new Promise(() => undefined));
    await mountMain();
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledTimes(1));
    expect(mocks.trackConversion).toHaveBeenCalledWith('vip_plan_selected', expect.objectContaining({ plan: 'weekly', billing_mode: 'payment' }));
    expect(mocks.trackConversion).toHaveBeenCalledWith('checkout_started', expect.objectContaining({ plan: 'weekly', billing_mode: 'payment' }));
  });

  it('labels monthly checkout analytics as a subscription', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'user' } } } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
    mocks.invoke.mockReturnValue(new Promise(() => undefined));
    await mountMain();
    document.querySelector<HTMLButtonElement>('[data-plan="monthly"]')?.click();
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledTimes(1));
    expect(mocks.trackConversion).toHaveBeenCalledWith('vip_plan_selected', expect.objectContaining({ plan: 'monthly', billing_mode: 'subscription' }));
    expect(mocks.trackConversion).toHaveBeenCalledWith('checkout_started', expect.objectContaining({ plan: 'monthly', billing_mode: 'subscription' }));
  });

  it('does not start checkout for an ordinary account login', async () => {
    mocks.invoke.mockResolvedValue({ data: {}, error: null });
    await mountMain();
    const dialog = document.querySelector<HTMLDialogElement>('#auth-dialog')!;
    dialog.showModal = vi.fn();
    dialog.close = vi.fn();
    document.querySelector<HTMLButtonElement>('#login-button')?.click();
    document.querySelector<HTMLInputElement>('#auth-email')!.value = 'a@b.com';
    document.querySelector<HTMLInputElement>('#auth-password')!.value = 'secret';
    document.querySelector<HTMLFormElement>('#auth-form')?.requestSubmit();
    await vi.waitFor(() => expect(mocks.signInWithPassword).toHaveBeenCalled());
    await Promise.resolve();
    expect(mocks.invoke).not.toHaveBeenCalledWith('create-checkout', expect.anything());
  });

  it('clears a stale intent before an ordinary login', async () => {
    sessionStorage.setItem('rey_taco_checkout_plan', 'weekly');
    sessionStorage.setItem('rey_taco_checkout_plan_at', String(Date.now()));
    await mountMain();
    const dialog = document.querySelector<HTMLDialogElement>('#auth-dialog')!;
    dialog.showModal = vi.fn(); dialog.close = vi.fn();
    document.querySelector<HTMLButtonElement>('#login-button')?.click();
    document.querySelector<HTMLInputElement>('#auth-email')!.value = 'a@b.com';
    document.querySelector<HTMLInputElement>('#auth-password')!.value = 'secret';
    document.querySelector<HTMLFormElement>('#auth-form')?.requestSubmit();
    await vi.waitFor(() => expect(mocks.signInWithPassword).toHaveBeenCalled());
    expect(sessionStorage.getItem('rey_taco_checkout_plan')).toBeNull();
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('handles a concurrent signed-in auth callback with one authoritative membership lookup', async () => {
    let resolveMembership!: (value: unknown) => void;
    mocks.rpc.mockReturnValue(new Promise(resolve => { resolveMembership = resolve; }));
    mocks.signInWithPassword.mockImplementation(async () => {
      mocks.authCallback?.('SIGNED_IN', { user: { id: 'race' } });
      return { data: { user: { id: 'race' } }, error: null };
    });
    mocks.invoke.mockResolvedValue({ data: {}, error: null });
    await mountMain();
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    document.querySelector<HTMLDialogElement>('#auth-dialog')!.close = vi.fn();
    document.querySelector<HTMLInputElement>('#auth-email')!.value = 'a@b.com';
    document.querySelector<HTMLInputElement>('#auth-password')!.value = 'secret';
    document.querySelector<HTMLFormElement>('#auth-form')?.requestSubmit();
    await vi.waitFor(() => expect(mocks.signInWithPassword).toHaveBeenCalled());
    resolveMembership({ data: true, error: null });
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('create-portal'));
    expect(mocks.invoke).not.toHaveBeenCalledWith('create-checkout', expect.anything());
    expect(mocks.rpc).toHaveBeenCalledTimes(1);
  });

  it('fails closed when membership lookup rejects and keeps the free app usable', async () => {
    mocks.rpc.mockRejectedValue(new Error('membership unavailable'));
    await mountMain();
    await vi.waitFor(() => expect(document.body.textContent).toContain('Partido público'));
    expect(document.querySelector('#auth-form')?.classList.contains('hidden')).toBe(false);
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('reveals VIP access only after the authoritative subscriber RPC is true', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'vip' } } } });
    mocks.rpc.mockResolvedValue({ data: true, error: null });
    await mountMain();
    await vi.waitFor(() => expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(false));

    mocks.authCallback?.('SIGNED_OUT', null);
    await vi.waitFor(() => expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(true));
  });

  it('builds a safe Telegram bot deep link without embedding a channel invite', async () => {
    vi.stubEnv('VITE_TELEGRAM_BOT_USERNAME', '@ReyTacoBot');
    await mountMain();

    const link = document.querySelector<HTMLAnchorElement>('#telegram-access-link');
    expect(link?.href).toBe('https://t.me/ReyTacoBot?start=vip_access');
    expect(link?.classList.contains('hidden')).toBe(false);
  });

  it('rejects a configured Telegram destination that is not the official bot', async () => {
    vi.stubEnv('VITE_TELEGRAM_BOT_USERNAME', '@ReyTacoBot');
    vi.stubEnv('VITE_TELEGRAM_VIP_ACCESS_URL', 'https://t.me/unrelated_channel?start=vip_access');
    await mountMain();

    const link = document.querySelector<HTMLAnchorElement>('#telegram-access-link');
    expect(link?.href).toBe('https://t.me/ReyTacoBot?start=vip_access');
    expect(link?.href).not.toContain('unrelated_channel');
  });

  it('keeps access hidden when the subscriber RPC is inactive or errors', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'user' } } } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
    await mountMain();
    expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(true);
  });

  it('retries checkout success membership four times over 15 seconds and stays closed on failure', async () => {
    window.history.replaceState({}, '', '/?checkout=success');
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'buyer' } } } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
    const app = await mountMain();
    await vi.waitFor(() => expect(mocks.rpc).toHaveBeenCalledTimes(1));
    expect(document.querySelector('#checkout-status')?.textContent).toContain('Confirmando pago…');
    expect(app.CHECKOUT_RETRY_DELAYS).toEqual([1000, 2000, 4000, 8000]);

    await vi.advanceTimersByTimeAsync(15_000);
    expect(mocks.rpc).toHaveBeenCalledTimes(5);
    expect(document.querySelector('#checkout-status')?.textContent).toContain('soporte');
    expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(true);
  });

  it('reveals access when a checkout success retry becomes active and does not trust the URL alone', async () => {
    window.history.replaceState({}, '', '/?checkout=success');
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'buyer' } } } });
    mocks.rpc.mockResolvedValueOnce({ data: false, error: null }).mockResolvedValueOnce({ data: true, error: null });
    await mountMain();
    expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(true);
    await vi.advanceTimersByTimeAsync(1000);
    await vi.waitFor(() => expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(false));
    expect(mocks.rpc).toHaveBeenCalledTimes(2);
    expect(document.querySelector('#checkout-status')?.textContent).toContain('Pago confirmado');
  });

  it('stops checkout confirmation if the authenticated session changes', async () => {
    window.history.replaceState({}, '', '/?checkout=success');
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'buyer' } } } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
    await mountMain();
    await vi.waitFor(() => expect(mocks.rpc).toHaveBeenCalledTimes(1));

    mocks.authCallback?.('SIGNED_OUT', null);
    await vi.waitFor(() => expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(true));
    await vi.advanceTimersByTimeAsync(15_000);

    expect(mocks.rpc).toHaveBeenCalledTimes(1);
    expect(document.querySelector('#checkout-status')?.textContent).toContain('cambió tu sesión');
    expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(true);
  });

  it('does not report checkout success when the session changes during the initial membership lookup', async () => {
    window.history.replaceState({}, '', '/?checkout=success');
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'buyer-a' } } } });
    let resolveBuyerA!: (result: { data: boolean; error: null }) => void;
    mocks.rpc
      .mockReturnValueOnce(new Promise(resolve => { resolveBuyerA = resolve; }))
      .mockResolvedValueOnce({ data: false, error: null });
    await mountMain();
    await vi.waitFor(() => expect(mocks.rpc).toHaveBeenCalledTimes(1));

    mocks.authCallback?.('SIGNED_IN', { user: { id: 'buyer-b' } });
    await vi.waitFor(() => expect(mocks.rpc).toHaveBeenCalledTimes(2));
    resolveBuyerA({ data: true, error: null });
    await vi.waitFor(() => expect(document.querySelector('#checkout-status')?.textContent).toContain('cambió tu sesión'));

    expect(document.querySelector('#checkout-status')?.textContent).not.toContain('Pago confirmado');
    expect(document.querySelector('#vip-access-panel')?.classList.contains('hidden')).toBe(true);
  });

  it('guards duplicate portal clicks and never emits plan selection for VIP management', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'vip' } } } });
    mocks.rpc.mockResolvedValue({ data: true, error: null });
    mocks.invoke.mockReturnValue(new Promise(() => undefined));
    await mountMain();
    document.querySelector<HTMLButtonElement>('#vip-button')?.click();
    document.querySelector<HTMLButtonElement>('#vip-button')?.click();
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledTimes(1));
    expect(mocks.invoke).toHaveBeenCalledWith('create-portal');
    expect(mocks.trackConversion).not.toHaveBeenCalledWith('vip_plan_selected', expect.anything());
  });

  it('recovers from rejected checkout and permits a retry', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'user' } } } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
    mocks.invoke.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: {}, error: null });
    await mountMain();
    const dialog = document.querySelector<HTMLDialogElement>('#auth-dialog')!;
    dialog.showModal = vi.fn();
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    await vi.waitFor(() => expect(document.querySelector('#auth-message')?.textContent).toContain('No pudimos abrir Stripe'));
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledTimes(2));
  });

  it('recovers from rejected or invalid portal creation without navigation', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: { user: { id: 'vip' } } } });
    mocks.rpc.mockResolvedValue({ data: true, error: null });
    mocks.invoke.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: { url: 'https://evil.example/pay' }, error: null });
    await mountMain();
    document.querySelector<HTMLDialogElement>('#auth-dialog')!.showModal = vi.fn();
    document.querySelector<HTMLButtonElement>('#vip-button')?.click();
    await vi.waitFor(() => expect(document.querySelector('#auth-message')?.textContent).toContain('No pudimos abrir Stripe'));
    document.querySelector<HTMLButtonElement>('#vip-button')?.click();
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledTimes(2));
    expect(window.location.href).not.toContain('evil.example');
  });

  it('clears checkout intent when auth dialog is cancelled', async () => {
    await mountMain();
    document.querySelector<HTMLButtonElement>('[data-plan="weekly"]')?.click();
    document.querySelector<HTMLDialogElement>('#auth-dialog')?.dispatchEvent(new Event('cancel'));
    expect(sessionStorage.getItem('rey_taco_checkout_plan')).toBeNull();
  });

  it('emits checkout_cancelled once without starting checkout', async () => {
    window.history.replaceState({}, '', '/?checkout=cancelled');
    await mountMain();
    expect(mocks.trackConversion).toHaveBeenCalledWith('checkout_cancelled', expect.anything());
    expect(mocks.invoke).not.toHaveBeenCalled();
  });
});
