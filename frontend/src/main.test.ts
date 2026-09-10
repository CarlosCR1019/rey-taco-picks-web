import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PickRow } from './services/data';

const mocks = vi.hoisted(() => ({
  loadActiveOfferCounts: vi.fn(),
  loadHistory: vi.fn(),
  loadLocalPublicPicks: vi.fn(),
  loadPublicPicks: vi.fn(),
  loadSubscriberPicks: vi.fn(),
  loadTicketManifest: vi.fn(),
  trackConversion: vi.fn(),
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
  loadHistory: mocks.loadHistory,
  loadLocalPublicPicks: mocks.loadLocalPublicPicks,
  loadPublicPicks: mocks.loadPublicPicks,
  loadSubscriberPicks: mocks.loadSubscriberPicks,
}));
vi.mock('./services/analytics', () => ({
  initPlausible: vi.fn(),
  trackConversion: mocks.trackConversion,
  trackWhenVisible: vi.fn(),
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
  fecha_evento: '2026-09-11',
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
    vi.resetModules();
    vi.clearAllMocks();
    localStorage.clear();
    window.history.replaceState({}, '', '/');
    mocks.loadPublicPicks.mockResolvedValue([publicPick]);
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

  it('renders the exact generic fallback when active counts are unavailable', async () => {
    mocks.loadActiveOfferCounts.mockResolvedValue(null);

    await mountMain();

    await vi.waitFor(() => {
      expect(document.querySelector('.vip-discovery strong')?.textContent).toContain('Más selecciones disponibles en VIP');
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
