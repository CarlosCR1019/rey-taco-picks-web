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
    horario: String(value.horario ?? ''),
    estado: (allowedStates.includes(rawState) ? rawState : 'revision_pendiente') as PickRow['estado'],
    es_parlay: Boolean(value.es_parlay),
    visibility: value.visibility === 'premium' ? 'premium' : 'public',
  };
}

export function chooseFreePick(rows: Array<Record<string, unknown>>): PickRow[] {
  const row = rows.find(value => value.estado === 'pendiente' && !value.es_parlay);
  return row ? [{ ...normalizePick(row), visibility: 'public' }] : [];
}

const SAFE_FIELDS = 'id,categoria,partido,pick,cuota,confianza,razonamiento,fecha_generacion,fecha_evento,horario,estado,es_parlay,visibility';
const LEGACY_SAFE_FIELDS = 'id,categoria,partido,pick,cuota,confianza,razonamiento,fecha_generacion,estado,es_parlay';

export async function loadPublicPicks(client: SupabaseClient): Promise<PickRow[]> {
  const response = await client.from('public_picks').select(SAFE_FIELDS).eq('estado', 'pendiente').order('id', { ascending: false }).limit(1);
  if (!response.error) return (response.data ?? []).map(normalizePick);

  return loadLocalPublicPicks();
}

export async function loadLocalPublicPicks(): Promise<PickRow[]> {
  const fallback = await fetch('/picks.json', { cache: 'no-store' });
  if (!fallback.ok) return [];
  const rows = await fallback.json() as Array<Record<string, unknown>>;
  return chooseFreePick(rows);
}

export async function loadHistory(client: SupabaseClient): Promise<PickRow[]> {
  const response = await client.from('public_picks')
    .select(SAFE_FIELDS)
    .in('estado', ['ganado', 'perdido', 'pendiente', 'void', 'revision_pendiente'])
    .order('id', { ascending: false });
  if (!response.error) return (response.data ?? []).map(normalizePick);

  const legacy = await client.from('picks')
    .select(LEGACY_SAFE_FIELDS)
    .in('estado', ['ganado', 'perdido', 'void', 'revision_pendiente'])
    .order('id', { ascending: false });
  return legacy.error ? [] : (legacy.data ?? []).map(normalizePick);
}

export async function loadSubscriberPicks(client: SupabaseClient): Promise<PickRow[]> {
  const response = await client.rpc('get_visible_picks');
  if (response.error) return [];
  return (response.data ?? []).filter((row: Record<string, unknown>) => row.estado === 'pendiente').map(normalizePick);
}
