import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PickRow } from './services/data';

const mocks = vi.hoisted(() => ({
  loadActiveOfferCounts: vi.fn(),
  loadDailyPublicPicks: vi.fn(),
  loadHistory: vi.fn(),
  loadLocalPublicPicks: vi.fn(),
  loadSubscriberPicks: vi.fn(),
  loadTicketManifest: vi.fn(),
  trackConversion: vi.fn(),
  trackWhenVisible: vi.fn(),
  getSession: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('./lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: mocks.getSession,
      onAuthStateChange: vi.fn(),
      signInWithPassword: vi.fn(),
      signOut: vi.fn(),
      signUp: vi.fn(),
    },
    functions: { invoke: vi.fn() },
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
  initPlausible: vi.fn(),
  trackConversion: mocks.trackConversion,
  trackWhenVisible: mocks.trackWhenVisible,
}));
vi.mock('./services/tickets', () => ({ loadTicketManifest: mocks.loadTicketManifest }));
vi.mock('./dailyVerse', () => ({ initDailyVerseBanner: vi.fn() }));

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

async function mountMain(): Promise<void> {
  document.body.innerHTML = '<div id="app"></div><div id="telegram-mini-app" class="hidden"></div>';
  await import('./main');
  await vi.waitFor(() => expect(mocks.loadHistory).toHaveBeenCalled());
}

describe('active offer integration', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllTimers();
    vi.setSystemTime(new Date('2026-09-10T17:59:59.999Z'));
    vi.resetModules();
    vi.clearAllMocks();
    localStorage.clear();
    window.history.replaceState({}, '', '/');
    mocks.loadDailyPublicPicks.mockResolvedValue([publicPick]);
    mocks.loadHistory.mockResolvedValue([]);
    mocks.loadSubscriberPicks.mockResolvedValue([]);
    mocks.loadTicketManifest.mockResolvedValue([]);
    mocks.getSession.mockResolvedValue({ data: { session: null } });
    mocks.rpc.mockResolvedValue({ data: false, error: null });
  });

  it('loads active offer counts and renders their truthful headline', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue({
      windowStart: '2026-09-10T12:00:00.000Z', publicCount: 1, premiumCount: 3,
    });

    await mountMain();

    expect(mocks.loadActiveOfferCounts).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => {
      expect(document.querySelector('.vip-discovery strong')?.textContent).toContain('1 gratis y 3 en VIP');
    });
    expect(mocks.trackConversion).toHaveBeenCalledWith('free_pick_viewed', expect.objectContaining({
      public_pick_count: 1,
      premium_pick_count: 3,
    }));
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
});
