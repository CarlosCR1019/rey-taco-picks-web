# Editorial Delivery and Live Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver two attractive public picks, six VIP picks, factual Meta copy, verified result recaps, and a Supabase-backed production web experience, then validate the complete scraper flow without duplicates.

**Architecture:** Supabase remains the authoritative source for visibility, daily portfolios, delivery receipts, and verified results. Deterministic formatters create safe editorial Telegram and Meta content; optional AI may only reorder approved lines. Result reports use a claim/complete ledger keyed by batch, report kind, and destination, while the frontend reads the anonymous `public_picks` view directly and keeps `/picks.json` only as an outage fallback.

**Tech Stack:** Python 3.11, pytest, Supabase/PostgreSQL RPC, Telegram Bot API, Meta Graph API, TypeScript, Vite, Vitest, Render, GitHub Actions.

---

## File map

### Create

- `frontend/src/app/picks.ts`: pure public-card and counter rendering helpers.
- `frontend/src/app/picks.test.ts`: two-card, escaping, CTA, and mobile-safe markup tests.
- `backend/result_reporting.py`: result report domain, formatters, and destination policy.
- `backend/result_report_repository.py`: Supabase report loading and claim/complete boundary.
- `backend/result_banner.py`: deterministic 1080-square verified-result JPEG.
- `tests/test_result_reporting.py`: report eligibility, copy, disclosure, and routing tests.
- `tests/test_result_report_repository.py`: strict RPC response and ledger tests.
- `tests/test_result_banner.py`: deterministic result-artifact tests.
- `supabase/migrations/20260824150000_result_report_delivery.sql`: service-role-only report projection and idempotent delivery ledger.

### Modify

- `frontend/src/services/data.ts`: request and preserve two public pending picks.
- `frontend/src/services/data.test.ts`: enforce the two-pick public contract.
- `frontend/src/main.ts`: render approved cards, dynamic counter, VIP CTA, and complete history.
- `frontend/src/app/template.ts`: approved section labels and VIP conversion block.
- `frontend/src/style.css`: responsive cream/wine/gold/navy card and result-table styling.
- `frontend/src/style.test.ts`: responsive and brand-style assertions.
- `backend/telegram_publisher.py`: destination-aware editorial Telegram packages.
- `tests/test_telegram_publisher.py`: exact VIP/free/admin content and chunking tests.
- `backend/social_content.py`: rich deterministic safe captions.
- `backend/social_copy.py`: allow only approved editorial lines around protected facts.
- `tests/test_social_content.py`: deterministic Facebook/Instagram copy assertions.
- `tests/test_social_copy.py`: provider safety and fallback tests.
- `backend/verificar_resultados.py`: invoke report publication after persisted grading.
- `.github/workflows/scraper.yml`: add evening/night verification windows and result-publishing secrets.
- `tests/test_scraper_workflow.py`: assert the four CDMX verification windows and secret scope.
- `tests/test_supabase_contract.py`: verify the report migration, grants, and RPC shape.
- `backend/requirements.txt`: add no dependency unless result-banner tests prove one is missing.

### Operational configuration

- Render build environment: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.
- GitHub Actions secret: `TELEGRAM_FREE_CHANNEL_ID`.
- Existing GitHub result job secrets reused: service role, Telegram, Meta IDs/token, and API-Football.

---

### Task 1: Make the public web data contract return two picks

**Files:**
- Modify: `frontend/src/services/data.ts`
- Modify: `frontend/src/services/data.test.ts`

- [ ] **Step 1: Write failing two-pick tests**

Add these cases to `frontend/src/services/data.test.ts` and rename imports from
`chooseFreePick` to `choosePublicPicks`:

```ts
it('chooses exactly two pending non-parlay public selections', () => {
  expect(choosePublicPicks(rows)).toEqual([
    expect.objectContaining({ id: 2, visibility: 'public' }),
    expect.objectContaining({ id: 3, visibility: 'public' }),
  ]);
});

it('requests two current public rows from Supabase', async () => {
  const calls: Array<[string, number]> = [];
  const response = { data: rows.slice(1), error: null };
  const builder = {
    eq: () => builder,
    order: () => builder,
    limit: (value: number) => {
      calls.push(['limit', value]);
      return Promise.resolve(response);
    },
  };
  const client = {
    from: () => ({ select: () => builder }),
  } as unknown as SupabaseClient;

  expect(await loadPublicPicks(client)).toHaveLength(2);
  expect(calls).toEqual([['limit', 2]]);
});
```

- [ ] **Step 2: Run the focused test and confirm the old one-pick behavior fails**

Run:

```powershell
Set-Location frontend
npm test -- --run src/services/data.test.ts
```

Expected: FAIL because `choosePublicPicks` is not exported and the query still
uses `limit(1)`.

- [ ] **Step 3: Implement the exact two-pick selection contract**

Replace `chooseFreePick` and the two loaders in `frontend/src/services/data.ts`:

```ts
export function choosePublicPicks(rows: Array<Record<string, unknown>>): PickRow[] {
  return rows
    .filter(value => value.estado === 'pendiente' && !value.es_parlay)
    .slice(0, 2)
    .map(value => ({ ...normalizePick(value), visibility: 'public' }));
}

export async function loadPublicPicks(client: SupabaseClient): Promise<PickRow[]> {
  const response = await client.from('public_picks')
    .select(PUBLIC_PICK_FIELDS)
    .eq('estado', 'pendiente')
    .order('id', { ascending: false })
    .limit(2);
  if (!response.error) return (response.data ?? []).map(normalizePick);
  return loadLocalPublicPicks();
}

export async function loadLocalPublicPicks(): Promise<PickRow[]> {
  const fallback = await fetch('/picks.json', { cache: 'no-store' });
  if (!fallback.ok) return [];
  const rows = await fallback.json() as Array<Record<string, unknown>>;
  return choosePublicPicks(rows);
}
```

