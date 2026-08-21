import { describe, expect, it, vi } from 'vitest';
import { isMembershipActive } from './membership';

describe('membership', () => {
  it('requires an active status and future period end', () => {
    vi.setSystemTime(new Date('2026-08-20T12:00:00Z'));
    expect(isMembershipActive({ status: 'active', current_period_end: '2026-09-20T12:00:00Z' })).toBe(true);
    expect(isMembershipActive({ status: 'canceled', current_period_end: '2026-09-20T12:00:00Z' })).toBe(false);
    expect(isMembershipActive({ status: 'active', current_period_end: '2026-07-20T12:00:00Z' })).toBe(false);
    vi.useRealTimers();
  });
});
