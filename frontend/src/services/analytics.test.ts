import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetAnalyticsForTests, trackConversion } from './analytics';

describe('conversion analytics', () => {
  afterEach(() => {
    resetAnalyticsForTests();
    delete (window as typeof window & { dataLayer?: unknown[] }).dataLayer;
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

  it('drops identifiers and free-form values from transport properties', async () => {
    vi.stubEnv('VITE_PLAUSIBLE_DOMAIN', 'reytacopicks.com');
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(new Response());
    trackConversion('free_pick_viewed', {
      surface: 'web', window_slot: '6pm', pick_id: 'secret', partido: 'A vs B', cuota: '1.8',
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const request = fetchSpy.mock.calls[0][1];
    const payload = JSON.parse(String(request?.body));
    expect(payload.props).toEqual({ surface: 'web', window_slot: '6pm' });
    expect(JSON.stringify(payload)).not.toContain('A vs B');
    expect(JSON.stringify(payload)).not.toContain('secret');
    fetchSpy.mockRestore();
  });
});