- [ ] **Step 4: Run data tests, typecheck, and commit**

Run:

```powershell
npm test -- --run src/services/data.test.ts
npm run typecheck
Set-Location ..
git add frontend/src/services/data.ts frontend/src/services/data.test.ts
git commit -m "fix: expose two public picks on web"
```

Expected: focused tests and typecheck PASS; commit contains only the two files.

---

### Task 2: Render the approved populated web design

**Files:**
- Create: `frontend/src/app/picks.ts`
- Create: `frontend/src/app/picks.test.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/app/template.ts`
- Modify: `frontend/src/style.css`
- Modify: `frontend/src/style.test.ts`

- [ ] **Step 1: Write failing pure-renderer tests**

Create `frontend/src/app/picks.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { publicCounterLabel, renderPublicCards } from './picks';

const rows = [
  { id: 1, categoria: 'Calcutta', partido: 'Kalighat MS vs East Bengal II', pick: 'East Bengal II', cuota: '1.29', confianza: '65%', horario: '03:30', fecha_evento: '2026-08-24', fecha_generacion: '', estado: 'pendiente', es_parlay: false, visibility: 'public', razonamiento: '' },
  { id: 2, categoria: 'Kazajistán F', partido: 'Kairat (F) vs Atyrau Women', pick: 'Kairat (F)', cuota: '1.44', confianza: '65%', horario: '05:00', fecha_evento: '2026-08-24', fecha_generacion: '', estado: 'pendiente', es_parlay: false, visibility: 'public', razonamiento: '' },
] as const;

describe('approved public cards', () => {
  it('renders both public selections and the four-pick VIP CTA', () => {
    const html = renderPublicCards([...rows]);
    expect(html).toContain('East Bengal II');
    expect(html).toContain('Kairat (F)');
    expect(html).toContain('4 picks adicionales en VIP');
    expect(html).not.toContain('razonamiento');
  });

  it('escapes untrusted database text', () => {
    const html = renderPublicCards([{ ...rows[0], partido: '<img onerror=alert(1)>' }]);
    expect(html).not.toContain('<img');
  });

  it('uses an accurate public counter', () => {
    expect(publicCounterLabel(0)).toBe('Sin selección disponible');
    expect(publicCounterLabel(1)).toBe('1 selección pública');
    expect(publicCounterLabel(2)).toBe('2 selecciones públicas');
  });
});
```

- [ ] **Step 2: Run the new test and confirm the missing module failure**

Run:

```powershell
Set-Location frontend
npm test -- --run src/app/picks.test.ts
```

Expected: FAIL because `app/picks.ts` does not exist.

- [ ] **Step 3: Create the pure renderer and use it from `main.ts`**

Create `frontend/src/app/picks.ts` with these exported boundaries:

```ts
import { escapeHtml, type PickRow } from '../services/data';
import { formatEvidenceSupport } from '../domain/evidence';

export function publicCounterLabel(count: number): string {
  if (count === 0) return 'Sin selección disponible';
  if (count === 1) return '1 selección pública';
  return `${count} selecciones públicas`;
}

export function renderPublicCards(rows: PickRow[]): string {
  if (!rows.length) {
    return '<div class="state-card"><strong>No hay picks disponibles.</strong><span>Vuelve más tarde; no publicamos selecciones para llenar espacio.</span></div>';
  }
  const cards = rows.map(row => `
    <article class="pick-card public-pick-card">
      <div class="pick-meta"><span>${escapeHtml(row.categoria)}</span><span>${escapeHtml(row.horario)} CDMX</span></div>
      <h3>${escapeHtml(row.partido)}</h3>
      <span class="selection-label">Selección del Rey</span>
      <div class="selection-row"><strong>${escapeHtml(row.pick)}</strong><b>@ ${escapeHtml(row.cuota)}</b></div>
      <div class="pick-footer"><span>${escapeHtml(formatEvidenceSupport(row.confianza))}</span><span>Momio sujeto a cambio</span></div>
    </article>`).join('');
  return `${cards}<aside class="vip-discovery"><div><strong>👑 4 picks adicionales en VIP</strong><span>Consulta la cartelera completa antes del inicio.</span></div><button id="inline-vip-button" type="button">Quiero acceso VIP</button></aside>`;
}
```

Modify `frontend/src/main.ts` so `renderPicks()` calls `renderPublicCards(rows)`
for non-VIP visitors and uses `publicCounterLabel(rows.length)` instead of the
hard-coded `1 selección pública`. Keep authenticated premium rendering behind
the existing membership RPC.

- [ ] **Step 4: Apply approved template labels and responsive styles**

In `frontend/src/app/template.ts`, use:

```html
<span class="section-kicker">Selección pública</span>
<h2 id="picks-title">La mesa está servida</h2>
```

and change the history heading to:

```html
<span class="section-kicker">Transparencia · resultados verificados</span>
<h2 id="history-title">Los picks que recibió VIP</h2>
```

Add to `frontend/src/style.css`:

