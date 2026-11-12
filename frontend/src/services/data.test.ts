import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
import {
  choosePublicPicks,
  escapeHtml,
  LEGACY_PUBLIC_PICK_FIELDS,
  loadDailyPublicPicks,
  loadHistory,
  loadPublicPicks,
  normalizeActivePick,
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
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
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

  it('loads settled history from R2 feed when available', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        kpis: { total_settled: 1, won: 1, lost: 0 },
        settled_picks: [
          {
            id: 'RT-20261111-NBA-0700',
            categoria: '🏀 NBA',
            partido: 'BKN Nets @ NO Pelicans',
            pick: 'BKN Nets +3.5 (Handicap)',
            cuota: 1.8,
            estado: 'ganado',
            fecha_evento: '2026-11-11',
          },
        ],
      }),
    });
    vi.stubGlobal('fetch', mockFetch);

    const history = await loadHistory(null);
    expect(history).toHaveLength(1);
    expect(history[0].id).toBe('RT-20261111-NBA-0700');
    expect(history[0].estado).toBe('ganado');
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

  it('normalizes active private picks from R2 feed into PickRow', () => {
    const rawR2Pick = {
      ticket_id: 'RT-20261111-NBA-0699',
      match: 'WAS Wizards @ IND Pacers',
      pick: 'WAS Wizards +1.5 (Handicap)',
      market_odds_decimal: 2.05,
      league: '🏀 NBA',
      time: '18:00 CDMX',
      date_cdmx: '2026-11-11',
      reasoning: 'Valor +EV detectado',
      status: 'active',
      is_jewel: true,
      is_free_pick: false,
    };
    const normalized = normalizeActivePick(rawR2Pick);
    expect(normalized).toEqual(expect.objectContaining({
      id: 'RT-20261111-NBA-0699',
      categoria: '🏀 NBA',
      partido: 'WAS Wizards @ IND Pacers',
      pick: 'WAS Wizards +1.5 (Handicap)',
      cuota: 2.05,
      horario: '18:00',
      fecha_evento: '2026-11-11',
      estado: 'pendiente',
      visibility: 'premium',
    }));
  });

  it('falls back to R2 active picks when Supabase daily public query returns 0 rows', async () => {
    const response = { data: [], error: null };
    const builder = {
      eq: () => builder,
      in: () => builder,
      order: () => Promise.resolve(response),
    };
    const client = { from: () => ({ select: () => builder }) } as unknown as SupabaseClient;

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([
        {
          ticket_id: 'RT-20261111-NBA-0698',
          match: 'BOS Celtics @ TOR Raptors',
          pick: 'BOS Celtics -5.5 (Handicap)',
          market_odds_decimal: 1.917,
          league: '🏀 NBA',
          time: '18:00 CDMX',
          date_cdmx: '2026-11-11',
          status: 'active',
          is_free_pick: true,
        },
      ]),
    });
    vi.stubGlobal('fetch', mockFetch);

    const picks = await loadDailyPublicPicks(client, '2026-11-11');
    expect(picks).toHaveLength(1);
    expect(picks[0].partido).toBe('BOS Celtics @ TOR Raptors');
    expect(picks[0].visibility).toBe('public');
  });
});
