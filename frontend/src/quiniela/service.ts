import type {
  QuinielaMatch,
  QuinielaOutcome,
  QuinielaPrediction,
  QuinielaReceipt,
  QuinielaSnapshot,
  QuinielaStanding,
  QuinielaWeek,
} from './domain';

type RpcError = Readonly<{ message?: string }>;
type RpcResponse = Promise<Readonly<{ data: unknown; error: RpcError | null }>>;

export type QuinielaClient = Readonly<{
  rpc: (functionName: string, args?: Record<string, unknown>) => RpcResponse;
}>;

export type CreateWeekInput = Readonly<{
  seasonKey: string;
  weekKey: string;
  title: string;
  opensAt: string;
  closesAt: string;
  termsVersion: string;
  resultSourceName: string;
  resultSourceUrl: string;
}>;

export type AddMatchInput = Readonly<{
  weekId: string;
  displayOrder: number;
  homeTeam: string;
  awayTeam: string;
  startsAt: string;
}>;

export type ConfirmResultInput = Readonly<{
  matchId: string;
  homeScore: number;
  awayScore: number;
  sourceUrl: string;
}>;

const PUBLIC_CODES = new Set([
  'quiniela_auth_required',
  'quiniela_attestation_required',
  'quiniela_closed',
  'quiniela_already_submitted',
  'quiniela_terms_changed',
  'quiniela_incomplete',
  'quiniela_duplicate_match',
  'quiniela_unknown_match',
  'quiniela_invalid_score',
  'quiniela_invalid_predictions',
  'quiniela_outcome_mismatch',
  'quiniela_admin_required',
  'quiniela_invalid_week',
  'quiniela_invalid_match',
  'quiniela_invalid_deadline',
  'quiniela_results_incomplete',
  'quiniela_results_not_ready',
  'quiniela_result_source_mismatch',
  'quiniela_result_unchanged',
  'quiniela_results_not_revised',
  'quiniela_not_scored',
  'quiniela_no_entries',
  'quiniela_unavailable',
]);

export class QuinielaServiceError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = 'QuinielaServiceError';
    this.code = code;
  }
}

function fail(code = 'quiniela_unavailable'): never {
  throw new QuinielaServiceError(code);
}

function errorCode(error: RpcError | null): string {
  const found = error?.message?.match(/quiniela_[a-z_]+/)?.[0];
  return found && PUBLIC_CODES.has(found) ? found : 'quiniela_unavailable';
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail();
  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== 'string') return fail();
  return value;
}

