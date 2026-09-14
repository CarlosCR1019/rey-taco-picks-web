export type QuinielaOutcome = '1' | 'X' | '2';
export type QuinielaWeekStatus = 'draft' | 'open' | 'locked' | 'scored' | 'awarded';
export type QuinielaResultState = 'pending' | 'confirmed' | 'corrected';
export type QuinielaEntryState = 'upcoming' | 'open' | 'closed';

export type QuinielaWeek = Readonly<{
  id: string;
  seasonKey: string;
  weekKey: string;
  title: string;
  status: QuinielaWeekStatus;
  opensAt: string;
  closesAt: string;
  termsVersion: string;
  resultSourceName: string;
  resultSourceUrl: string;
  resultsCheckedAt: string | null;
}>;

export type QuinielaMatch = Readonly<{
  id: string;
  displayOrder: number;
  homeTeam: string;
  awayTeam: string;
  startsAt: string;
  homeScore: number | null;
  awayScore: number | null;
  resultState: QuinielaResultState;
  resultSourceUrl: string | null;
}>;

export type QuinielaPrediction = Readonly<{
  matchId: string;
  outcome: QuinielaOutcome;
  predictedHomeScore: number;
  predictedAwayScore: number;
}>;

export type QuinielaReceipt = Readonly<{
  entryId: string;
  publicAlias: string;
  submittedAt: string;
  termsVersion: string;
  predictions: readonly QuinielaPrediction[];
}>;

export type QuinielaStanding = Readonly<{
  rank: number;
  entryId: string;
  publicAlias: string;
  correctOutcomes: number;
  scoreError: number;
  submittedAt: string;
  isWinner: boolean;
}>;

export type QuinielaSnapshot = Readonly<{
  week: QuinielaWeek | null;
  matches: readonly QuinielaMatch[];
  receipt: QuinielaReceipt | null;
  standings: readonly QuinielaStanding[];
  entryState: QuinielaEntryState | null;
  isAdmin: boolean;
}>;

export type PredictionValidation =
  | Readonly<{ ok: true }>
  | Readonly<{
      ok: false;
      code:
        | 'quiniela_incomplete'
        | 'quiniela_duplicate_match'
        | 'quiniela_unknown_match'
        | 'quiniela_invalid_score'
        | 'quiniela_outcome_mismatch';
    }>;

export function deriveOutcome(homeScore: number, awayScore: number): QuinielaOutcome {
  if (homeScore > awayScore) return '1';
  if (homeScore < awayScore) return '2';
  return 'X';
}
export function validatePredictions(
  matches: readonly QuinielaMatch[],
  predictions: readonly QuinielaPrediction[],
): PredictionValidation {
  if (predictions.length !== matches.length) return { ok: false, code: 'quiniela_incomplete' };

  const matchIds = new Set(matches.map(match => match.id));
  const predictionIds = new Set(predictions.map(prediction => prediction.matchId));
  if (predictionIds.size !== predictions.length) {
    return { ok: false, code: 'quiniela_duplicate_match' };
  }
  if (predictions.some(prediction => !matchIds.has(prediction.matchId))) {
    return { ok: false, code: 'quiniela_unknown_match' };
  }
  if (predictions.some(prediction =>
    !Number.isInteger(prediction.predictedHomeScore)
    || !Number.isInteger(prediction.predictedAwayScore)
    || prediction.predictedHomeScore < 0
    || prediction.predictedHomeScore > 20
    || prediction.predictedAwayScore < 0
    || prediction.predictedAwayScore > 20
  )) {
    return { ok: false, code: 'quiniela_invalid_score' };
  }
  if (predictions.some(prediction => prediction.outcome !== deriveOutcome(
    prediction.predictedHomeScore,
    prediction.predictedAwayScore,
  ))) {
    return { ok: false, code: 'quiniela_outcome_mismatch' };
  }
  return { ok: true };
}

export function formatMexicoDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Fecha no disponible';
  return new Intl.DateTimeFormat('es-MX', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'America/Mexico_City',
  }).format(date);
}

const PUBLIC_ERRORS: Readonly<Record<string, string>> = {
  quiniela_auth_required: 'Inicia sesión para enviar tu quiniela.',
  quiniela_attestation_required: 'Confirma que eres mayor de 18 años y estás en México.',
  quiniela_closed: 'La recepción de esta quiniela ya cerró.',
  quiniela_already_submitted: 'Tu participación para esta semana ya fue registrada.',
  quiniela_terms_changed: 'Los términos cambiaron. Revísalos antes de volver a enviar.',
  quiniela_incomplete: 'Completa el pronóstico de todos los partidos.',
  quiniela_duplicate_match: 'Hay un partido repetido en el formulario.',
  quiniela_unknown_match: 'Uno de los partidos ya no pertenece a esta quiniela.',
  quiniela_invalid_score: 'Cada marcador debe ser un entero entre 0 y 20.',
  quiniela_invalid_predictions: 'Revisa los pronósticos e intenta nuevamente.',
  quiniela_outcome_mismatch: 'El resultado 1/X/2 debe coincidir con el marcador estimado.',
  quiniela_admin_required: 'Esta acción requiere una cuenta administradora.',
  quiniela_invalid_week: 'Revisa la configuración de la semana.',
  quiniela_invalid_match: 'Revisa los datos del partido.',
  quiniela_invalid_deadline: 'El cierre debe ser anterior al primer partido.',
  quiniela_results_incomplete: 'Confirma todos los resultados antes de calificar.',
  quiniela_results_not_ready: 'El partido todavía no está listo para confirmar su resultado.',
  quiniela_result_source_mismatch: 'El resultado debe usar la fuente registrada para esta semana.',
  quiniela_result_unchanged: 'Para registrar una corrección, cambia el marcador o la fuente.',
  quiniela_results_not_revised: 'Antes de recalificar o premiar, corrige un resultado.',
  quiniela_not_scored: 'La semana todavía no está calificada.',
  quiniela_no_entries: 'No hay participaciones para premiar.',
};

export function publicErrorMessage(code: string): string {
  return PUBLIC_ERRORS[code] ?? 'No pudimos completar la operación. Intenta de nuevo.';
}
