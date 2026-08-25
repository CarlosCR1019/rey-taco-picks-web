# Six-Hour Board and Victory Wall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the current CDMX day as four always-visible six-hour pick blocks and add a progressive gallery of every original winning-ticket image below the existing public history table.

**Architecture:** Keep Supabase `public_picks` as the anonymous security boundary and query every public row for the current CDMX date, including settled results. Put timezone grouping and ticket-manifest validation in pure modules, render both features with escaped deterministic HTML, and let `main.ts` coordinate authentication, data loading, pagination, and the native `<dialog>` viewer.

**Tech Stack:** TypeScript 6, Vite 8, Vitest 3, jsdom, Supabase JS 2, semantic HTML, responsive CSS.

---

## File map

- Create `frontend/src/domain/timeBlocks.ts`: CDMX date/hour parsing and deterministic four-block grouping.
- Create `frontend/src/domain/timeBlocks.test.ts`: boundary, timezone, ordering, and invalid-data tests.
- Modify `frontend/src/services/data.ts`: load all public picks for one CDMX date without exposing premium rows.
- Modify `frontend/src/services/data.test.ts`: verify date filtering, selected columns, and absence of the old two-row limit for the daily board.
- Create `frontend/src/app/timeBoard.ts`: render four semantic sections and one anonymous VIP discovery CTA.
- Create `frontend/src/app/timeBoard.test.ts`: verify all periods, active/past states, escaping, empty states, and no premium leakage.
- Create `frontend/src/services/tickets.ts`: validate and fetch the public ticket manifest.
- Create `frontend/src/services/tickets.test.ts`: malformed, duplicate, unsafe, and network-failure coverage.
- Create `frontend/src/app/victoryWall.ts`: render six-image pages and safe original-image controls.
- Create `frontend/src/app/victoryWall.test.ts`: pagination, escaping, empty/error, and button coverage.
- Modify `frontend/src/app/template.ts`: mount the wall below history and add the accessible image dialog.
- Modify `frontend/src/main.ts`: maintain public/VIP board state, load the manifest independently, paginate, and control the dialog.
- Modify `frontend/src/style.css`: approved stacked-block and responsive wall presentation.
- Modify `frontend/public/tickets/manifest.json`: include every image captured by the bot.
- Add any new `frontend/public/tickets/ticket_<timestamp>.jpg` files already referenced by the manifest.

### Task 1: Pure CDMX time-block domain

**Files:**
- Create: `frontend/src/domain/timeBlocks.ts`
- Create: `frontend/src/domain/timeBlocks.test.ts`

- [ ] **Step 1: Write the failing boundary and timezone tests**

```ts
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
```

- [ ] **Step 2: Run the test and verify the module is missing**

Run: `npm test -- --run src/domain/timeBlocks.test.ts` from `frontend/`  
Expected: FAIL because `./timeBlocks` does not exist.

- [ ] **Step 3: Implement the minimal pure domain**

```ts
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
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', hourCycle: 'h23',
  }).formatToParts(now).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
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
```

- [ ] **Step 4: Run the focused test**

Run: `npm test -- --run src/domain/timeBlocks.test.ts` from `frontend/`  
Expected: PASS with 4 tests plus the parameterized cases.

- [ ] **Step 5: Commit the domain**

```bash
git add frontend/src/domain/timeBlocks.ts frontend/src/domain/timeBlocks.test.ts
git commit -m "feat: group daily picks into CDMX time blocks"
```

### Task 2: Daily public-board data boundary

**Files:**
- Modify: `frontend/src/services/data.ts`
- Modify: `frontend/src/services/data.test.ts`

- [ ] **Step 1: Add a failing test for the date-scoped public query**

Add to `frontend/src/services/data.test.ts`:

