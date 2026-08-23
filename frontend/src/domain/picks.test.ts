import { describe, expect, it } from 'vitest';
import { publicPick, statusLabel } from './picks';

describe('public picks', () => {
  it('drops premium selection and reasoning', () => {
    expect(publicPick({ visibility: 'premium', pick: 'VIP secret', razonamiento: 'secret' }))
      .toEqual({ visibility: 'premium' });
  });

  it('keeps a public selection', () => {
    expect(publicPick({ visibility: 'public', pick: 'Más de 2.5', razonamiento: 'Datos' }))
      .toMatchObject({ pick: 'Más de 2.5', razonamiento: 'Datos' });
  });

  it('labels every result state honestly', () => {
    expect(statusLabel('perdido')).toBe('Perdido');
    expect(statusLabel('revision_pendiente')).toBe('En revisión');
  });
});
