import { describe, expect, it } from 'vitest';
import {
  deriveOutcome,
  formatMexicoDateTime,
  publicErrorMessage,
  validatePredictions,
  type QuinielaMatch,
  type QuinielaPrediction,
} from './domain';

const matches: QuinielaMatch[] = [
  {
    id: '11111111-1111-4111-8111-111111111111',
    displayOrder: 1,
    homeTeam: 'América',
    awayTeam: 'Pumas',
    startsAt: '2026-09-13T18:00:00Z',
    homeScore: null,
    awayScore: null,
    resultState: 'pending',
    resultSourceUrl: null,
  },
  {
    id: '22222222-2222-4222-8222-222222222222',
    displayOrder: 2,
    homeTeam: 'Tigres',
    awayTeam: 'Monterrey',
    startsAt: '2026-09-14T01:00:00Z',
    homeScore: null,
    awayScore: null,
    resultState: 'pending',
    resultSourceUrl: null,
  },
];

const validPredictions: QuinielaPrediction[] = [
  {
    matchId: matches[0]!.id,
    outcome: '1',
    predictedHomeScore: 2,
    predictedAwayScore: 1,
  },
  {
    matchId: matches[1]!.id,
    outcome: 'X',
    predictedHomeScore: 1,
    predictedAwayScore: 1,
  },
];

describe('quiniela domain', () => {
  it('derives 1, X, and 2 from the estimated score', () => {
    expect(deriveOutcome(2, 1)).toBe('1');
    expect(deriveOutcome(1, 1)).toBe('X');
    expect(deriveOutcome(0, 3)).toBe('2');
  });

  it('accepts one coherent prediction for every match', () => {
    expect(validatePredictions(matches, validPredictions)).toEqual({ ok: true });
  });

  it('rejects incomplete, duplicate, unknown, and incoherent predictions', () => {
    expect(validatePredictions(matches, validPredictions.slice(0, 1))).toEqual({
      ok: false,
      code: 'quiniela_incomplete',
    });
    expect(validatePredictions(matches, [validPredictions[0]!, validPredictions[0]!])).toEqual({
      ok: false,
      code: 'quiniela_duplicate_match',
    });
    expect(validatePredictions(matches, [validPredictions[0]!, {
      ...validPredictions[1]!, matchId: '33333333-3333-4333-8333-333333333333',
    }])).toEqual({ ok: false, code: 'quiniela_unknown_match' });
    expect(validatePredictions(matches, [{ ...validPredictions[0]!, outcome: '2' }, validPredictions[1]!]))
      .toEqual({ ok: false, code: 'quiniela_outcome_mismatch' });
  });

  it('rejects non-integer and out-of-range scores', () => {
    expect(validatePredictions(matches, [
      { ...validPredictions[0]!, predictedHomeScore: 21 }, validPredictions[1]!,
    ])).toEqual({ ok: false, code: 'quiniela_invalid_score' });
    expect(validatePredictions(matches, [
      { ...validPredictions[0]!, predictedHomeScore: 1.5 }, validPredictions[1]!,
    ])).toEqual({ ok: false, code: 'quiniela_invalid_score' });
  });

  it('formats dates in Mexico City time', () => {
    const value = formatMexicoDateTime('2026-09-13T06:00:00Z');
    expect(value).toContain('13');
    expect(value).toContain('00:00');
  });

  it('maps known backend codes and hides unknown backend text', () => {
    expect(publicErrorMessage('quiniela_closed')).toContain('cerró');
    expect(publicErrorMessage('quiniela_terms_changed')).toContain('términos');
    expect(publicErrorMessage('quiniela_result_source_mismatch')).toContain('fuente registrada');
    expect(publicErrorMessage('quiniela_result_unchanged')).toContain('cambia el marcador');
    expect(publicErrorMessage('quiniela_results_not_revised')).toContain('corrige un resultado');
    expect(publicErrorMessage('database password=secret')).toBe(
      'No pudimos completar la operación. Intenta de nuevo.',
    );
  });
});
