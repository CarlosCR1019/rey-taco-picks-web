import { describe, expect, it } from 'vitest';
import type { PickRow } from '../services/data';
import {
  blockIndexFromHorario,
  currentMexicoBlockIndex,
  groupDailyPicks,
  mexicoDateKey,
  TIME_BLOCKS,
} from './timeBlocks';

const pick = (id: number, fecha_evento: string, horario: string): PickRow => ({
  id,
  categoria: 'Fútbol',
  partido: `Partido ${id}`,
  pick: `Pick ${id}`,
  cuota: '1.80',
  confianza: '65%',
  razonamiento: '',
  fecha_generacion: fecha_evento,
  fecha_evento,
  horario,
  estado: 'pendiente',
  es_parlay: false,
  visibility: 'public',
});

describe('CDMX six-hour board', () => {
  it.each([
    ['00:00', 0], ['05:59', 0], ['06:00', 1], ['11:59', 1],
    ['12:00', 2], ['17:59', 2], ['18:00', 3], ['23:59', 3],
  ])('assigns %s to block %i', (value, expected) => {
    expect(blockIndexFromHorario(value)).toBe(expected);
  });

  it.each(['24:00', '6:00', '06:60', '', 'texto'])('rejects invalid time %s', value => {
    expect(blockIndexFromHorario(value)).toBeNull();
  });

  it('derives the day and active block in America/Mexico_City', () => {
    const now = new Date('2026-08-26T03:30:00.000Z');
    expect(mexicoDateKey(now)).toBe('2026-08-25');
    expect(currentMexicoBlockIndex(now)).toBe(3);
  });

  it('returns four chronological groups for the requested day only', () => {
    const groups = groupDailyPicks([
      pick(3, '2026-08-25', '12:30'),
      pick(2, '2026-08-25', '06:30'),
      pick(1, '2026-08-25', '06:00'),
      pick(4, '2026-08-24', '18:00'),
      pick(5, '2026-08-25', 'hora mala'),
    ], '2026-08-25');
    expect(groups).toHaveLength(4);
    expect(groups[0].rows).toEqual([]);
    expect(groups[1].rows.map(row => row.id)).toEqual([1, 2]);
    expect(groups[2].rows.map(row => row.id)).toEqual([3]);
    expect(groups[3].rows).toEqual([]);
    expect(groups.map(group => group.definition)).toEqual(TIME_BLOCKS);
  });
});
