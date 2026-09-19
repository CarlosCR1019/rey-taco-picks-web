import { describe, expect, it } from 'vitest';
import type { PickRow } from '../services/data';
import { renderTimeBoard } from './timeBoard';

const rows: PickRow[] = [
  {
    id: 1,
    categoria: 'Fútbol',
    partido: 'Aryans vs Rainbow',
    pick: 'Aryans',
    cuota: '1.57',
    confianza: '65%',
    razonamiento: '',
    fecha_generacion: '2026-08-25',
    fecha_evento: '2026-08-25',
    horario: '03:30',
    estado: 'ganado',
    es_parlay: false,
    visibility: 'public',
  },
  {
    id: 2,
    categoria: 'Fútbol',
    partido: '<img src=x>',
    pick: 'Visitante',
    cuota: '2.10',
    confianza: '65%',
    razonamiento: '',
    fecha_generacion: '2026-08-25',
    fecha_evento: '2026-08-25',
    horario: '17:00',
    estado: 'pendiente',
    es_parlay: false,
    visibility: 'public',
  },
];

describe('time board rendering', () => {
  it('keeps all four periods visible and marks the active one', () => {
    const html = renderTimeBoard(rows, {
      dateKey: '2026-08-25', activeBlock: 2, isVip: false,
    });
    expect(html.match(/<section class="time-block/g)).toHaveLength(4);
    expect(html).toContain('00:00–05:59');
    expect(html).toContain('06:00–11:59');
    expect(html).toContain('12:00–17:59');
    expect(html).toContain('18:00–23:59');
    expect(html).toContain('time-block active');
    expect(html).toContain('Aryans');
    expect(html).toContain('Ganado');
  });

  it('shows explicit empty states and escapes database text', () => {
    const html = renderTimeBoard(rows, {
      dateKey: '2026-08-25', activeBlock: 2, isVip: false,
    });
    expect(html).toContain('Sin selección en este periodo');
    expect(html).not.toContain('<img src=x>');
    expect(html).toContain('&lt;img src=x&gt;');
  });

  it('adds one anonymous VIP discovery CTA without exposing premium rows', () => {
    const html = renderTimeBoard([
      ...rows,
      { ...rows[1], id: 3, partido: 'Partido privado', pick: 'Secreto VIP', visibility: 'premium' },
    ], {
      dateKey: '2026-08-25', activeBlock: 2, isVip: false,
    });
    expect(html.match(/inline-vip-button/g)).toHaveLength(1);
    expect(html).toContain('Más selecciones disponibles en VIP');
    expect(html).not.toContain('Partido privado');
    expect(html).not.toContain('Secreto VIP');
  });
});
