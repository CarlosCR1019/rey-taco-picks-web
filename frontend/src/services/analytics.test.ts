import { afterEach, describe, expect, it, vi } from 'vitest';
import { initUmami, resetAnalyticsForTests, trackConversion } from './analytics';

describe('conversion analytics', () => {
  afterEach(() => {
    resetAnalyticsForTests();
    delete (window as typeof window & { dataLayer?: unknown[] }).dataLayer;
    delete (window as typeof window & { umami?: unknown }).umami;
    document.getElementById('umami-script')?.remove();
    vi.unstubAllEnvs();
  });

  it('emits an approved event without personal data', () => {
    trackConversion('telegram_clicked');
    expect((window as typeof window & { dataLayer?: unknown[] }).dataLayer).toEqual([
      { event: 'telegram_clicked' },
    ]);
  });

  it('keeps dataLayer and sends no network request without a website id', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', '');
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(new Response());
    trackConversion('miniapp_opened', { surface: 'telegram_miniapp', window_slot: '12pm' });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect((window as typeof window & { dataLayer?: unknown[] }).dataLayer).toEqual([
      { event: 'miniapp_opened' },
    ]);
    fetchSpy.mockRestore();
  });

  it('queues early events and drops identifiers and free-form values', () => {
    vi.stubEnv('VITE_UMAMI_WEBSITE_ID', 'test-website-id');
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(new Response());
    initUmami();
    trackConversion('free_pick_viewed', {
      surface: 'web', window_slot: '6pm', pick_id: 'secret', partido: 'A vs B', cuota: '1.8',
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    const umami = (window as typeof window & {
      umami?: { q?: unknown[][] };
    }).umami;
    expect(umami?.q).toEqual([[
      'free_pick_viewed',
      { data: { surface: 'web', window_slot: '6pm' } },
    ]]);
    expect(JSON.stringify(umami?.q)).not.toContain('A vs B');
    expect(JSON.stringify(umami?.q)).not.toContain('secret');
    fetchSpy.mockRestore();
  });
});
