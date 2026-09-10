import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
import {
  choosePublicPicks,
  escapeHtml,
  LEGACY_PUBLIC_PICK_FIELDS,
  loadActiveOfferCounts,
  loadDailyPublicPicks,
  loadHistory,
  loadPublicPicks,
  normalizePick,
  PUBLIC_PICK_FIELDS,
} from './data';

const rows = [
  { id: 1, categoria: 'MLB', partido: 'A vs B', pick: 'Más de 8.5', cuota: '1.90', estado: 'pendiente', es_parlay: true },
  { id: 2, categoria: 'Liga MX', partido: 'C vs D', pick: 'Local gana', cuota: '1.75', estado: 'pendiente', es_parlay: false },
  { id: 3, categoria: 'Liga MX', partido: 'E vs F', pick: 'Visitante gana', cuota: '2.05', estado: 'pendiente', es_parlay: false },
];

describe('public pick data', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('chooses exactly two pending, non-parlay public selections', () => {
    expect(choosePublicPicks(rows)).toEqual([
      expect.objectContaining({ id: 2, visibility: 'public' }),
      expect.objectContaining({ id: 3, visibility: 'public' }),
    ]);
  });

  it('requests two current public rows from Supabase', async () => {
    const limits: number[] = [];
    const response = { data: rows.slice(1), error: null };
    const builder = {
      eq: () => builder,
      order: () => builder,
      limit: (value: number) => {
        limits.push(value);
        return Promise.resolve(response);
      },
    };
    const client = {
      from: () => ({ select: () => builder }),
    } as unknown as SupabaseClient;

    expect(await loadPublicPicks(client)).toHaveLength(2);
    expect(limits).toEqual([2]);
  });

  it('loads every public state for one CDMX event date without a row limit', async () => {
    const calls: Array<[string, unknown]> = [];
    const response = { data: [
      { ...rows[1], fecha_evento: '2026-08-25' },
      { ...rows[2], fecha_evento: '2026-08-25', estado: 'ganado' },
    ], error: null };
    const builder = {
      eq: (field: string, value: unknown) => { calls.push([field, value]); return builder; },
      in: (field: string, value: unknown) => { calls.push([field, value]); return builder; },
      order: () => Promise.resolve(response),
    };
    const client = { from: () => ({ select: () => builder }) } as unknown as SupabaseClient;

    const result = await loadDailyPublicPicks(client, '2026-08-25');

    expect(result).toHaveLength(2);
    expect(calls).toContainEqual(['fecha_evento', '2026-08-25']);
    expect(calls).toContainEqual(['estado', ['pendiente', 'ganado', 'perdido', 'void', 'revision_pendiente']]);
  });

  it('normalizes missing values without inventing results', () => {
    expect(normalizePick({ id: 9, estado: 'perdido' })).toMatchObject({
      id: 9,
      partido: 'Evento por confirmar',
      estado: 'perdido',
    });
  });

  it('normalizes the Playdoit display schedule to a sortable CDMX time', () => {
    expect(normalizePick({ id: 10, horario: 'Hoy 15:15 hrs' }).horario).toBe('15:15');
    expect(normalizePick({ id: 11, horario: 'Mañana 6:05 hrs' }).horario).toBe('06:05');
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

  it('does not revive a stale local pick when the public view is simply empty', async () => {
    const response = { data: [], error: null };
    const builder = {
      eq: () => builder,
      order: () => builder,
      limit: () => builder,
      then: (resolve: (value: typeof response) => void) => Promise.resolve(response).then(resolve),
    };
    const client = { from: () => ({ select: () => builder }) } as unknown as SupabaseClient;
    const fallback = vi.fn();
    vi.stubGlobal('fetch', fallback);

    expect(await loadPublicPicks(client)).toEqual([]);
    expect(fallback).not.toHaveBeenCalled();
  });

  it('never requests private reasoning from a public relation', () => {
    expect(PUBLIC_PICK_FIELDS.split(',')).not.toContain('razonamiento');
    expect(LEGACY_PUBLIC_PICK_FIELDS.split(',')).not.toContain('razonamiento');
  });
});

describe('active offer counts', () => {
  it('loads one bounded aggregate row without copying unknown fields', async () => {
    const rpc = vi.fn().mockResolvedValue({
      data: [{
        window_start: '2026-09-10T00:00:00.000Z',
        public_count: 2,
        premium_count: 4,
        unknown_private_field: 'must not escape',
      }],
      error: null,
    });
    const client = { rpc } as unknown as SupabaseClient;

    expect(await loadActiveOfferCounts(client)).toEqual({
      windowStart: '2026-09-10T00:00:00.000Z',
      publicCount: 2,
      premiumCount: 4,
    });
    expect(rpc).toHaveBeenCalledOnce();
    expect(rpc).toHaveBeenCalledWith('get_active_offer_counts');
  });

  it('accepts an ISO timestamp with an explicit UTC offset', async () => {
    const client = { rpc: vi.fn().mockResolvedValue({
      data: [{ window_start: '2026-09-10T00:00:00.000-06:00', public_count: 2, premium_count: 4 }],
      error: null,
    }) } as unknown as SupabaseClient;

    expect(await loadActiveOfferCounts(client)).toEqual({
      windowStart: '2026-09-10T00:00:00.000-06:00',
      publicCount: 2,
      premiumCount: 4,
    });
  });

  it.each([
    ['RPC errors', { data: null, error: { message: 'denied' } }],
    ['zero rows', { data: [], error: null }],
    ['a null row', { data: [null], error: null }],
    ['multiple rows', { data: [
      { window_start: '2026-09-10T00:00:00.000Z', public_count: 2, premium_count: 4 },
      { window_start: '2026-09-10T06:00:00.000Z', public_count: 1, premium_count: 3 },
    ], error: null }],
    ['a missing window start', { data: [{ public_count: 2, premium_count: 4 }], error: null }],
    ['a missing public count', { data: [{ window_start: '2026-09-10T00:00:00.000Z', premium_count: 4 }], error: null }],
    ['a missing premium count', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: 2 }], error: null }],
    ['an invalid date', { data: [{ window_start: 'not-a-date', public_count: 2, premium_count: 4 }], error: null }],
    ['a numeric timestamp', { data: [{ window_start: 0, public_count: 2, premium_count: 4 }], error: null }],
    ['an object timestamp', { data: [{ window_start: { toString: () => '2026-09-10T00:00:00.000Z' }, public_count: 2, premium_count: 4 }], error: null }],
    ['an impossible calendar date', { data: [{ window_start: '2026-02-30T00:00:00.000Z', public_count: 2, premium_count: 4 }], error: null }],
    ['a negative public count', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: -1, premium_count: 4 }], error: null }],
    ['a negative premium count', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: 2, premium_count: -1 }], error: null }],
    ['a fractional public count', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: 1.5, premium_count: 4 }], error: null }],
    ['a fractional premium count', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: 2, premium_count: 3.5 }], error: null }],
    ['a public count above six', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: 7, premium_count: 0 }], error: null }],
    ['a premium count above six', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: 0, premium_count: 7 }], error: null }],
    ['a combined count above six', { data: [{ window_start: '2026-09-10T00:00:00.000Z', public_count: 3, premium_count: 4 }], error: null }],
  ])('returns null for %s', async (_case, response) => {
    const client = { rpc: vi.fn().mockResolvedValue(response) } as unknown as SupabaseClient;

    expect(await loadActiveOfferCounts(client)).toBeNull();
  });
});
