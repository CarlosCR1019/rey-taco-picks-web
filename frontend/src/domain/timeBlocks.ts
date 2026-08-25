import type { PickRow } from '../services/data';

export const BOARD_TIME_ZONE = 'America/Mexico_City';

export type TimeBlockDefinition = Readonly<{
  id: 'midnight' | 'morning' | 'afternoon' | 'evening';
  label: string;
  icon: string;
}>;

export type TimeBlockGroup = Readonly<{
  definition: TimeBlockDefinition;
  rows: PickRow[];
}>;

export const TIME_BLOCKS: readonly TimeBlockDefinition[] = [
  { id: 'midnight', label: '00:00–05:59', icon: '🌙' },
  { id: 'morning', label: '06:00–11:59', icon: '☀️' },
  { id: 'afternoon', label: '12:00–17:59', icon: '🌤️' },
  { id: 'evening', label: '18:00–23:59', icon: '🌆' },
];

function mexicoParts(now: Date): Record<string, string> {
  return Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: BOARD_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now)
    .filter(part => part.type !== 'literal')
    .map(part => [part.type, part.value]));
}

export function mexicoDateKey(now: Date): string {
  const parts = mexicoParts(now);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function currentMexicoBlockIndex(now: Date): number {
  const hour = Number(mexicoParts(now).hour);
  return Math.min(3, Math.floor(hour / 6));
}

export function blockIndexFromHorario(value: string): number | null {
  const match = /^(?<hour>[01]\d|2[0-3]):(?<minute>[0-5]\d)$/.exec(value);
  return match?.groups ? Math.floor(Number(match.groups.hour) / 6) : null;
}

export function groupDailyPicks(rows: PickRow[], dateKey: string): TimeBlockGroup[] {
  const grouped = TIME_BLOCKS.map(definition => ({ definition, rows: [] as PickRow[] }));
  for (const row of rows) {
    if (row.fecha_evento !== dateKey) continue;
    const index = blockIndexFromHorario(row.horario);
    if (index === null) continue;
    grouped[index].rows.push(row);
  }
  for (const group of grouped) {
    group.rows.sort((left, right) => left.horario.localeCompare(right.horario)
      || String(left.id).localeCompare(String(right.id)));
  }
  return grouped;
}