```css
.public-pick-card { border: 1px solid #ead3ae; box-shadow: 0 8px 25px rgba(74,40,20,.07); }
.selection-label { color: #7d6256; font-size: .78rem; }
.vip-discovery { grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; gap: 20px; padding: 20px; border-radius: 18px; background: #0b172a; color: #fff; }
.vip-discovery strong { color: #f5cf58; display: block; }
.vip-discovery span { color: #c5cedd; display: block; margin-top: 4px; }
.vip-discovery button { background: #f5cf58; color: #17110a; border: 0; border-radius: 10px; padding: 11px 16px; font-weight: 800; }
@media (max-width: 720px) {
  .pick-grid { grid-template-columns: 1fr; }
  .vip-discovery { align-items: stretch; flex-direction: column; }
  .history-table-wrap { overflow-x: auto; }
}
```

Wire `#inline-vip-button` to the same `startVipCheckout` function after each
public render.

- [ ] **Step 5: Test, build, visually inspect, and commit**

Run:

```powershell
npm test -- --run src/app/picks.test.ts src/app/render.test.ts src/style.test.ts
npm run build
npm run preview -- --host 127.0.0.1
```

Inspect desktop at 1440×900 and mobile at 390×844. Confirm two cards, the Salmo
section still precedes picks, CTA is visible, and the history table does not clip.
Then stop preview and run:

```powershell
Set-Location ..
git add frontend/src/app/picks.ts frontend/src/app/picks.test.ts frontend/src/main.ts frontend/src/app/template.ts frontend/src/style.css frontend/src/style.test.ts
git commit -m "feat: render branded public portfolio"
```

---

### Task 3: Replace Telegram technical blocks with destination-aware editorials

**Files:**
- Modify: `backend/telegram_publisher.py`
- Modify: `tests/test_telegram_publisher.py`

- [ ] **Step 1: Replace old block expectations with failing editorial tests**

Add tests that assert:

```python
def test_vip_receives_one_branded_six_pick_cartelera():
    rows = [pick(partido=f"Evento {index}", pick=f"Pick {index}") for index in range(6)]
    messages = chunk_messages(rows, destination="vip")
    assert messages[0].startswith("👑 CARTELERA VIP DEL REY")
    assert "6 selecciones" in messages[0]
    assert all(f"Pick {index}" in "\n".join(messages) for index in range(6))
    assert "Evento:" not in messages[0]
    assert "Rationale:" not in messages[0]

def test_free_receives_two_public_picks_and_vip_cta_without_premium_leak():
    rows = [
        pick(pick="PUBLIC 1", visibility="public"),
        pick(pick="PUBLIC 2", visibility="public"),
        pick(pick="PREMIUM SECRET", visibility="premium"),
    ]
    messages = chunk_messages(rows, destination="free")
    joined = "\n".join(messages)
    assert joined.startswith("🌮 2 PICKS PÚBLICOS DEL REY")
    assert "PUBLIC 1" in joined and "PUBLIC 2" in joined
    assert "PREMIUM SECRET" not in joined
    assert "4 picks adicionales en VIP" in joined

def test_admin_keeps_auditable_labels_without_public_brand_copy():
    message = chunk_messages([pick()], destination="admin")[0]
    assert "Evento:" in message
    assert "Pick:" in message
    assert "Respaldo de datos:" in message
```

- [ ] **Step 2: Run tests and verify the signature/content failure**

Run:

```powershell
python -m pytest tests/test_telegram_publisher.py -q
```

Expected: FAIL because `chunk_messages` accepts `public`, not `destination`, and
VIP still uses technical blocks.

- [ ] **Step 3: Implement exact destination-aware formatting**

Use these exact boundaries in `backend/telegram_publisher.py`:

```python
TelegramMessageKind = Literal["admin", "vip", "free"]

def chunk_messages(
    picks: Iterable[Mapping[str, object]], *, destination: TelegramMessageKind
) -> list[str]:
    rows = list(picks)
    full_count = len(rows)
    if destination == "free":
        rows = public_payload(rows)
        return _editorial_messages(rows, public=True, full_count=full_count)
    if destination == "vip":
        return _editorial_messages(rows, public=False, full_count=full_count)
    return _admin_messages(rows)

def _editorial_messages(
    rows: Sequence[Mapping[str, object]], *, public: bool, full_count: int
) -> list[str]:
    if not rows:
        return []
    title = (
        f"🌮 {len(rows)} PICKS PÚBLICOS DEL REY"
        if public
        else "👑 CARTELERA VIP DEL REY"
    )
    blocks = []
    for index, row in enumerate(rows, start=1):
        event = _field(row, ("partido", "event", "evento"), "Evento no especificado", 500)
        selection = _field(row, ("pick",), "Pick no especificado", 500)
        schedule = _field(row, ("horario", "schedule"), "Horario por confirmar", 120)
        odds = _field(row, ("cuota", "price", "odds"), "—", 40)
        market = _field(row, ("mercado", "market"), "Mercado principal", 200)
        support = format_evidence_support(row.get("confianza") or row.get("confidence"))
        blocks.append(
            "\n".join(
                (
                    f"{index}. ⚽ {event}",
                    f"   🎯 {selection} @ {odds}",
                    f"   🏟️ {market} · 🕒 {schedule}",
                    f"   📊 {support}",
                )
            )
        )
    footer = []
    if public and full_count == 6 and len(rows) == 2:
        footer.append("👑 La cartelera VIP contiene 4 selecciones adicionales.")
    footer.extend(("🌐 reytacopicks.com", "18+ · Apuesta con responsabilidad"))
    return _pack_editorial(title, blocks, footer)

def _pack_editorial(title: str, blocks: Sequence[str], footer: Sequence[str]) -> list[str]:
    suffix = "\n\n" + "\n".join(footer)
    messages: list[str] = []
    current = title
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) + len(suffix) <= MAX_MESSAGE_LENGTH:
            current = candidate
            continue
        messages.append(current + suffix)
        current = title + " · CONTINUACIÓN\n\n" + block
    messages.append(current + suffix)
    return messages

def _admin_messages(rows: Sequence[Mapping[str, object]]) -> list[str]:
    messages: list[str] = []
    current = ""
    for row in rows:
        block = format_pick_block(row, public=False)
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= MAX_MESSAGE_LENGTH:
            current = candidate
        else:
            messages.append(current)
            current = block
    if current:
        messages.append(current)
    return messages
```