function number(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fail();
  return value;
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function nullableNumber(value: unknown): number | null {
  return value === null ? null : number(value);
}

function parseOutcome(value: unknown): QuinielaOutcome {
  if (value === '1' || value === 'X' || value === '2') return value;
  return fail();
}

function parseWeek(value: unknown): QuinielaWeek {
  const row = record(value);
  const status = string(row.status);
  if (!['draft', 'open', 'locked', 'scored', 'awarded'].includes(status)) return fail();
  return {
    id: string(row.id),
    seasonKey: string(row.season_key),
    weekKey: string(row.week_key),
    title: string(row.title),
    status: status as QuinielaWeek['status'],
    opensAt: string(row.opens_at),
    closesAt: string(row.closes_at),
    termsVersion: string(row.terms_version),
    resultSourceName: string(row.result_source_name),
    resultSourceUrl: string(row.result_source_url),
    resultsCheckedAt: nullableString(row.results_checked_at),
  };
}

function parseMatch(value: unknown): QuinielaMatch {
  const row = record(value);
  const resultState = string(row.result_state);
  if (!['pending', 'confirmed', 'corrected'].includes(resultState)) return fail();
  return {
    id: string(row.id),
    displayOrder: number(row.display_order),
    homeTeam: string(row.home_team),
    awayTeam: string(row.away_team),
    startsAt: string(row.starts_at),
    homeScore: nullableNumber(row.home_score),
    awayScore: nullableNumber(row.away_score),
    resultState: resultState as QuinielaMatch['resultState'],
    resultSourceUrl: nullableString(row.result_source_url),
  };
}

function parsePrediction(value: unknown): QuinielaPrediction {
  const row = record(value);
  return {
    matchId: string(row.match_id),
    outcome: parseOutcome(row.outcome),
    predictedHomeScore: number(row.predicted_home_score),
    predictedAwayScore: number(row.predicted_away_score),
  };
}

function parseReceipt(value: unknown): QuinielaReceipt {
  const row = record(value);
  if (!Array.isArray(row.predictions)) return fail();
  return {
    entryId: string(row.entry_id),
    publicAlias: string(row.public_alias),
    submittedAt: string(row.submitted_at),
    termsVersion: string(row.terms_version),
    predictions: row.predictions.map(parsePrediction),
  };
}

function parseStanding(value: unknown): QuinielaStanding {
  const row = record(value);
  if (typeof row.is_winner !== 'boolean') return fail();
  return {
    rank: number(row.rank),
    entryId: string(row.entry_id),
    publicAlias: string(row.public_alias),
    correctOutcomes: number(row.correct_outcomes),
    scoreError: number(row.score_error),
    submittedAt: string(row.submitted_at),
    isWinner: row.is_winner,
  };
}

async function call(
  client: QuinielaClient,
  functionName: string,
  args?: Record<string, unknown>,
): Promise<unknown> {
  const response = args === undefined
    ? await client.rpc(functionName)
    : await client.rpc(functionName, args);
  if (response.error) return fail(errorCode(response.error));
  return response.data;
}

export async function loadQuiniela(client: QuinielaClient): Promise<QuinielaSnapshot> {
  const payload = record(await call(client, 'get_current_quiniela'));
  if (!Array.isArray(payload.matches) || !Array.isArray(payload.standings)
      || typeof payload.is_admin !== 'boolean') return fail();
  const entryState = payload.entry_state;
  if (entryState !== null && entryState !== 'upcoming' && entryState !== 'open' && entryState !== 'closed') {
    return fail();
  }
  return {
    week: payload.week === null ? null : parseWeek(payload.week),
    matches: payload.matches.map(parseMatch),
    receipt: payload.receipt === null ? null : parseReceipt(payload.receipt),
    standings: payload.standings.map(parseStanding),
    entryState,
    isAdmin: payload.is_admin,
  };
}

export async function submitEntry(
  client: QuinielaClient,
  weekId: string,
  termsVersion: string,
  adultInMexico: boolean,
  predictions: readonly QuinielaPrediction[],
): Promise<QuinielaReceipt> {
  const payload = record(await call(client, 'submit_quiniela_entry', {
    p_week_id: weekId,
    p_terms_version: termsVersion,
    p_adult_in_mexico: adultInMexico,
    p_predictions: predictions.map(prediction => ({
      match_id: prediction.matchId,
      outcome: prediction.outcome,
      predicted_home_score: prediction.predictedHomeScore,
      predicted_away_score: prediction.predictedAwayScore,
    })),
  }));
  return {
    entryId: string(payload.entry_id),
    publicAlias: string(payload.public_alias),
    submittedAt: string(payload.submitted_at),
    termsVersion,
    predictions: [...predictions],
  };
}

export function createWeek(client: QuinielaClient, input: CreateWeekInput): Promise<unknown> {
  return call(client, 'create_quiniela_week', {
    p_season_key: input.seasonKey,
    p_week_key: input.weekKey,
    p_title: input.title,
    p_opens_at: input.opensAt,
    p_closes_at: input.closesAt,
    p_terms_version: input.termsVersion,
    p_result_source_name: input.resultSourceName,
    p_result_source_url: input.resultSourceUrl,
  });
}

export function addMatch(client: QuinielaClient, input: AddMatchInput): Promise<unknown> {
  return call(client, 'add_quiniela_match', {
    p_week_id: input.weekId,
    p_display_order: input.displayOrder,
    p_home_team: input.homeTeam,
    p_away_team: input.awayTeam,
    p_starts_at: input.startsAt,
  });
}

export function openWeek(client: QuinielaClient, weekId: string): Promise<unknown> {
  return call(client, 'open_quiniela_week', { p_week_id: weekId });
}

export function confirmResult(client: QuinielaClient, input: ConfirmResultInput): Promise<unknown> {
  return call(client, 'confirm_quiniela_result', {
    p_match_id: input.matchId,
    p_home_score: input.homeScore,
    p_away_score: input.awayScore,
    p_source_url: input.sourceUrl,
  });
}

export function scoreWeek(client: QuinielaClient, weekId: string): Promise<unknown> {
  return call(client, 'score_quiniela_week', { p_week_id: weekId });
}

export function awardWeek(client: QuinielaClient, weekId: string): Promise<unknown> {
  return call(client, 'award_quiniela_week', { p_week_id: weekId });
}

export function reverseAward(
  client: QuinielaClient,
  weekId: string,
  reason: string,
): Promise<unknown> {
  return call(client, 'reverse_quiniela_award', { p_week_id: weekId, p_reason: reason });
}
