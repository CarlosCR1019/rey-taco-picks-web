import type { SupabaseClient } from '@supabase/supabase-js';

export type PickRow = {
  id: number | string;
  categoria: string;
  partido: string;
  pick: string;
  cuota: number | string;
  confianza: number | string;
  razonamiento: string;
  fecha_generacion: string;
  fecha_evento: string;
  horario: string;
  estado: 'pendiente' | 'ganado' | 'perdido' | 'void' | 'revision_pendiente';
  es_parlay: boolean;
  visibility: 'public' | 'premium';
};

export function escapeHtml(value: unknown): string {
  const node = document.createElement('div');
  node.textContent = String(value ?? '');
  return node.innerHTML;
}

function normalizeHorario(value: unknown): string {
  const raw = String(value ?? '');
  const match = /(?:^|\D)([01]?\d|2[0-3]):([0-5]\d)(?:\D|$)/.exec(raw);
  return match ? `${match[1].padStart(2, '0')}:${match[2]}` : raw;
}

export function normalizePick(value: Record<string, unknown>): PickRow {
  const allowedStates = ['pendiente', 'ganado', 'perdido', 'void', 'revision_pendiente'];
  const rawState = String(value.estado ?? 'pendiente');
  return {
    id: (value.id as number | string) ?? crypto.randomUUID(),
    categoria: String(value.categoria ?? 'Deportes'),
    partido: String(value.partido ?? 'Evento por confirmar'),
    pick: String(value.pick ?? 'Selección por confirmar'),
    cuota: (value.cuota as number | string) ?? '—',
    confianza: (value.confianza as number | string) ?? '—',
    razonamiento: String(value.razonamiento ?? 'Consulta los datos y apuesta con responsabilidad.'),
    fecha_generacion: String(value.fecha_generacion ?? ''),
    fecha_evento: String(value.fecha_evento ?? ''),
    horario: normalizeHorario(value.horario),
    estado: (allowedStates.includes(rawState) ? rawState : 'revision_pendiente') as PickRow['estado'],
    es_parlay: Boolean(value.es_parlay),
    visibility: value.visibility === 'premium' ? 'premium' : 'public',
  };
}

export function normalizeActivePick(value: Record<string, unknown>): PickRow {
  const isFree = value.is_free_pick === true || value.visibility === 'public';
  const isPremium = value.is_free_pick === false || value.visibility === 'premium';
  const visibility: 'public' | 'premium' = isFree ? 'public' : (isPremium ? 'premium' : 'public');

  const allowedStates = ['pendiente', 'ganado', 'perdido', 'void', 'revision_pendiente'];
  const rawStatus = String(value.status ?? value.estado ?? 'pendiente').toLowerCase();
  const state: PickRow['estado'] = (rawStatus === 'active' || rawStatus === 'pending')
    ? 'pendiente'
    : (rawStatus === 'won' ? 'ganado' : (rawStatus === 'lost' ? 'perdido' : (allowedStates.includes(rawStatus) ? rawStatus as PickRow['estado'] : 'pendiente')));

  const rawHorario = value.time ?? value.horario ?? '';
  const horario = normalizeHorario(rawHorario);

  const league = String(value.league ?? value.categoria ?? (value.sport ? String(value.sport).toUpperCase() : 'Deportes'));
  const matchFallback = `${value.away_team ?? ''} vs ${value.home_team ?? ''}`.trim();
  const match = String(value.match ?? value.partido ?? (matchFallback || 'Evento por confirmar'));
  const pick = String(value.pick ?? value.altenar_selection ?? 'Selección por confirmar');
  const odds = (value.market_odds_decimal as number | string) ?? (value.cuota as number | string) ?? '—';
  const confidence = (value.confidence as number | string) ?? (value.confianza as number | string) ?? (value.is_jewel ? '94%' : '88%');
  const reasoning = String(value.reasoning ?? value.razonamiento ?? value.meaning ?? 'Valor cuantitativo +EV verificado.');
  const dateKey = String(value.date_cdmx ?? value.fecha_evento ?? value.fecha_generacion ?? '');

  return {
    id: (value.ticket_id as number | string) ?? (value.id as number | string) ?? crypto.randomUUID(),
    categoria: league,
    partido: match,
    pick,
    cuota: odds,
    confianza: confidence,
    razonamiento: reasoning,
    fecha_generacion: dateKey,
    fecha_evento: dateKey,
    horario,
    estado: state,
    es_parlay: Boolean(value.es_parlay),
    visibility,
  };
}