Modify `deliver_batch()` to call:

```python
messages = chunk_messages(full_batch, destination=destination.name)
```

Keep `_admin_messages` based on the existing `format_pick_block` for operational
auditing. Preserve the 4,000-codepoint bound and split only between complete rows.

- [ ] **Step 4: Run Telegram and scraper delivery tests**

Run:

```powershell
python -m pytest tests/test_telegram_publisher.py tests/test_scraper_pipeline.py tests/test_delivery_recovery.py -q
```

Expected: PASS, including isolation of destination failures and completed-receipt
skips.

- [ ] **Step 5: Commit**

```powershell
git add backend/telegram_publisher.py tests/test_telegram_publisher.py
git commit -m "feat: add editorial Telegram packages"
```

---

### Task 4: Make deterministic Meta copy attractive and still fail closed

**Files:**
- Modify: `backend/social_content.py`
- Modify: `backend/social_copy.py`
- Modify: `tests/test_social_content.py`
- Modify: `tests/test_social_copy.py`

- [ ] **Step 1: Write failing approved-copy tests**

Add assertions for the fallback package:

```python
def test_fallback_captions_use_premium_balanced_voice(content):
    captions = build_fallback_captions(content)
    assert captions.facebook.startswith("👑 PICK PÚBLICO DEL REY")
    assert "🎯 Selección:" in captions.facebook
    assert "📊 Momio observado:" in captions.facebook
    assert "🕒 Horario:" in captions.facebook
    assert "🌐 Consulta la cartelera:" in captions.facebook
    assert captions.instagram.startswith("🌮 LA MESA ESTÁ SERVIDA")
    assert captions.facebook != captions.instagram
    for unsafe in ("seguro", "garantizado", "profit", "+EV", "va a ganar"):
        assert unsafe.casefold() not in captions.facebook.casefold()
        assert unsafe.casefold() not in captions.instagram.casefold()
```

Add a provider test that returns one unauthorized line such as
`Este pick va a ganar` and assert `GroqCopyProvider.captions()` returns the rich
fallback, not the candidate.

- [ ] **Step 2: Run focused tests and verify the flat-copy failure**

Run:

```powershell
python -m pytest tests/test_social_content.py tests/test_social_copy.py -q
```

Expected: FAIL because fallback begins with `Información del pick` and both
platforms share the same body.

- [ ] **Step 3: Implement platform-specific deterministic lines**

Replace `_caption_lines` with two explicit builders:

```python
def _facebook_lines(content: SocialContent) -> list[str]:
    return [
        "👑 PICK PÚBLICO DEL REY",
        f"⚽ {content.event}",
        f"🎯 Selección: {content.selection}",
        f"📊 Momio observado: {content.odds_text}",
        f"🕒 Horario: {content.schedule}",
        f"🏟️ Mercado: {content.market}",
        _observation_label(content.observed_at),
        "🌐 Consulta la cartelera: reytacopicks.com",
        "18+ · Apuesta con responsabilidad",
    ]

def _instagram_lines(content: SocialContent) -> list[str]:
    return [
        "🌮 LA MESA ESTÁ SERVIDA",
        f"⚽ {content.event}",
        f"👑 {content.selection} @ {content.odds_text}",
        f"🕒 {content.schedule}",
        f"🏟️ {content.market}",
        "Guarda la publicación y consulta la cartelera pública.",
        "🌐 reytacopicks.com",
        "18+ · Apuesta con responsabilidad",
    ]
```

Append `DEMO NO VIGENTE` or `Señal de valor comparada` only under the existing
boolean gates, then append the current platform-specific hashtag constants.

In `social_copy.py`, derive `required_lines` and `allowed_lines` from the exact
fallback lines for each platform. A provider may reorder or omit only explicitly
optional neutral lines; it cannot create new lines, URLs, hashtags, numbers, or
outcome claims.

- [ ] **Step 4: Run all social tests and commit**

```powershell
python -m pytest tests/test_social_content.py tests/test_social_copy.py tests/test_social_poster.py tests/test_social_banner.py -q
git add backend/social_content.py backend/social_copy.py tests/test_social_content.py tests/test_social_copy.py
git commit -m "feat: add branded factual social copy"
```

Expected: all focused tests PASS and the current image renderer remains unchanged.

---

### Task 5: Build verified evening and final result-report packages

**Files:**
- Create: `backend/result_reporting.py`
- Create: `tests/test_result_reporting.py`

- [ ] **Step 1: Write failing result-domain tests**

Create `tests/test_result_reporting.py` with an exact six-row fixture and these
behaviors:

