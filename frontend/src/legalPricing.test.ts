import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const terms = readFileSync('public/terminos.html', 'utf8');

describe('public VIP pricing', () => {
  it('keeps legal copy aligned with the weekly and monthly offers', () => {
    expect(terms).toContain('$129 MXN por 7 días');
    expect(terms).toContain('$349 MXN al mes');
    expect(terms).not.toContain('$299 MXN');
  });
});