```ts
it('loads every public state for one CDMX event date without a row limit', async () => {
  const calls: Array<[string, unknown]> = [];
  const response = { data: [
    { ...rows[1], fecha_evento: '2026-08-25' },
    { ...rows[2], fecha_evento: '2026-08-25', estado: 'ganado' },
  ], error: null };
  const builder = {
    eq: (field: string, value: unknown) => { calls.push([field, value]); return builder; },
    in: (field: string, value: unknown) => { calls.push([field, value]); return builder; },
    order: () => Promise.resolve(response),
  };
  const client = { from: () => ({ select: () => builder }) } as unknown as SupabaseClient;

  const result = await loadDailyPublicPicks(client, '2026-08-25');

  expect(result).toHaveLength(2);
  expect(calls).toContainEqual(['fecha_evento', '2026-08-25']);
  expect(calls).toContainEqual(['estado', ['pendiente', 'ganado', 'perdido', 'void', 'revision_pendiente']]);
});
```

Import `loadDailyPublicPicks` in the existing import list.

- [ ] **Step 2: Run the focused test and verify the export is missing**

Run: `npm test -- --run src/services/data.test.ts` from `frontend/`  
Expected: FAIL because `loadDailyPublicPicks` is not exported.

- [ ] **Step 3: Add the date-scoped loader**

Add to `frontend/src/services/data.ts`:

```ts
const PUBLIC_STATES: PickRow['estado'][] = [
  'pendiente', 'ganado', 'perdido', 'void', 'revision_pendiente',
];

export async function loadDailyPublicPicks(
  client: SupabaseClient,
  dateKey: string,
): Promise<PickRow[]> {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) return [];
  const response = await client.from('public_picks')
    .select(PUBLIC_PICK_FIELDS)
    .eq('fecha_evento', dateKey)
    .in('estado', PUBLIC_STATES)
    .order('horario', { ascending: true });
  return response.error ? [] : (response.data ?? []).map(normalizePick);
}
```

Do not query `picks` directly and do not add `razonamiento`, Telegram identifiers, or premium aggregates to `PUBLIC_PICK_FIELDS`.

- [ ] **Step 4: Run the data tests**

Run: `npm test -- --run src/services/data.test.ts` from `frontend/`  
Expected: PASS, including the legacy and privacy tests.

- [ ] **Step 5: Commit the loader**

```bash
git add frontend/src/services/data.ts frontend/src/services/data.test.ts
git commit -m "feat: load the full public daily board"
```

### Task 3: Four-block renderer

**Files:**
- Create: `frontend/src/app/timeBoard.ts`
- Create: `frontend/src/app/timeBoard.test.ts`
- Modify: `frontend/src/main.ts`

- [ ] **Step 1: Write failing renderer tests**

```ts
import { describe, expect, it } from 'vitest';
import type { PickRow } from '../services/data';
import { renderTimeBoard } from './timeBoard';

const rows: PickRow[] = [
  {
    id: 1, categoria: 'Fútbol', partido: 'Aryans vs Rainbow', pick: 'Aryans', cuota: '1.57',
    confianza: '65%', razonamiento: '', fecha_generacion: '2026-08-25',
    fecha_evento: '2026-08-25', horario: '03:30', estado: 'ganado',
    es_parlay: false, visibility: 'public',
  },
  {
    id: 2, categoria: 'Fútbol', partido: '<img src=x>', pick: 'Visitante', cuota: '2.10',
    confianza: '65%', razonamiento: '', fecha_generacion: '2026-08-25',
    fecha_evento: '2026-08-25', horario: '17:00', estado: 'pendiente',
    es_parlay: false, visibility: 'public',
  },
];

describe('time board rendering', () => {
  it('keeps all four periods visible and marks the active one', () => {
    const html = renderTimeBoard(rows, {
      dateKey: '2026-08-25', activeBlock: 2, isVip: false,
    });
    expect(html.match(/<section class="time-block/g)).toHaveLength(4);
    expect(html).toContain('00:00–05:59');
    expect(html).toContain('06:00–11:59');
    expect(html).toContain('12:00–17:59');
    expect(html).toContain('18:00–23:59');
    expect(html).toContain('time-block active');
    expect(html).toContain('Aryans');
    expect(html).toContain('Ganado');
  });

  it('shows explicit empty states and escapes database text', () => {
    const html = renderTimeBoard(rows, {
      dateKey: '2026-08-25', activeBlock: 2, isVip: false,
    });
    expect(html).toContain('Sin selección en este periodo');
    expect(html).not.toContain('<img src=x>');
    expect(html).toContain('&lt;img src=x&gt;');
  });

  it('adds one anonymous VIP discovery CTA without exposing premium rows', () => {
    const html = renderTimeBoard(rows, {
      dateKey: '2026-08-25', activeBlock: 2, isVip: false,
    });
    expect(html.match(/inline-vip-button/g)).toHaveLength(1);
    expect(html).toContain('Más selecciones disponibles en VIP');
  });
});
```

