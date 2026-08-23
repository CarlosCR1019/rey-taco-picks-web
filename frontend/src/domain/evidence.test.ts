import { describe, expect, it } from 'vitest';
import { formatEvidenceSupport } from './evidence';

describe('evidence support messaging', () => {
  it.each([
    '65% respaldo de datos',
    'Respaldo de datos: 65%',
    '65%',
  ])('normalizes productive payload %s to one label', raw => {
    expect(formatEvidenceSupport(raw)).toBe('Respaldo de datos: 65%');
  });

  it('uses neutral text when the field is absent', () => {
    expect(formatEvidenceSupport(null)).toBe('Respaldo de datos: No disponible');
  });
});
