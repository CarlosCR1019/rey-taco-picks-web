import { describe, expect, it } from 'vitest';
import { calculatePerformance } from './metrics';

describe('calculatePerformance', () => {
  it('includes losses and pending rows', () => {
    expect(calculatePerformance([
      { estado: 'ganado', cuota: 2 },
      { estado: 'perdido', cuota: 1.8 },
      { estado: 'pendiente', cuota: 2.1 },
    ])).toEqual({ wins: 1, losses: 1, pending: 1, units: 0, roi: 0 });
  });

  it('returns zero metrics for no settled picks', () => {
    expect(calculatePerformance([])).toEqual({ wins: 0, losses: 0, pending: 0, units: 0, roi: 0 });
  });
});
