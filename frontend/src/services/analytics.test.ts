import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  initUmami,
  resetAnalyticsForTests,
  trackConversion,
  trackWhenVisible,
  type AnalyticsProperties,
} from './analytics';

type TestWindow = typeof window & {
  dataLayer?: unknown[];
  umami?: { track: ReturnType<typeof vi.fn> };
};

const WEBSITE_ID = '123e4567-e89b-42d3-a456-426614174000';

describe('conversion analytics', () => {
  afterEach(() => {
    resetAnalyticsForTests();
    delete (window as TestWindow).dataLayer;
    delete (window as TestWindow).umami;
    document.getElementById('umami-script')?.remove();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('loads the Umami script once for a canonical website UUID', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    initUmami();
    initUmami();

    const scripts = document.querySelectorAll<HTMLScriptElement>('#umami-script');
    expect(scripts).toHaveLength(1);
    expect(scripts[0]?.src).toBe('https://cloud.umami.is/script.js');
    expect(scripts[0]?.defer).toBe(true);
    expect(scripts[0]?.dataset.websiteId).toBe(WEBSITE_ID);
    expect(scripts[0]?.dataset.excludeSearch).toBe('true');
    expect(scripts[0]?.dataset.excludeHash).toBe('true');
  });

  it('accepts uppercase UUIDs and normalizes the dataset value', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID.toUpperCase());
    initUmami();
    expect(document.querySelector<HTMLScriptElement>('#umami-script')?.dataset.websiteId).toBe(WEBSITE_ID);
  });

  it.each(['', 'not-a-uuid', '123e4567-e89b-02d3-a456-426614174000'])(
    'loads nothing for missing or invalid website ID %j',
    websiteId => {
      vi.stubEnv('VITE_UMAMI_WEBSITE_ID', websiteId);
      initUmami();
      expect(document.getElementById('umami-script')).toBeNull();
    },
  );

  it('keeps dataLayer behavior and calls Umami when available', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    const track = vi.fn();
    (window as TestWindow).umami = { track };

    trackConversion('miniapp_opened', { surface: 'telegram_miniapp', window_slot: '12pm' });

    expect((window as TestWindow).dataLayer).toEqual([{ event: 'miniapp_opened' }]);
    expect(track).toHaveBeenCalledWith('miniapp_opened', {
      surface: 'telegram_miniapp',
      window_slot: '12pm',
    });
  });

  it('keeps analytics failures non-blocking', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    const track = vi.fn(() => {
      throw new Error('blocked');
    });
    (window as TestWindow).umami = { track };

    expect(() => trackConversion('history_viewed')).not.toThrow();
    expect((window as TestWindow).dataLayer).toEqual([{ event: 'history_viewed' }]);
  });

  it('does not require config or Umami availability to emit dataLayer events', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', '');
    expect(() => trackConversion('telegram_clicked')).not.toThrow();
    expect((window as TestWindow).dataLayer).toEqual([{ event: 'telegram_clicked' }]);
  });

  it('does not deliver to stale Umami or queue events when config is invalid', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', '');
    const track = vi.fn();
    (window as TestWindow).umami = { track };
    trackConversion('checkout_cancelled');
    expect(track).not.toHaveBeenCalled();
  });

  it('delivers an early conversion after the Umami script loads', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    initUmami();
    trackConversion('checkout_started', { surface: 'web', plan: 'monthly' });
    const track = vi.fn();
    (window as TestWindow).umami = { track };
    document.getElementById('umami-script')?.dispatchEvent(new Event('load'));
    expect(track).toHaveBeenCalledWith('checkout_started', { surface: 'web', plan: 'monthly' });
  });

  it('allows only approved funnel properties and drops identifiers, details, tokens, and free text', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    const track = vi.fn();
    (window as TestWindow).umami = { track };

    trackConversion('checkout_started', {
      surface: 'web',
      window_slot: '6pm',
      public_pick_count: 2,
      premium_pick_count: 4,
      plan: 'weekly',
      billing_mode: 'subscription',
      email: 'private@example.com',
      user_id: 'user-123',
      telegram_id: 'telegram-123',
      stripe_id: 'cus_123',
      pick: 'secret pick',
      event_details: 'A vs B',
      token: 'secret-token',
      note: 'free text',
    });

    expect(track).toHaveBeenCalledWith('checkout_started', {
      surface: 'web',
      window_slot: '6pm',
      public_pick_count: '2',
      premium_pick_count: '4',
      plan: 'weekly',
      billing_mode: 'subscription',
    });
    expect(JSON.stringify(track.mock.calls)).not.toMatch(/private|user-123|telegram-123|cus_123|secret|A vs B|free text/);
  });

  it('drops out-of-range or non-integer counts and invalid plan values', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    const track = vi.fn();
    (window as TestWindow).umami = { track };

    trackConversion('vip_primary_clicked', {
      public_pick_count: 7,
      premium_pick_count: 1.5,
      plan: 'annual',
      billing_mode: 'invoice',
    } as unknown as AnalyticsProperties);

    expect(track).toHaveBeenCalledWith('vip_primary_clicked', {});
  });

  it('deduplicates by event, surface, and window slot', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    const track = vi.fn();
    (window as TestWindow).umami = { track };

    trackConversion('free_pick_viewed', { surface: 'web', window_slot: '6am', public_pick_count: 1 });
    trackConversion('free_pick_viewed', { surface: 'web', window_slot: '6am', public_pick_count: 2 });

    expect(track).toHaveBeenCalledTimes(1);
    expect((window as TestWindow).dataLayer).toEqual([{ event: 'free_pick_viewed' }]);
  });

  it('deduplicates plan repeats but delivers weekly and monthly selections separately', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    const track = vi.fn();
    (window as TestWindow).umami = { track };

    trackConversion('vip_plan_selected', { surface: 'web', window_slot: '6am', plan: 'weekly', billing_mode: 'payment' });
    trackConversion('vip_plan_selected', { surface: 'web', window_slot: '6am', plan: 'monthly', billing_mode: 'subscription' });
    trackConversion('vip_plan_selected', { surface: 'web', window_slot: '6am', plan: 'weekly', billing_mode: 'payment' });

    expect(track).toHaveBeenCalledTimes(2);
  });

  it('resolves visible-event property factories when intersection occurs', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', WEBSITE_ID);
    const track = vi.fn();
    (window as TestWindow).umami = { track };
    let intersect: IntersectionObserverCallback | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal('IntersectionObserver', vi.fn((callback: IntersectionObserverCallback) => {
      intersect = callback;
      return { observe: vi.fn(), disconnect };
    }));
    let properties: AnalyticsProperties = { surface: 'web', window_slot: '6am', premium_pick_count: 3 };

    trackWhenVisible(document.body, 'vip_offer_viewed', () => properties);
    properties = { surface: 'web', window_slot: '12pm', premium_pick_count: 0 };
    intersect?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);

    expect(track).toHaveBeenCalledWith('vip_offer_viewed', {
      surface: 'web',
      window_slot: '12pm',
      premium_pick_count: '0',
    });
    expect(disconnect).toHaveBeenCalledTimes(1);
  });
});
