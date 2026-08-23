import { describe, expect, it } from 'vitest';
import { getAdConfig } from './ads';

describe('AdSense configuration', () => {
  it('does not render an empty or incomplete ad unit', () => {
    expect(getAdConfig('', 'ca-pub-123')).toBeNull();
    expect(getAdConfig('123', '')).toBeNull();
  });

  it('returns the configured client and slot', () => {
    expect(getAdConfig('123', 'ca-pub-456')).toEqual({ slot: '123', client: 'ca-pub-456' });
  });
});
