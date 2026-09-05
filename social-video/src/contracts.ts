const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const PICK_FIELDS = new Set(['partido', 'pick', 'cuota', 'categoria', 'estado']);
const FORBIDDEN_FIELDS = new Set([
  'token', 'telegram_id', 'file_id', 'email', 'pick_id', 'source_event_id',
]);

export type ReelKind = 'results' | 'teaser';

export type ReelPick = Readonly<{
  partido: string;
  pick: string;
  cuota: string;
  categoria?: string;
  estado?: string;
}>;

export type ReelInput = Readonly<{
  batch_id: string;
  portfolio_date: string;
  kind: ReelKind;
  picks: readonly ReelPick[];
  editorial_text: string;
  template_digest: string;
  approved_image_refs: readonly string[];
}>;

function invalid(): never {
  throw new Error('invalid reel input');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function boundedText(value: unknown, maximum: number, allowEmpty = false): value is string {
  return typeof value === 'string'
    && (allowEmpty || value.length > 0)
    && value.length <= maximum
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value);
}

function forbiddenKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return FORBIDDEN_FIELDS.has(normalized) || normalized.includes('token') || normalized.includes('secret');
}

export function parseReelInput(value: unknown): ReelInput {
  if (!isRecord(value)) invalid();
  if (Object.keys(value).some(forbiddenKey)) invalid();
  if (typeof value.batch_id !== 'string' || !UUID_PATTERN.test(value.batch_id)) invalid();
  if (typeof value.portfolio_date !== 'string' || !DATE_PATTERN.test(value.portfolio_date)) invalid();
  const parsedDate = new Date(`${value.portfolio_date}T00:00:00Z`);
  if (Number.isNaN(parsedDate.valueOf()) || parsedDate.toISOString().slice(0, 10) !== value.portfolio_date) invalid();
  if (value.kind !== 'results' && value.kind !== 'teaser') invalid();
  if (!Array.isArray(value.picks) || value.picks.length < 1 || value.picks.length > 6) invalid();
  if (!boundedText(value.editorial_text, 1000, true)) invalid();
  if (typeof value.template_digest !== 'string' || !DIGEST_PATTERN.test(value.template_digest)) invalid();
  if (!Array.isArray(value.approved_image_refs) || value.approved_image_refs.some((ref) => (
    !boundedText(ref, 512) || ref.includes('://')
  ))) invalid();

  const picks = value.picks.map((rawPick): ReelPick => {
    if (!isRecord(rawPick)) invalid();
    const keys = Object.keys(rawPick);
    if (keys.some((key) => forbiddenKey(key) || !PICK_FIELDS.has(key))) invalid();
    if (!boundedText(rawPick.partido, 240) || !boundedText(rawPick.pick, 240) || !boundedText(rawPick.cuota, 64)) invalid();
    if (rawPick.categoria !== undefined && !boundedText(rawPick.categoria, 120)) invalid();
    if (rawPick.estado !== undefined && !boundedText(rawPick.estado, 64)) invalid();
    return {
      partido: rawPick.partido,
      pick: rawPick.pick,
      cuota: rawPick.cuota,
      ...(rawPick.categoria === undefined ? {} : { categoria: rawPick.categoria }),
      ...(rawPick.estado === undefined ? {} : { estado: rawPick.estado }),
    };
  });

  return {
    batch_id: value.batch_id,
    portfolio_date: value.portfolio_date,
    kind: value.kind,
    picks,
    editorial_text: value.editorial_text,
    template_digest: value.template_digest,
    approved_image_refs: value.approved_image_refs,
  };
}