```python
def test_evening_report_counts_only_verified_rows():
    report = build_result_report(rows_with_states("ganado", "ganado", "pendiente", "pendiente", "pendiente", "pendiente"), kind="evening")
    assert report.eligible is True
    assert report.terminal is False
    assert "2 verificados" in report.telegram
    assert "Cierre final" not in report.telegram

def test_final_report_requires_all_six_terminal_rows():
    with pytest.raises(ValueError, match="six terminal"):
        build_result_report(rows_with_states("ganado", "ganado", "pendiente", "pendiente", "pendiente", "pendiente"), kind="final")

def test_six_wins_disclose_all_six_rows_after_settlement():
    report = build_result_report(rows_with_states(*(["ganado"] * 6)), kind="final")
    assert report.record == "6-0"
    assert report.telegram.count("✅") == 6
    assert all(row["pick"] in report.telegram for row in report.rows)
    assert "garant" not in report.telegram.casefold()

def test_losses_void_and_review_are_not_hidden():
    report = build_result_report(rows_with_states("ganado", "perdido", "void", "revision_pendiente", "ganado", "ganado"), kind="evening")
    assert "❌" in report.telegram
    assert "↩️" in report.telegram
    assert "🟡" in report.telegram
```

- [ ] **Step 2: Run test and confirm module-not-found failure**

```powershell
python -m pytest tests/test_result_reporting.py -q
```

Expected: FAIL because `backend.result_reporting` does not exist.

- [ ] **Step 3: Implement immutable report types and formatters**

Create `backend/result_reporting.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal, Mapping, Sequence
from uuid import UUID

ReportKind = Literal["evening", "final"]
TERMINAL_STATES = frozenset({"ganado", "perdido", "void", "revision_pendiente"})
STATE_ICON = {
    "ganado": "✅",
    "perdido": "❌",
    "void": "↩️",
    "revision_pendiente": "🟡",
    "pendiente": "⏳",
}

@dataclass(frozen=True)
class ResultReport:
    batch_id: str
    portfolio_date: str
    kind: ReportKind
    rows: tuple[Mapping[str, object], ...]
    eligible: bool
    terminal: bool
    record: str
    digest: str
    telegram: str
    facebook: str
    instagram: str

def build_result_report(
    rows: Sequence[Mapping[str, object]], *, kind: ReportKind
) -> ResultReport:
    if kind not in ("evening", "final"):
        raise ValueError("report kind must be evening or final")
    if len(rows) != 6:
        raise ValueError("result report requires six rows")
    normalized = tuple(dict(row) for row in rows)
    pick_ids = [row.get("id") for row in normalized]
    if len(set(pick_ids)) != 6 or any(type(value) is not int for value in pick_ids):
        raise ValueError("result report requires six unique integer pick ids")
    batch_ids = {str(row.get("batch_id", "")) for row in normalized}
    dates = {str(row.get("portfolio_date", "")) for row in normalized}
    if len(batch_ids) != 1 or len(dates) != 1:
        raise ValueError("result report rows must share batch and date")
    batch_id = batch_ids.pop()
    try:
        if str(UUID(batch_id)) != batch_id:
            raise ValueError
    except ValueError:
        raise ValueError("batch_id must be a canonical UUID") from None
    portfolio_date = dates.pop()
    terminal_rows = tuple(
        row for row in normalized if row.get("estado") in TERMINAL_STATES
    )
    if not terminal_rows:
        raise ValueError("evening report requires a verified row")
    terminal = len(terminal_rows) == 6
    if kind == "final" and not terminal:
        raise ValueError("final report requires six terminal rows")
    for row in terminal_rows:
        for field in (
            "resultado_fuente",
            "resultado_evento_id",
            "resultado_marcador",
            "resultado_verificado_at",
        ):
            if not isinstance(row.get(field), str) or not str(row[field]).strip():
                raise ValueError(f"verified row requires {field}")
    wins = sum(row.get("estado") == "ganado" for row in terminal_rows)
    losses = sum(row.get("estado") == "perdido" for row in terminal_rows)
    record = f"{wins}-{losses}"
    heading = (
        "👑 REY TACO PICKS · CIERRE VERIFICADO"
        if kind == "final"
        else "👑 REY TACO PICKS · REPORTE VESPERTINO"
    )
    lines = [heading, "", f"📊 {len(terminal_rows)} verificados · Récord {record}"]
    if not terminal:
        lines.append(f"⏳ {6 - len(terminal_rows)} selecciones pendientes")
    lines.append("")
    for row in terminal_rows:
        icon = STATE_ICON[str(row["estado"])]
        lines.append(
            f"{icon} {row['partido']} ➜ {row['pick']} @ {float(row['cuota']):.2f}"
        )
    lines.extend(("", "🌐 Historial completo: reytacopicks.com", "18+ · Apuesta con responsabilidad"))
    telegram = "\n".join(lines)
    digest_payload = [
        (row["id"], row["estado"], row["resultado_verificado_at"])
        for row in terminal_rows
    ]
    digest = sha256(
        json.dumps(digest_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    facebook = telegram + "\n\n#ReyTacoPicks #ResultadosVerificados"
    instagram = telegram + "\n\n#ReyTacoPicks #SportsPicks #ApuestasResponsables"
    return ResultReport(
        batch_id=batch_id,
        portfolio_date=portfolio_date,
        kind=kind,
        rows=terminal_rows,
        eligible=True,
        terminal=terminal,
        record=record,
        digest=digest,
        telegram=telegram,
        facebook=facebook,
        instagram=instagram,
    )
```

