import { describe, expect, it } from 'vitest';
import type { PickRow } from '../services/data';
import { publicCounterLabel, renderPublicCards } from './picks';

const rows: PickRow[] = [
  {
    id: 1,
    categoria: 'División Premier Calcuta',
    partido: 'Kalighat MS vs East Bengal II',
    pick: 'East Bengal II',
    cuota: '1.29',
    confianza: '65%',
    razonamiento: '',
    fecha_generacion: '2026-08-24',
    fecha_evento: '2026-08-24',
    horario: '03:30',
    estado: 'pendiente',
    es_parlay: false,
    visibility: 'public',
  },
  {
    id: 2,
    categoria: 'Kazajistán Femenil',
    partido: 'Kairat (F) vs FC Atyrau Women',
    pick: 'Kairat (F)',
    cuota: '1.44',
    confianza: '65%',
    razonamiento: '',
    fecha_generacion: '2026-08-24',
    fecha_evento: '2026-08-24',
    horario: '05:00',
    estado: 'pendiente',
    es_parlay: false,
    visibility: 'public',
  },
];

describe('approved public cards', () => {
  it('renders both public selections and the four-pick VIP CTA', () => {
    const html = renderPublicCards(rows);

    expect(html).toContain('East Bengal II');
    expect(html).toContain('Kairat (F)');
    expect(html).toContain('4 picks adicionales en VIP');
    expect(html).toContain('Momio sujeto a cambio');
    expect(html).not.toContain('Razonamiento');
  });

  it('escapes untrusted database text', () => {
    const html = renderPublicCards([
      { ...rows[0], partido: '<img src=x onerror=alert(1)>' },
    ]);

    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });

  it('uses an accurate public counter', () => {
    expect(publicCounterLabel(0)).toBe('Sin selección disponible');
    expect(publicCounterLabel(1)).toBe('1 selección pública');
    expect(publicCounterLabel(2)).toBe('2 selecciones públicas');
  });
});
