import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  QuinielaServiceError,
  addMatch,
  awardWeek,
  confirmResult,
  createWeek,
  loadQuiniela,
  openWeek,
  reverseAward,
  scoreWeek,
  submitEntry,
  type QuinielaClient,
} from './service';

const rpc = vi.fn();
const client: QuinielaClient = { rpc };

const wireSnapshot = {
  week: {
    id: 'week-id', season_key: 'apertura-2026', week_key: 'j7', title: 'Jornada 7',
    status: 'open', opens_at: '2026-09-10T00:00:00Z', closes_at: '2026-09-13T17:00:00Z',
    terms_version: '2026-09-12', result_source_name: 'Liga MX',
    result_source_url: 'https://example.com/results', results_checked_at: null,
  },
  matches: [{
    id: 'match-id', display_order: 1, home_team: 'América', away_team: 'Pumas',
    starts_at: '2026-09-13T18:00:00Z', home_score: null, away_score: null,
    result_state: 'pending', result_source_url: null,
  }],
  receipt: null,
  standings: [],
  entry_state: 'open',
  is_admin: false,
};

describe('quiniela service', () => {
  beforeEach(() => rpc.mockReset());

  it('loads and normalizes the public snapshot', async () => {
    rpc.mockResolvedValue({ data: wireSnapshot, error: null });

    const snapshot = await loadQuiniela(client);

    expect(rpc).toHaveBeenCalledWith('get_current_quiniela');
    expect(snapshot.week).toEqual(expect.objectContaining({
      seasonKey: 'apertura-2026', weekKey: 'j7', termsVersion: '2026-09-12',
    }));
    expect(snapshot.entryState).toBe('open');
    expect(snapshot.matches[0]).toEqual(expect.objectContaining({
      displayOrder: 1, homeTeam: 'América', awayTeam: 'Pumas',
    }));
  });

  it('submits the exact immutable entry payload', async () => {
    rpc.mockResolvedValue({ data: {
      entry_id: 'entry-id', public_alias: 'Jugador-ABCDEF123456',
      submitted_at: '2026-09-12T12:00:00Z',
    }, error: null });
    const predictions = [{
      matchId: 'match-id', outcome: '1' as const,
      predictedHomeScore: 2, predictedAwayScore: 1,
    }];

    const receipt = await submitEntry(client, 'week-id', '2026-09-12', true, predictions);

    expect(rpc).toHaveBeenCalledWith('submit_quiniela_entry', {
      p_week_id: 'week-id',
      p_terms_version: '2026-09-12',
      p_adult_in_mexico: true,
      p_predictions: [{
        match_id: 'match-id', outcome: '1', predicted_home_score: 2, predicted_away_score: 1,
      }],
    });
    expect(receipt).toEqual({
      entryId: 'entry-id', publicAlias: 'Jugador-ABCDEF123456',
      submittedAt: '2026-09-12T12:00:00Z', termsVersion: '2026-09-12', predictions,
    });
  });

  it('calls each narrow administrator RPC with exact parameters', async () => {
    rpc.mockResolvedValue({ data: true, error: null });
    await createWeek(client, {
      seasonKey: 'apertura-2026', weekKey: 'j7', title: 'Jornada 7',
      opensAt: '2026-09-10T00:00:00Z', closesAt: '2026-09-13T17:00:00Z',
      termsVersion: '2026-09-12', resultSourceName: 'Liga MX',
      resultSourceUrl: 'https://example.com/results',
    });
    await addMatch(client, {
      weekId: 'week-id', displayOrder: 1, homeTeam: 'América', awayTeam: 'Pumas',
      startsAt: '2026-09-13T18:00:00Z',
    });
    await openWeek(client, 'week-id');
    await confirmResult(client, {
      matchId: 'match-id', homeScore: 2, awayScore: 1,
      sourceUrl: 'https://example.com/results/match',
    });
    await scoreWeek(client, 'week-id');
    await awardWeek(client, 'week-id');
    await reverseAward(client, 'week-id', 'Resultado oficial corregido');

    expect(rpc.mock.calls.map(call => call[0])).toEqual([
      'create_quiniela_week', 'add_quiniela_match', 'open_quiniela_week',
      'confirm_quiniela_result', 'score_quiniela_week', 'award_quiniela_week',
      'reverse_quiniela_award',
    ]);
    expect(rpc).toHaveBeenCalledWith('confirm_quiniela_result', {
      p_match_id: 'match-id', p_home_score: 2, p_away_score: 1,
      p_source_url: 'https://example.com/results/match',
    });
  });

  it('keeps only an allowlisted backend error code', async () => {
    rpc.mockResolvedValue({
      data: null,
      error: { message: 'quiniela_closed detail password=secret' },
    });

    await expect(loadQuiniela(client)).rejects.toEqual(new QuinielaServiceError('quiniela_closed'));
  });

  it.each([
    'quiniela_result_unchanged',
    'quiniela_results_not_revised',
  ])('preserves the safe administrator recovery code %s', async code => {
    rpc.mockResolvedValue({
      data: null,
      error: { message: `${code} detail password=secret` },
    });

    await expect(scoreWeek(client, 'week-id')).rejects.toEqual(
      new QuinielaServiceError(code),
    );
  });

  it('maps malformed payloads and unknown errors to unavailable', async () => {
    rpc.mockResolvedValueOnce({ data: { week: { id: 7 } }, error: null });
    await expect(loadQuiniela(client)).rejects.toEqual(new QuinielaServiceError('quiniela_unavailable'));

    rpc.mockResolvedValueOnce({ data: null, error: { message: 'connection password=secret' } });
    await expect(loadQuiniela(client)).rejects.toEqual(new QuinielaServiceError('quiniela_unavailable'));
  });
});
