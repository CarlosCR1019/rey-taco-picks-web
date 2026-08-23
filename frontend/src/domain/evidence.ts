const PREFIX = /^respaldo\s+de\s+datos\s*:\s*/i;
const SUFFIX = /\s+respaldo\s+de\s+datos\s*$/i;

export function formatEvidenceSupport(value: unknown): string {
  const raw = value === null || value === undefined || value === ''
    ? 'No disponible'
    : String(value).trim();
  const normalized = raw.replace(PREFIX, '').replace(SUFFIX, '').trim() || 'No disponible';
  return `Respaldo de datos: ${normalized}`;
}