- [ ] **Step 2: Run the renderer test and verify it fails**

Run: `npm test -- --run src/app/timeBoard.test.ts` from `frontend/`  
Expected: FAIL because `./timeBoard` does not exist.

- [ ] **Step 3: Implement semantic rendering with one CTA**

Create `frontend/src/app/timeBoard.ts` with:

```ts
import { formatEvidenceSupport } from '../domain/evidence';
import { groupDailyPicks } from '../domain/timeBlocks';
import { statusLabel, type PickStatus } from '../domain/picks';
import { escapeHtml, type PickRow } from '../services/data';

type BoardOptions = Readonly<{ dateKey: string; activeBlock: number; isVip: boolean }>;

function card(row: PickRow): string {
  return `<article class="pick-card public-pick-card">
    <div class="pick-meta"><span>${escapeHtml(row.categoria)}</span><span>${escapeHtml(row.horario)} CDMX</span></div>
    <h3>${escapeHtml(row.partido)}</h3>
    <span class="selection-label">Selección del Rey</span>
    <div class="selection-row"><strong>${escapeHtml(row.pick)}</strong><b>@ ${escapeHtml(row.cuota)}</b></div>
    <div class="pick-footer"><span>${escapeHtml(formatEvidenceSupport(row.confianza))}</span>
      <span class="status status-${row.estado}">${statusLabel(row.estado as PickStatus)}</span></div>
  </article>`;
}

export function renderTimeBoard(rows: PickRow[], options: BoardOptions): string {
  const groups = groupDailyPicks(rows, options.dateKey);
  const sections = groups.map((group, index) => {
    const past = index < options.activeBlock;
    const state = group.rows.length ? (past ? 'Cerrado' : index === options.activeBlock ? 'En curso' : 'Próximo') : 'Sin selección';
    const content = group.rows.length
      ? group.rows.map(card).join('')
      : '<div class="time-block-empty"><strong>Sin selección en este periodo</strong><span>No publicamos picks solo para llenar espacio.</span></div>';
    return `<section class="time-block${index === options.activeBlock ? ' active' : ''}${past ? ' past' : ''}" aria-labelledby="time-block-${group.definition.id}">
      <header><h3 id="time-block-${group.definition.id}">${group.definition.icon} ${group.definition.label}</h3><span>${state}</span></header>
      <div class="time-block-grid">${content}</div>
    </section>`;
  }).join('');
  const cta = options.isVip ? '' : `<aside class="vip-discovery"><div><strong>👑 Más selecciones disponibles en VIP</strong><span>Consulta la cartera completa antes del inicio.</span></div><button id="inline-vip-button" type="button">Quiero acceso VIP</button></aside>`;
  return `<div class="time-board">${sections}${cta}</div>`;
}
```

- [ ] **Step 4: Replace flat rendering in `main.ts`**

Import `currentMexicoBlockIndex`, `mexicoDateKey`, `renderTimeBoard`, and `loadDailyPublicPicks`. Add `publicBoard: PickRow[]` to `AppState`. In `refreshData`, compute one `now` and load the daily public rows:

```ts
const now = new Date();
const dateKey = mexicoDateKey(now);
const [board, history] = await Promise.all([
  loadDailyPublicPicks(supabase, dateKey),
  loadHistory(supabase),
]);
state.publicBoard = board;
state.picks = board;
state.history = history;
```