The implementation must validate exactly one canonical batch ID and portfolio
date, exactly six unique pick IDs, allowed states, decimal odds, and result evidence
for every terminal row. `evening` is eligible when at least one terminal row exists
and the terminal-state digest differs from the last claimed evening digest. `final`
requires six terminal rows. Copy uses the Premium equilibrado voice, lists every
terminal row, states pending count in the evening report, and includes responsible
play language.

- [ ] **Step 4: Run result-report tests and commit**

```powershell
python -m pytest tests/test_result_reporting.py -q
git add backend/result_reporting.py tests/test_result_reporting.py
git commit -m "feat: build verified result reports"
```

---

### Task 6: Add an idempotent result-report ledger and projection

**Files:**
- Create: `supabase/migrations/20260824150000_result_report_delivery.sql`
- Create: `backend/result_report_repository.py`
- Create: `tests/test_result_report_repository.py`
- Modify: `tests/test_supabase_contract.py`

- [ ] **Step 1: Write failing migration and repository contract tests**

Tests must assert:

```python
assert "create table public.result_report_deliveries" in migration
assert "primary key (batch_id, report_kind, destination)" in migration
assert "revoke all on table public.result_report_deliveries from public, anon, authenticated" in migration
assert "grant select, insert, update, delete on table public.result_report_deliveries to service_role" in migration
assert "public.get_result_report_batches" in migration
assert "public.claim_result_report_delivery" in migration
assert "public.complete_result_report_delivery" in migration
```

Repository tests use a fake Supabase client and verify that a successful prior
claim returns `complete`, a failed claim is retryable, and `in_progress` is never
silently retried.

- [ ] **Step 2: Run tests and confirm missing migration/module failures**

```powershell
python -m pytest tests/test_result_report_repository.py tests/test_supabase_contract.py -q
```

Expected: FAIL because neither file exists.

- [ ] **Step 3: Create the service-role-only SQL contract**

The migration creates:

```sql
create table public.result_report_deliveries (
    batch_id uuid not null references public.pick_batches(id),
    portfolio_date date not null,
    report_kind text not null check (report_kind in ('evening', 'final')),
    destination text not null check (destination in ('admin', 'vip', 'free', 'facebook', 'instagram')),
    report_digest text not null check (report_digest ~ '^[0-9a-f]{64}$'),
    state text not null check (state in ('in_progress', 'success', 'failed')),
    attempt_id uuid not null,
    error text not null default '',
    receipt text not null default '',
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    primary key (batch_id, report_kind, destination)
);
```

`get_result_report_batches()` returns portfolios from the current and previous
Mexico City dates with their six persisted picks and result evidence.
`claim_result_report_delivery(...)` inserts `in_progress`, returns `complete` for
an existing success, returns `ambiguous` for active `in_progress`, and replaces an
existing failed attempt only when the caller provides a fresh UUID.
`complete_result_report_delivery(...)` updates only the matching `attempt_id`,
sanitizes the bounded error/receipt, and returns one row.

Revoke all access from public/anon/authenticated; grant table and RPC access only
to service role. Set fixed `search_path = pg_catalog, public` on every security
definer function.

- [ ] **Step 4: Implement the strict Python repository**

Create `backend/result_report_repository.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Mapping
from uuid import UUID, uuid4

from supabase import create_client

DIGEST = re.compile(r"^[0-9a-f]{64}$")
DESTINATIONS = frozenset({"admin", "vip", "free", "facebook", "instagram"})

@dataclass(frozen=True)
class Claim:
    state: Literal["claimed", "complete", "ambiguous"]
    attempt_id: str | None

class SupabaseResultReportRepository:
    def __init__(self, url: str, service_role_key: str) -> None:
        if not url.strip() or not service_role_key.strip():
            raise ValueError("Supabase result report credentials are required")
        self._client = create_client(url, service_role_key)

    def batches(self) -> tuple[tuple[Mapping[str, object], ...], ...]:
        raw = self._client.rpc("get_result_report_batches", {}).execute().data
        if not isinstance(raw, list):
            raise RuntimeError("result report batches returned invalid data")
        batches = []
        for value in raw:
            if not isinstance(value, dict) or set(value) != {"picks"}:
                raise RuntimeError("result report batch returned invalid keys")
            picks = value["picks"]
            if not isinstance(picks, list) or len(picks) != 6:
                raise RuntimeError("result report batch requires six picks")
            if not all(isinstance(row, dict) for row in picks):
                raise RuntimeError("result report pick must be an object")
            batches.append(tuple(dict(row) for row in picks))
        return tuple(batches)

    def claim(self, *, batch_id: str, portfolio_date: str, report_kind: str,
              destination: str, report_digest: str) -> Claim:
        if destination not in DESTINATIONS or report_kind not in {"evening", "final"}:
            raise ValueError("invalid report claim")
        _canonical_uuid(batch_id)
        if DIGEST.fullmatch(report_digest) is None:
            raise ValueError("invalid report digest")
        attempt_id = str(uuid4())
        raw = self._client.rpc("claim_result_report_delivery", {
            "requested_batch_id": batch_id,
            "requested_portfolio_date": portfolio_date,
            "requested_report_kind": report_kind,
            "requested_destination": destination,
            "requested_report_digest": report_digest,
            "requested_attempt_id": attempt_id,
        }).execute().data
        value = _one(raw)
        if set(value) != {"state", "attempt_id"}:
            raise RuntimeError("result report claim returned invalid keys")
        state = value["state"]
        if state not in {"claimed", "complete", "ambiguous"}:
            raise RuntimeError("result report claim returned invalid state")
        returned_attempt = value["attempt_id"]
        if state == "claimed":
            if returned_attempt != attempt_id:
                raise RuntimeError("result report claim returned wrong attempt")
            return Claim("claimed", attempt_id)
        if returned_attempt is not None:
            raise RuntimeError("terminal claim must not expose an attempt")
        return Claim(state, None)

    def complete(self, *, batch_id: str, report_kind: str, destination: str,
                 report_digest: str, attempt_id: str, success: bool,
                 error: str = "", receipt: str = "") -> None:
        _canonical_uuid(batch_id)
        _canonical_uuid(attempt_id)
        if destination not in DESTINATIONS or report_kind not in {"evening", "final"}:
            raise ValueError("invalid report completion")
        if DIGEST.fullmatch(report_digest) is None or type(success) is not bool:
            raise ValueError("invalid report completion")
        raw = self._client.rpc("complete_result_report_delivery", {
            "requested_batch_id": batch_id,
            "requested_report_kind": report_kind,
            "requested_destination": destination,
            "requested_report_digest": report_digest,
            "requested_attempt_id": attempt_id,
            "requested_success": success,
            "requested_error": error[:64],
            "requested_receipt": receipt[:256],
        }).execute().data
        if _one(raw) != {"completed": True}:
            raise RuntimeError("result report completion was not persisted")

def _one(value: object) -> dict[str, object]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        raise RuntimeError("result report RPC returned invalid data")
    return dict(value)

def _canonical_uuid(value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ValueError("value must be a canonical UUID") from None
```

