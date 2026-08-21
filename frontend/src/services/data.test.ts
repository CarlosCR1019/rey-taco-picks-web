import { describe, expect, it } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
import { chooseFreePick, escapeHtml, loadHistory, normalizePick } from './data';

const rows = [
  { id: 1, categoria: 'MLB', partido: 'A vs B', pick: 'Más de 8.5', cuota: '1.90', estado: 'pendiente', es_parlay: true },
  { id: 2, categoria: 'Liga MX', partido: 'C vs D', pick: 'Local gana', cuota: '1.75', estado: 'pendiente', es_parlay: false },
  { id: 3, categoria: 'Liga MX', partido: 'E vs F', pick: 'Visitante gana', cuota: '2.05', estado: 'pendiente', es_parlay: false },
];

describe('public pick data', () => {
  it('chooses exactly one pending, non-parlay selection', () => {
    expect(chooseFreePick(rows)).toEqual([expect.objectContaining({ id: 2 })]);
  });

  it('normalizes missing values without inventing results', () => {
    expect(normalizePick({ id: 9, estado: 'perdido' })).toMatchObject({
      id: 9,
      partido: 'Evento por confirmar',
      estado: 'perdido',
    });
  });

  it('escapes database text before rendering it as HTML', () => {
    expect(escapeHtml('<img src=x onerror=alert(1)>')).not.toContain('<img');
  });

  it('retries history with legacy columns while the migration is pending', async () => {
    let queries = 0;
    const client = {
      from: () => ({
        select: () => {
          queries += 1;
          const response = queries === 1
            ? { data: null, error: { message: 'visibility does not exist' } }
            : { data: [{ id: 7, estado: 'ganado', partido: 'A vs B', pick: 'A gana' }], error: null };
          const builder = {
            in: () => builder,
            order: () => builder,
            limit: () => builder,
            then: (resolve: (value: typeof response) => void) => Promise.resolve(response).then(resolve),
          };
          return builder;
        },
      }),
    } as unknown as SupabaseClient;

    const history = await loadHistory(client);
    expect(queries).toBe(2);
    expect(history).toEqual([expect.objectContaining({ id: 7, estado: 'ganado' })]);
  });
});