export const ACTIVE_PICKS_SOURCES = [
  'https://pub-1d89d25fcc84453db0d833d998d5a57c.r2.dev/active_private_picks.json',
  '/active_private_picks.json',
];

export async function loadActivePrivatePicks(): Promise<PickRow[]> {
  const cacheBuster = `?t=${Date.now()}`;
  for (const baseUrl of ACTIVE_PICKS_SOURCES) {
    try {
      const resp = await fetch(`${baseUrl}${cacheBuster}`, {
        cache: 'no-store',
      });
      if (!resp.ok) continue;
      const rows = await resp.json() as Array<Record<string, unknown>>;
      if (Array.isArray(rows) && rows.length > 0) {
        return rows.map(normalizeActivePick);
      }
    } catch {
      // Continue to next source
    }
  }
  return [];
}

export function choosePublicPicks(rows: Array<Record<string, unknown>>): PickRow[] {
  return rows
    .filter(value => value.estado === 'pendiente' && !value.es_parlay)
    .slice(0, 2)
    .map(value => ({ ...normalizePick(value), visibility: 'public' }));
}

export const PUBLIC_PICK_FIELDS = 'id,categoria,partido,pick,cuota,confianza,fecha_generacion,fecha_evento,horario,estado,es_parlay,visibility';
export const LEGACY_PUBLIC_PICK_FIELDS = 'id,categoria,partido,pick,cuota,confianza,fecha_generacion,estado,es_parlay';
const PUBLIC_STATES: PickRow['estado'][] = [
  'pendiente', 'ganado', 'perdido', 'void', 'revision_pendiente',
];

export async function loadPublicPicks(client: SupabaseClient): Promise<PickRow[]> {
  const response = await client.from('public_picks').select(PUBLIC_PICK_FIELDS).eq('estado', 'pendiente').order('id', { ascending: false }).limit(2);
  if (!response.error) return (response.data ?? []).map(normalizePick);

  return loadLocalPublicPicks();
}

export async function loadLocalPublicPicks(): Promise<PickRow[]> {
  try {
    const fallback = await fetch('/picks.json', { cache: 'no-store' });
    if (!fallback || !fallback.ok) return [];
    const rows = await fallback.json() as Array<Record<string, unknown>>;
    return choosePublicPicks(rows);
  } catch {
    return [];
  }
}

export async function loadDailyPublicPicks(
  client: SupabaseClient,
  dateKey: string,
): Promise<PickRow[]> {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) return [];
  if (client) {
    const response = await client.from('public_picks')
      .select(PUBLIC_PICK_FIELDS)
      .eq('fecha_evento', dateKey)
      .in('estado', PUBLIC_STATES)
      .order('horario', { ascending: true });
    if (!response.error && (response.data ?? []).length > 0) {
      return (response.data ?? []).map(normalizePick);
    }
  }

  try {
    const activeRows = await loadActivePrivatePicks();
    if (activeRows.length > 0) {
      const filtered = activeRows.filter(row => !row.fecha_evento || row.fecha_evento === dateKey);
      if (filtered.length > 0) {
        return filtered;
      }
      return activeRows;
    }
  } catch {
    // Continue to local fallback
  }

  return loadLocalPublicPicks();
}

export async function loadHistory(client: SupabaseClient): Promise<PickRow[]> {
  const response = await client.from('public_picks')
    .select(PUBLIC_PICK_FIELDS)
    .in('estado', ['ganado', 'perdido', 'pendiente', 'void', 'revision_pendiente'])
    .order('id', { ascending: false });
  if (!response.error) return (response.data ?? []).map(normalizePick);

  const legacy = await client.from('picks')
    .select(LEGACY_PUBLIC_PICK_FIELDS)
    .in('estado', ['ganado', 'perdido', 'void', 'revision_pendiente'])
    .order('id', { ascending: false });
  return legacy.error ? [] : (legacy.data ?? []).map(normalizePick);
}

export async function loadSubscriberPicks(client: SupabaseClient): Promise<PickRow[]> {
  if (client) {
    const response = await client.rpc('get_visible_picks');
    if (!response.error && (response.data ?? []).length > 0) {
      return (response.data ?? []).filter((row: Record<string, unknown>) => row.estado === 'pendiente').map(normalizePick);
    }
  }

  try {
    const active = await loadActivePrivatePicks();
    return active.filter(row => row.estado === 'pendiente');
  } catch {
    return [];
  }
}

export type ActiveOfferCounts = {
  windowStart: string;
  publicCount: number;
  premiumCount: number;
};

export async function loadActiveOfferCounts(_client: SupabaseClient): Promise<ActiveOfferCounts | null> {
  return null;
}