Reject extra/missing RPC keys, malformed UUIDs/digests, invalid destinations, and
unbounded remote strings before returning domain values.

- [ ] **Step 5: Run contract tests, apply migration locally, and commit**

```powershell
python -m pytest tests/test_result_report_repository.py tests/test_supabase_contract.py -q
supabase db reset
python -m pytest tests/test_supabase_contract.py -q
git add supabase/migrations/20260824150000_result_report_delivery.sql backend/result_report_repository.py tests/test_result_report_repository.py tests/test_supabase_contract.py
git commit -m "feat: persist result report deliveries"
```

Expected: tests PASS and local reset installs all migrations.

---

### Task 7: Generate a verified result image and publish reports

**Files:**
- Create: `backend/result_banner.py`
- Create: `tests/test_result_banner.py`
- Modify: `backend/verificar_resultados.py`
- Modify: `tests/test_results_integration.py`
- Modify: `.github/workflows/scraper.yml`
- Modify: `tests/test_scraper_workflow.py`

- [ ] **Step 1: Write failing image and routing tests**

Create a six-row final report fixture and assert `render_result_jpeg(report)`
returns a valid 1080×1080 JPEG containing no network dependency. Add verifier
integration tests that fake the repository/transports and assert:

```python
assert destinations_for("evening") == ("admin", "vip", "free")
assert destinations_for("final") == ("admin", "vip", "free", "facebook", "instagram")
```

Also assert a success claim skips transport, a failed destination does not block
others, and Meta is not called for an evening report.

- [ ] **Step 2: Run focused tests and verify failures**

```powershell
python -m pytest tests/test_result_banner.py tests/test_results_integration.py tests/test_scraper_workflow.py -q
```

Expected: FAIL because the banner and routing do not exist and the workflow has
only two schedules.

- [ ] **Step 3: Implement the deterministic result banner**

Create `backend/result_banner.py` using Pillow already present in the runtime:

```python
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from backend.result_reporting import ResultReport, STATE_ICON

def render_result_jpeg(report: ResultReport) -> bytes:
    """Return one 1080-square navy/gold result card from verified rows only."""
    if report.kind != "final" or not report.terminal or len(report.rows) != 6:
        raise ValueError("result banner requires one terminal six-pick report")
    image = Image.new("RGB", (1080, 1080), "#071021")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    title = ImageFont.load_default(size=54)
    gold = "#f5cf58"
    white = "#f8fafc"
    muted = "#aab6ca"
    draw.rounded_rectangle((32, 32, 1048, 1048), radius=28, outline=gold, width=3)
    draw.text((72, 74), "REY TACO PICKS", fill=gold, font=font)
    draw.text((72, 125), "CIERRE VERIFICADO", fill=white, font=title)
    draw.text((72, 205), f"RÉCORD DE LA JORNADA: {report.record}", fill=gold, font=font)
    y = 285
    for row in report.rows:
        icon = STATE_ICON[str(row["estado"])]
        event = str(row["partido"])[:48]
        selection = str(row["pick"])[:42]
        draw.rounded_rectangle((64, y, 1016, y + 100), radius=14, fill="#101b31")
        draw.text((84, y + 16), f"{icon} {event}", fill=white, font=font)
        draw.text((84, y + 54), f"{selection} @ {float(row['cuota']):.2f}", fill=muted, font=font)
        y += 112
    draw.text((72, 986), "reytacopicks.com · 18+ · Juega responsablemente", fill=gold, font=font)
    output = BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()
```

The card includes logo, `CIERRE VERIFICADO`, record, all six compact rows with
state icons, date, `reytacopicks.com`, and responsible-play footer. It must not use
remote images, random choices, or AI-generated text.

- [ ] **Step 4: Replace the lossy Telegram notifier with ledger-backed publishing**

In `backend/verificar_resultados.py`, remove `_notificar_resultados_telegram` and
call a new `publish_available_result_reports(...)` after database updates. For
each batch returned by `SupabaseResultReportRepository.batches()`:

1. build and attempt `evening` when eligible;
2. build and attempt `final` only when terminal;
3. claim each destination before transport;
4. send Telegram with the existing bounded HTTP transport;
5. for final Meta, upload the deterministic JPEG through the existing social
   artifact repository and call the existing Meta Graph transport with the result
   captions;
