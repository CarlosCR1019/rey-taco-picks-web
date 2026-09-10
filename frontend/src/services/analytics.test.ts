import { afterEach, describe, expect, it, vi } from 'vitest';
import { initPlausible, resetAnalyticsForTests, trackConversion } from './analytics';

describe('conversion analytics', () => {
  afterEach(() => {
    resetAnalyticsForTests();
    delete (window as typeof window & { dataLayer?: unknown[] }).dataLayer;
    delete (window as typeof window & { plausible?: unknown }).plausible;
    document.getElementById('plausible-script')?.remove();
    vi.unstubAllEnvs();
  });

  it('emits an approved event without personal data', () => {
    trackConversion('telegram_clicked');
    expect((window as typeof window & { dataLayer?: unknown[] }).dataLayer).toEqual([
      { event: 'telegram_clicked' },
    ]);
  });

  it('keeps dataLayer and sends no network request without a domain', () => {
    vi.stubEnv('VITE_PLAUSIBLE_DOMAIN', '');
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(new Response());
    trackConversion('miniapp_opened', { surface: 'telegram_miniapp', window_slot: '12pm' });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect((window as typeof window & { dataLayer?: unknown[] }).dataLayer).toEqual([
      { event: 'miniapp_opened' },
    ]);
    fetchSpy.mockRestore();
  });

  it('queues early events and drops identifiers and free-form values', () => {
    vi.stubEnv('VITE_PLAUSIBLE_DOMAIN', 'reytacopicks.com');
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(new Response());
    initPlausible();
    trackConversion('free_pick_viewed', {
      surface: 'web', window_slot: '6pm', pick_id: 'secret', partido: 'A vs B', cuota: '1.8',
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    const plausible = (window as typeof window & {
      plausible?: { q?: unknown[][] };
    }).plausible;
    expect(plausible?.q).toEqual([[
      'free_pick_viewed',
      { props: { surface: 'web', window_slot: '6pm' } },
    ]]);
    expect(JSON.stringify(plausible?.q)).not.toContain('A vs B');
    expect(JSON.stringify(plausible?.q)).not.toContain('secret');
    fetchSpy.mockRestore();
  });

  it('allows only bounded aggregate funnel properties', () => {
    vi.stubEnv('VITE_PLAUSIBLE_DOMAIN', 'reytacopicks.com');
    initPlausible();
    trackConversion('vip_primary_clicked', {
      surface: 'web', window_slot: '12am', public_pick_count: 2,
      premium_pick_count: 4, email: 'private@example.com', pick: 'secret pick',
    });
    const plausible = (window as typeof window & { plausible?: { q?: unknown[][] } }).plausible;
    expect(plausible?.q).toEqual([[
      'vip_primary_clicked',
      { props: { surface: 'web', window_slot: '12am', public_pick_count: '2', premium_pick_count: '4' } },
    ]]);
    expect(JSON.stringify(plausible?.q)).not.toContain('private@example.com');
    expect(JSON.stringify(plausible?.q)).not.toContain('secret pick');
  });
});
