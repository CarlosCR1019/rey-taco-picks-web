import { afterEach, describe, expect, it } from 'vitest';
import { trackConversion } from './analytics';

describe('conversion analytics', () => {
  afterEach(() => { delete (window as typeof window & { dataLayer?: unknown[] }).dataLayer; });

  it('emits an approved event without personal data', () => {
    trackConversion('telegram_clicked');
    expect((window as typeof window & { dataLayer?: unknown[] }).dataLayer).toEqual([
      { event: 'telegram_clicked' },
    ]);
  });
});