Change `renderPicks` to filter categories and call:

```ts
root.innerHTML = renderTimeBoard(rows, {
  dateKey: mexicoDateKey(new Date()),
  activeBlock: currentMexicoBlockIndex(new Date()),
  isVip: state.isVip,
});
```

In `checkMembership`, start from `state.publicBoard`. For active VIP merge `loadSubscriberPicks` with public settled rows by `id`; for anonymous users restore `state.publicBoard`. Never put a premium row into `publicBoard`.

- [ ] **Step 5: Run renderer, data, and existing public-card tests**

Run: `npm test -- --run src/app/timeBoard.test.ts src/services/data.test.ts src/app/picks.test.ts` from `frontend/`  
Expected: PASS.

- [ ] **Step 6: Commit the board integration**

```bash
git add frontend/src/app/timeBoard.ts frontend/src/app/timeBoard.test.ts frontend/src/main.ts
git commit -m "feat: render the daily board in four time periods"
```

### Task 4: Safe ticket-manifest service

**Files:**
- Create: `frontend/src/services/tickets.ts`
- Create: `frontend/src/services/tickets.test.ts`

- [ ] **Step 1: Write failing manifest tests**

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadTicketManifest, normalizeTicketManifest } from './tickets';

describe('ticket manifest', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('keeps unique safe filenames in source order', () => {
    expect(normalizeTicketManifest([
      'ticket_1787692765.jpg', 'ticket_1787692765.jpg', '../secret.jpg', 7,
      'ticket_1787692673.jpg',
    ])).toEqual(['ticket_1787692765.jpg', 'ticket_1787692673.jpg']);
  });

  it('returns an empty list for invalid JSON shapes', () => {
    expect(normalizeTicketManifest({ tickets: [] })).toEqual([]);
    expect(normalizeTicketManifest(null)).toEqual([]);
  });

  it('fails closed when the public manifest cannot be fetched', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    expect(await loadTicketManifest()).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test and verify the module is missing**

Run: `npm test -- --run src/services/tickets.test.ts` from `frontend/`  
Expected: FAIL because `./tickets` does not exist.

- [ ] **Step 3: Implement bounded validation and loading**

```ts
const SAFE_TICKET = /^ticket_[0-9]{1,20}[.]jpg$/;
const MAX_TICKETS = 500;

export function normalizeTicketManifest(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const entry of value) {
    if (typeof entry !== 'string' || !SAFE_TICKET.test(entry) || seen.has(entry)) continue;
    seen.add(entry);
    result.push(entry);
    if (result.length === MAX_TICKETS) break;
  }
  return result;
}

export async function loadTicketManifest(): Promise<string[]> {
  try {
    const response = await fetch('/tickets/manifest.json', { cache: 'no-store' });
    if (!response.ok) return [];
    return normalizeTicketManifest(await response.json());
  } catch {
    return [];
  }
}

export function ticketPublicUrl(filename: string): string {
  return SAFE_TICKET.test(filename) ? `/tickets/${filename}` : '';
}
```

- [ ] **Step 4: Run the service test**

Run: `npm test -- --run src/services/tickets.test.ts` from `frontend/`  
Expected: PASS.

- [ ] **Step 5: Commit the service**

```bash
git add frontend/src/services/tickets.ts frontend/src/services/tickets.test.ts
git commit -m "feat: validate the public ticket manifest"
```

### Task 5: Victory wall renderer and pagination

**Files:**
- Create: `frontend/src/app/victoryWall.ts`
- Create: `frontend/src/app/victoryWall.test.ts`

- [ ] **Step 1: Write failing wall tests**

```ts
import { describe, expect, it } from 'vitest';
import { renderVictoryWall, visibleTicketCount } from './victoryWall';

const tickets = Array.from({ length: 14 }, (_, index) => `ticket_${1000 + index}.jpg`);

describe('victory wall', () => {
  it('renders six originals initially and offers six more', () => {
    const html = renderVictoryWall(tickets, 6);
    expect(html.match(/class="victory-card"/g)).toHaveLength(6);
    expect(html).toContain('Cargar más victorias');
    expect(html).toContain('6 de 14 evidencias');
  });

  it('caps pagination at the manifest length', () => {
    expect(visibleTicketCount(6, tickets.length)).toBe(12);
    expect(visibleTicketCount(12, tickets.length)).toBe(14);
  });

  it('uses lazy original images and safe dialog controls', () => {
    const html = renderVictoryWall(tickets, 6);
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('decoding="async"');
    expect(html).toContain('data-ticket-url="/tickets/ticket_1000.jpg"');
  });

  it('shows a neutral empty state', () => {
    expect(renderVictoryWall([], 6)).toContain('Las evidencias fotográficas no están disponibles');
  });
});
```

- [ ] **Step 2: Run the test and verify the module is missing**

Run: `npm test -- --run src/app/victoryWall.test.ts` from `frontend/`  
Expected: FAIL because `./victoryWall` does not exist.

- [ ] **Step 3: Implement six-at-a-time rendering**

```ts
import { escapeHtml } from '../services/data';
import { ticketPublicUrl } from '../services/tickets';

export const TICKET_PAGE_SIZE = 6;

export function visibleTicketCount(current: number, total: number): number {
  return Math.min(Math.max(0, total), Math.max(TICKET_PAGE_SIZE, current + TICKET_PAGE_SIZE));
}

export function renderVictoryWall(tickets: string[], requested: number): string {
  if (!tickets.length) {
    return '<div class="victory-empty">Las evidencias fotográficas no están disponibles en este momento. Consulta el historial verificado.</div>';
  }
  const count = Math.min(tickets.length, Math.max(TICKET_PAGE_SIZE, requested));
  const cards = tickets.slice(0, count).map((filename, index) => {
    const url = ticketPublicUrl(filename);
    return `<button class="victory-card" type="button" data-ticket-url="${escapeHtml(url)}" aria-label="Abrir boleto ganador ${index + 1}">
      <img src="${escapeHtml(url)}" alt="Boleto ganador verificado ${index + 1}" loading="lazy" decoding="async">
      <span>Ver evidencia original</span>
    </button>`;
  }).join('');
  const more = count < tickets.length
    ? '<button id="victory-load-more" class="secondary-button" type="button">Cargar más victorias</button>'
    : '';
  return `<div class="victory-count">${count} de ${tickets.length} evidencias</div><div class="victory-grid">${cards}</div>${more}`;
}
```

- [ ] **Step 4: Run the wall tests**

Run: `npm test -- --run src/app/victoryWall.test.ts` from `frontend/`  
Expected: PASS.

- [ ] **Step 5: Commit the renderer**

```bash
git add frontend/src/app/victoryWall.ts frontend/src/app/victoryWall.test.ts
git commit -m "feat: render original winning tickets progressively"
```

### Task 6: Mount the wall, viewer, and approved responsive styling

**Files:**
- Modify: `frontend/src/app/template.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/style.css`
- Test: `frontend/src/app/render.test.ts`

- [ ] **Step 1: Add failing shell assertions**

Add to the existing shell/template test:

```ts
expect(html).toContain('id="victory-wall"');
expect(html).toContain('Muro de victorias');
expect(html).toContain('id="victory-dialog"');
expect(html.indexOf('history-table-wrap')).toBeLessThan(html.indexOf('id="victory-wall"'));
```

- [ ] **Step 2: Run the shell test and verify the wall is absent**

Run: `npm test -- --run src/app/render.test.ts` from `frontend/`  
Expected: FAIL because the approved wall markup is absent.

- [ ] **Step 3: Add wall and dialog markup below the history table**

In `frontend/src/app/template.ts`, immediately after `.history-table-wrap`, add:

```html
<section class="victory-wall-section" aria-labelledby="victory-title">
  <div class="victory-heading">
    <div><span class="section-kicker">Evidencia original</span><h3 id="victory-title">Muro de victorias</h3></div>
    <span>Fotografías recibidas por el bot, sin recrear el boleto.</span>
  </div>
  <div id="victory-wall" aria-live="polite"><div class="victory-empty">Cargando evidencias…</div></div>
</section>
```

Before the end of the shell, add:

```html
<dialog id="victory-dialog" class="victory-dialog" aria-labelledby="victory-dialog-title">
  <div class="dialog-close"><button id="victory-dialog-close" type="button" aria-label="Cerrar evidencia">×</button></div>
  <h2 id="victory-dialog-title">Evidencia original</h2>
  <img id="victory-dialog-image" alt="Boleto ganador verificado en tamaño completo">
</dialog>
```

- [ ] **Step 4: Coordinate loading and interaction in `main.ts`**

Add `tickets: string[]` and `visibleTickets: number` to `AppState`, initialized as `[]` and `6`. Import `loadTicketManifest`, `renderVictoryWall`, and `visibleTicketCount`. Add:

```ts
function renderTickets(): void {
  const root = byId('victory-wall');
  if (!root) return;
  root.innerHTML = renderVictoryWall(state.tickets, state.visibleTickets);
}

async function refreshTickets(): Promise<void> {
  state.tickets = await loadTicketManifest();
  state.visibleTickets = 6;
  renderTickets();
}
```

Use delegated click handling on `victory-wall`: `#victory-load-more` increments with `visibleTicketCount`; `[data-ticket-url]` sets `#victory-dialog-image.src` and calls `showModal()`. Clear the `src` when closing so a stale image is not retained. Call `refreshTickets()` independently from Supabase data so its failure cannot blank picks or history.

- [ ] **Step 5: Add responsive styles**

Add focused classes to `frontend/src/style.css`:

```css
.time-board { display: grid; gap: 16px; }
.time-block { padding: 18px; border: 1px solid var(--line); border-radius: 20px; background: rgba(255,253,248,.75); }
.time-block.active { border: 2px solid #d4a52e; box-shadow: 0 14px 38px rgba(170,111,5,.12); }
.time-block.past { background: #f7efe3; }
.time-block > header { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 14px; }
.time-block > header h3 { margin: 0; font-family: Georgia, serif; }
.time-block > header span { color: var(--muted); font-size: .7rem; font-weight: 900; text-transform: uppercase; }
.time-block-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }
.time-block-empty { grid-column: 1/-1; display: grid; gap: 5px; padding: 18px; border: 1px dashed #d7c2aa; border-radius: 14px; color: var(--muted); text-align: center; }
.victory-wall-section { margin-top: 42px; padding-top: 34px; border-top: 1px solid var(--line); }
.victory-heading { display: flex; justify-content: space-between; gap: 20px; align-items: end; margin-bottom: 18px; }
.victory-heading h3 { margin: 5px 0 0; font: 700 clamp(1.7rem,3vw,2.5rem) Georgia,serif; }
.victory-heading > span, .victory-count { color: var(--muted); font-size: .75rem; }
.victory-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px; margin: 10px 0 18px; }
.victory-card { min-width: 0; padding: 0; overflow: hidden; border: 1px solid #d4a52e; border-radius: 16px; background: #0b172a; color: #f5cf58; cursor: pointer; }
.victory-card img { width: 100%; aspect-ratio: 4/5; display: block; object-fit: cover; background: #0b172a; }
.victory-card span { display: block; padding: 10px; font-size: .72rem; font-weight: 800; }
.victory-empty { padding: 24px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); text-align: center; }
.victory-dialog { width: min(760px,calc(100% - 28px)); max-height: 90vh; padding: 44px 18px 18px; border: 0; border-radius: 18px; background: #07101f; color: white; }
.victory-dialog img { display: block; max-width: 100%; max-height: 75vh; margin: 0 auto; object-fit: contain; }
.victory-dialog::backdrop { background: rgba(5,8,14,.84); }
```

Add the exact responsive rules:

```css
@media (min-width: 701px) and (max-width: 960px) {
  .victory-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
}
@media (max-width: 700px) {
  .time-block-grid, .victory-grid { grid-template-columns: 1fr; }
  .victory-heading { align-items: flex-start; flex-direction: column; }
}
```

- [ ] **Step 6: Run focused UI tests and typecheck**

Run: `npm test -- --run src/app/render.test.ts src/app/timeBoard.test.ts src/app/victoryWall.test.ts` from `frontend/`  
Expected: PASS.  
Run: `npm run typecheck` from `frontend/`  
Expected: exit 0.

- [ ] **Step 7: Commit the mounted UI**

```bash
git add frontend/src/app/template.ts frontend/src/main.ts frontend/src/style.css frontend/src/app/render.test.ts
git commit -m "feat: mount the victory wall below verified history"
```

### Task 7: Include current evidence and verify the complete frontend

**Files:**
- Modify: `frontend/public/tickets/manifest.json`
- Add: current untracked `frontend/public/tickets/ticket_<timestamp>.jpg` files referenced by the manifest

- [ ] **Step 1: Validate manifest-to-file completeness**

Run from the repository root:

```powershell
$manifest = Get-Content frontend/public/tickets/manifest.json | ConvertFrom-Json
$missing = $manifest | Where-Object {
  -not (Test-Path -LiteralPath (Join-Path 'frontend/public/tickets' $_))
}
"manifest=$($manifest.Count) missing=$($missing.Count)"
```

Expected at the current checkpoint: `manifest=28 missing=0`.

- [ ] **Step 2: Add only manifest-referenced ticket artifacts**

Run `git status --short frontend/public/tickets` and confirm every untracked JPEG matches `ticket_[0-9]{1,20}.jpg` and appears in the manifest. Stage only `frontend/public/tickets/manifest.json` and those matching JPEGs; do not stage `.gitignore`, `supabase/.temp/`, or unrelated plans.

- [ ] **Step 3: Run the complete frontend suite and production build**

Run: `npm test` from `frontend/`  
Expected: all frontend tests PASS.  
Run: `npm run build` from `frontend/`  
Expected: typecheck and Vite production build exit 0.

- [ ] **Step 4: Run the repository regression suite**

Run: `python -m pytest -q` from the repository root  
Expected: existing Python suite remains green; no frontend-only change alters scraper behavior.

- [ ] **Step 5: Inspect the page at desktop and mobile widths**

Run `npm run dev -- --host 127.0.0.1` from `frontend/`, open the emitted local URL, and verify:

- all four blocks remain visible;
- current CDMX block has the gold active treatment;
- settled picks for today remain in their period;
- the history table remains above the wall;
- the wall initially shows six originals;
- “Cargar más victorias” reaches all 28 originals;
- the dialog shows the unmodified image and visible ticket ID;
- 390×844 mobile has no horizontal board/gallery overflow.

- [ ] **Step 6: Commit the current evidence set**

```bash
git add frontend/public/tickets/manifest.json frontend/public/tickets/ticket_*.jpg
git commit -m "content: publish the current winning-ticket evidence"
```

- [ ] **Step 7: Push direct-master delivery only after verification**

Run: `git status --short` and verify only pre-existing unrelated user changes remain.  
Run: `git push origin master`  
Expected: push succeeds and the hosting deployment starts from the verified commits.

## Self-review result

- Spec coverage: four blocks, CDMX boundaries, active/past/empty behavior, public/VIP separation, same-day settled rows, history retention, six-at-a-time wall, originals, lazy loading, viewer, mobile behavior, and failure isolation are each mapped to tasks.
- Placeholder scan: no TBD/TODO or unspecified error-handling steps remain.
- Type consistency: `PickRow`, `loadDailyPublicPicks`, `groupDailyPicks`, `renderTimeBoard`, `loadTicketManifest`, `renderVictoryWall`, and `visibleTicketCount` use the same signatures throughout.