6. complete every claim independently.

Do not send any destination whose claim is `complete` or `ambiguous`.

- [ ] **Step 5: Add the two cloud verification windows and scoped secrets**

Set `.github/workflows/scraper.yml` schedules to:

```yaml
  schedule:
    - cron: '0 13 * * *' # 07:00 CDMX
    - cron: '0 19 * * *' # 13:00 CDMX
    - cron: '0 1 * * *'  # 19:00 CDMX
    - cron: '0 5 * * *'  # 23:00 CDMX
```

Add only to the `Verify Results` step:

```yaml
META_SYSTEM_USER_ACCESS_TOKEN: ${{ secrets.META_SYSTEM_USER_ACCESS_TOKEN }}
FB_PAGE_ID: ${{ secrets.FB_PAGE_ID }}
IG_USER_ID: ${{ secrets.IG_USER_ID }}
SUPABASE_STORAGE_BUCKET: ${{ secrets.SUPABASE_STORAGE_BUCKET }}
RESULT_REPORT_MODE: ${{ github.event_name == 'workflow_dispatch' && 'auto' || github.event.schedule == '0 1 * * *' && 'evening' || 'final_only' }}
```

Update `tests/test_scraper_workflow.py` to expect all four cron expressions and
to assert these secrets never reach residential collection jobs. In Python,
`evening` attempts the one allowed vespertino report, `final_only` never emits a
partial report, and `auto` is limited by the same one-row ledger key so a manual
run cannot create a second vespertino report.

- [ ] **Step 6: Run focused and full backend tests, then commit**

```powershell
python -m pytest tests/test_result_banner.py tests/test_results_integration.py tests/test_scraper_workflow.py -q
python -m pytest -q
git add backend/result_banner.py tests/test_result_banner.py backend/verificar_resultados.py tests/test_results_integration.py .github/workflows/scraper.yml tests/test_scraper_workflow.py
git commit -m "feat: publish verified result recaps"
```

Expected: full suite PASS with no network calls in unit tests.

---

### Task 8: Configure production, verify today’s results, and run one real flow

**Files:**
- No source changes expected unless verification reveals a reproducible defect.
- Evidence: GitHub Actions run URLs, Render deploy ID, Meta/Telegram receipts, and
  live web checks recorded in the handoff.

- [ ] **Step 1: Apply the new Supabase migration**

Run the repository migration workflow against master and verify
`result_report_deliveries` plus the three RPCs with the service-role status probe.
Do not print credentials or tokens.

- [ ] **Step 2: Configure Render’s frontend build and redeploy**

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` on the existing Rey Taco web
service, trigger a clean deploy from master, and verify the built JS contains the
Supabase project URL but does not contain the service-role key.

Check:

```powershell
$html = (Invoke-WebRequest 'https://reytacopicks.com/?verify=live' -UseBasicParsing).Content
$asset = [regex]::Match($html, '<script[^>]+src="(?<src>[^"]+\.js)"').Groups['src'].Value
$js = (Invoke-WebRequest ([Uri]::new([Uri]'https://reytacopicks.com/', $asset)) -UseBasicParsing).Content
if ($js -notmatch '\.supabase\.co' -or $js -notmatch 'public_picks') { throw 'Supabase frontend config missing' }
```

Open desktop and mobile views and confirm two active public cards and complete
history.

- [ ] **Step 3: Configure and smoke-test the free Telegram destination**

Ensure `TELEGRAM_FREE_CHANNEL_ID` exists as a GitHub Actions secret and is distinct
from admin/VIP. Run a formatter preview locally with fake IDs, then send one clearly
marked configuration test message to free. Do not resend today’s six picks during
this step.

- [ ] **Step 4: Verify today’s six reported winners from authoritative sources**

Dispatch the result verifier manually. Accept `ganado` only when each row persists
source, event ID, score, and verification timestamp. Any unmatched event remains
`revision_pendiente`; the user-provided outcome alone is not written as verified.

Confirm the evening report shows partial evidence if not all six can be matched.
Confirm the final report and 6–0 graphic are emitted only if all six are terminal
and all six are verified as wins.

- [ ] **Step 5: Run a dry preview of the next scraper portfolio**

On an online residential runner, run the collector in collect-only/dry-preview mode
for the current Mexico date. Inspect candidate count, event start times, public
allocation, lineups, odds freshness, and the exact Telegram/Meta/web payloads.
No external delivery occurs in this step.

- [ ] **Step 6: Execute one real idempotent end-to-end flow**

Dispatch `collector.yml` for a portfolio date that has not already been released.
Verify in order:

1. exactly six persisted picks and exactly two `public`;
2. Telegram admin success;
3. Telegram VIP success with six editorial rows;
4. Telegram free success with two editorial rows and no premium text;
5. Facebook and Instagram success with rich factual captions and the existing
   approved pick image;
6. web shows two active cards without a deploy;
7. rerunning delivery recovery performs zero duplicate sends for successful
   destinations.

- [ ] **Step 7: Run final verification and produce the handoff**

Run:

```powershell
python -m pytest -q
Set-Location frontend
npm test
npm run build
Set-Location ..
git status --short
```

Expected: backend and frontend suites PASS, build succeeds, and only the user’s
pre-existing unrelated files remain dirty. Report exact test counts, production
run IDs, which destinations succeeded, whether all six current results were
authoritatively verified, and any item still requiring external action.
