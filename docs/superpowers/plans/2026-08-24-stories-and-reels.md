# Stories and Reels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish deterministic Rey Taco Instagram stories and Instagram/Facebook reels from the exact persisted pick portfolio, including validated original ticket evidence, without browser automation or paid media APIs.

**Architecture:** A vertical-content domain produces immutable cards from the existing audited `MetaSocialBatch` and `ResultReport` boundaries. Pillow renders 1080×1920 JPEGs, FFmpeg composes reviewed frames into MP4, Supabase atomically claims each content/destination pair and temporarily hosts media, and bounded Meta transports publish Instagram Stories plus Instagram/Facebook Reels. Ticket photographs remain owned by the existing Telegram bot and are recovered by `file_id`, inspected, matched, and attached only when confidence is sufficient.

**Tech Stack:** Python 3.11, Pillow, pytesseract, FFmpeg/FFprobe, requests, Supabase/PostgreSQL RPCs, Meta Graph API v26.0, Telegram Bot API, pytest, GitHub Actions, PowerShell runners.

---

## File map

**Create**

- `backend/vertical_content.py`: immutable story/reel card domain and audited builders.
- `backend/story_renderer.py`: deterministic 1080×1920 JPEG rendering, including uncut ticket evidence.
- `backend/vertical_repository.py`: Supabase claim, completion, temporary media, and ticket-evidence boundary.
- `backend/meta_http.py`: bounded shared Meta HTTP response helpers extracted from the feed publisher.
- `backend/vertical_meta.py`: Instagram Story, Instagram Reel, and Facebook Reel transports.
- `backend/ticket_evidence.py`: Telegram retrieval, OCR privacy inspection, and portfolio matching.
- `backend/reel_renderer.py`: FFmpeg composition and FFprobe validation.
- `backend/vertical_publisher.py`: pre-event and final-result orchestration/CLI.
- `supabase/migrations/20260824180000_vertical_media_delivery.sql`: vertical ledger, storage bucket, ticket metadata, and service-role RPCs.
- `tests/test_vertical_content.py`
- `tests/test_story_renderer.py`
- `tests/test_vertical_repository.py`
- `tests/test_vertical_meta.py`
- `tests/test_ticket_evidence.py`
- `tests/test_reel_renderer.py`
- `tests/test_vertical_publisher.py`
- `tests/test_vertical_workflows.py`

**Modify**

- `backend/social_poster.py`: consume the extracted bounded Meta HTTP helpers without changing feed behavior.
- `backend/ticket_listener.py`: persist admin origin and Telegram `file_unique_id` with saved evidence.
- `backend/verificar_resultados.py`: invoke final vertical publishing after building a final report.
- `.github/workflows/collector.yml`: publish the two pre-event stories after the exact social batch.
- `.github/workflows/scraper.yml`: install media/OCR tools and publish final stories/reels.
- `.github/workflows/delivery-recovery.yml`: recover incomplete vertical destinations without repeating completed ones.
- `scripts/windows/Test-ReyTacoRunnerHost.ps1`: report FFmpeg/Tesseract readiness without opening windows.
- `.env.example` and `backend/.env.example`: document variable names only.
- `README.md`: document dry-run, live validation, and recovery commands.
- `tests/test_social_poster.py`, `tests/test_backend_requirements.py`, `tests/test_result_report_workflow.py`, `tests/test_source_security.py`, `tests/test_supabase_contract.py`, and `tests/test_windows_host_check.py`: regression coverage.

## Task 1: Immutable vertical content packages

**Files:**

- Create: `backend/vertical_content.py`
- Create: `tests/test_vertical_content.py`

- [ ] **Step 1: Write the failing domain tests**

```python
from datetime import datetime, timezone

import pytest

from backend.social_repository import MetaSocialBatch
from backend.vertical_content import (
    build_final_results_story,
    build_public_pick_story,
    build_verified_result_story,
    build_vip_teaser_story,
)
from tests.test_social_poster import batch
from tests.test_result_reporting import rows_with_states
from backend.result_reporting import build_result_report


def test_public_and_teaser_never_cross_premium_details():
    source: MetaSocialBatch = batch()
    public = build_public_pick_story(source, portfolio_date="2026-08-24")
    teaser = build_vip_teaser_story(source, portfolio_date="2026-08-24")
    assert public.kind == "public_pick_story"
    assert len(public.rows) == 1
    assert teaser.kind == "vip_teaser_story"
    assert teaser.rows == ()
    assert "4 selecciones adicionales" in teaser.subtitle
    assert source.content.event not in teaser.subtitle
    assert len(public.digest) == len(teaser.digest) == 64


def test_final_story_contains_all_six_and_verified_card_contains_one():
    report = build_result_report(rows_with_states(*(["ganado"] * 6)), kind="final")
    summary = build_final_results_story(report)
    detail = build_verified_result_story(report, pick_id=int(report.rows[0]["id"]))
    assert len(summary.rows) == 6
    assert len(detail.rows) == 1
    assert summary.kind == "final_results_story"
    assert detail.kind == "verified_result_story"
    assert summary.batch_id == detail.batch_id == report.batch_id


def test_vertical_builders_reject_non_final_or_unknown_pick():
    evening = build_result_report(
        rows_with_states("ganado", "pendiente", "pendiente", "pendiente", "pendiente", "pendiente"),
        kind="evening",
    )
    with pytest.raises(ValueError, match="final"):
        build_final_results_story(evening)
```

- [ ] **Step 2: Run the domain tests and confirm the expected import failure**

Run: `python -m pytest tests/test_vertical_content.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.vertical_content'`.

- [ ] **Step 3: Implement the immutable domain and canonical digest**

```python
"""Immutable, audited packages for vertical social media."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Literal

from backend.result_reporting import ResultReport
from backend.social_repository import MetaSocialBatch

StoryKind = Literal[
    "public_pick_story",
    "vip_teaser_story",
    "final_results_story",
    "verified_result_story",
    "ticket_evidence_story",
    "reel_cta_story",
]


@dataclass(frozen=True, slots=True)
class VerticalRow:
    pick_id: int | None
    event: str
    selection: str
    odds: str
    state: str = ""
    score: str = ""


@dataclass(frozen=True, slots=True)
class VerticalCard:
    kind: StoryKind
    batch_id: str
    portfolio_date: str
    headline: str
    subtitle: str
    rows: tuple[VerticalRow, ...]
    cta: str
    digest: str
    template_version: int = 1


@dataclass(frozen=True, slots=True)
class ReelPackage:
    batch_id: str
    portfolio_date: str
    digest: str
    caption: str
    template_version: int = 1
    kind: Literal["daily_results_reel"] = "daily_results_reel"


def _card(*, kind: StoryKind, batch_id: str, portfolio_date: str,
          headline: str, subtitle: str, rows: tuple[VerticalRow, ...],
          cta: str) -> VerticalCard:
    payload = {
        "kind": kind, "batch_id": batch_id, "portfolio_date": portfolio_date,
        "headline": headline, "subtitle": subtitle, "rows": [asdict(row) for row in rows],
        "cta": cta, "template_version": 1,
    }
    digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")).hexdigest()
    return VerticalCard(kind=kind, batch_id=batch_id, portfolio_date=portfolio_date,
                        headline=headline, subtitle=subtitle, rows=rows, cta=cta,
                        digest=digest)


def build_public_pick_story(batch: MetaSocialBatch, *, portfolio_date: str) -> VerticalCard:
    content = batch.content
    row = VerticalRow(int(content.pick_id), content.event, content.selection, content.odds_text)
    return _card(kind="public_pick_story", batch_id=batch.batch_id,
                 portfolio_date=portfolio_date, headline="PICK PÚBLICO DEL DÍA",
                 subtitle=content.schedule, rows=(row,),
                 cta="Consulta la cartelera · reytacopicks.com")


def build_vip_teaser_story(batch: MetaSocialBatch, *, portfolio_date: str) -> VerticalCard:
    return _card(kind="vip_teaser_story", batch_id=batch.batch_id,
                 portfolio_date=portfolio_date, headline="CARTELERA VIP LISTA",
                 subtitle="6 selecciones analizadas · 4 selecciones adicionales en VIP",
                 rows=(), cta="Acceso VIP · reytacopicks.com")


def build_final_results_story(report: ResultReport) -> VerticalCard:
    if report.kind != "final" or not report.terminal or len(report.rows) != 6:
        raise ValueError("vertical result story requires a final six-pick report")
    rows = tuple(VerticalRow(int(row["id"]), str(row["partido"]), str(row["pick"]),
                             str(row["cuota"]), str(row["estado"]),
                             str(row["resultado_marcador"])) for row in report.rows)
    return _card(kind="final_results_story", batch_id=report.batch_id,
                 portfolio_date=report.portfolio_date, headline="CIERRE VERIFICADO",
                 subtitle=f"Resultados completos · Récord {report.record}", rows=rows,
                 cta="Historial completo · reytacopicks.com")


def build_verified_result_story(report: ResultReport, *, pick_id: int) -> VerticalCard:
    summary = build_final_results_story(report)
    selected = tuple(row for row in summary.rows if row.pick_id == pick_id)
    if len(selected) != 1:
        raise ValueError("verified result story requires one known pick")
    return _card(kind="verified_result_story", batch_id=report.batch_id,
                 portfolio_date=report.portfolio_date, headline="RESULTADO VERIFICADO",
                 subtitle="La corona acertó", rows=selected,
                 cta="Mira los 6 resultados · reytacopicks.com")


def build_ticket_evidence_card(report: ResultReport, *, evidence_id: str,
                               media_digest: str) -> VerticalCard:
    if report.kind != "final" or not report.terminal:
        raise ValueError("ticket evidence requires a final report")
    if not evidence_id or len(media_digest) != 64:
        raise ValueError("ticket evidence identity is invalid")
    return _card(kind="ticket_evidence_story", batch_id=report.batch_id,
                 portfolio_date=report.portfolio_date, headline="EVIDENCIA ORIGINAL",
                 subtitle=f"Ticket {evidence_id} · {media_digest[:12]}", rows=(),
                 cta="Resultados completos · reytacopicks.com")


def build_reel_cta_story(report: ResultReport) -> VerticalCard:
    if report.kind != "final" or not report.terminal:
        raise ValueError("reel CTA requires a final report")
    return _card(kind="reel_cta_story", batch_id=report.batch_id,
                 portfolio_date=report.portfolio_date, headline="¿QUIERES LA PRÓXIMA CARTELERA?",
                 subtitle="Dos picks públicos · seis selecciones en VIP", rows=(),
                 cta="Únete en reytacopicks.com")


def build_daily_reel_package(report: ResultReport) -> ReelPackage:
    summary = build_final_results_story(report)
    caption = (f"👑 Cierre verificado · {summary.subtitle}\n"
               "Consulta los seis resultados en reytacopicks.com\n"
               "18+ · Apuesta con responsabilidad")
    payload = {"batch_id": report.batch_id, "portfolio_date": report.portfolio_date,
               "report_digest": report.digest, "caption": caption, "template_version": 1}
    digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")).hexdigest()
    return ReelPackage(report.batch_id, report.portfolio_date, digest, caption)
```

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_vertical_content.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the domain boundary**

```powershell
git add backend/vertical_content.py tests/test_vertical_content.py
git commit -m "feat: add audited vertical content packages"
```

## Task 2: Deterministic 9:16 story rendering

**Files:**

- Create: `backend/story_renderer.py`
- Create: `tests/test_story_renderer.py`
- Modify: `backend/report_story_9_16.html`

- [ ] **Step 1: Write failing renderer tests**

```python
from io import BytesIO

from PIL import Image

from backend.story_renderer import render_story_jpeg, render_ticket_evidence_jpeg
from backend.vertical_content import build_public_pick_story
from tests.test_social_poster import batch


def decoded(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    image.load()
    return image


def test_story_is_network_free_rgb_1080_by_1920():
    card = build_public_pick_story(batch(), portfolio_date="2026-08-24")
    image = decoded(render_story_jpeg(card))
    assert image.format == "JPEG"
    assert image.mode == "RGB"
    assert image.size == (1080, 1920)


def test_ticket_evidence_uses_contain_without_cropping_source():
    source = Image.new("RGB", (500, 1000), "#ff0000")
    source.putpixel((0, 0), (0, 255, 0))
    raw = BytesIO()
    source.save(raw, "JPEG", quality=100, subsampling=0)
    story = decoded(render_ticket_evidence_jpeg(raw.getvalue(), observed_label="24 AGO · CDMX"))
    assert story.size == (1080, 1920)
    assert story.getbbox() == (0, 0, 1080, 1920)
```

- [ ] **Step 2: Run the renderer tests to confirm failure**

Run: `python -m pytest tests/test_story_renderer.py -q`

Expected: FAIL because `backend.story_renderer` does not exist.

- [ ] **Step 3: Implement the Pillow renderer and retire hard-coded production use**

```python
"""Network-free 1080x1920 story rendering."""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from backend.vertical_content import VerticalCard

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "frontend" / "public" / "logo.jpg"
NAVY, PANEL, GOLD, WHITE, MUTED = "#071021", "#101B31", "#F5CF58", "#F8FAFC", "#AAB6CA"


def _font(size: int, *, bold: bool = False):
    for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                 ("Arial Bold.ttf" if bold else "Arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _jpeg(image: Image.Image) -> bytes:
    output = BytesIO()
    image.convert("RGB").save(output, "JPEG", quality=92, optimize=True, subsampling=0)
    return output.getvalue()


def render_story_jpeg(card: VerticalCard) -> bytes:
    if not isinstance(card, VerticalCard):
        raise ValueError("story renderer requires one VerticalCard")
    image = Image.new("RGB", (1080, 1920), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((30, 30, 1050, 1890), radius=34, outline=GOLD, width=4)
    draw.text((80, 100), "REY TACO PICKS", fill=GOLD, font=_font(34, bold=True))
    draw.text((80, 190), card.headline, fill=WHITE, font=_font(66, bold=True))
    draw.text((80, 285), card.subtitle, fill=MUTED, font=_font(31))
    y = 410
    for row in card.rows:
        draw.rounded_rectangle((70, y, 1010, y + 190), radius=22, fill=PANEL)
        draw.text((105, y + 30), row.event[:54], fill=WHITE, font=_font(32, bold=True))
        draw.text((105, y + 88), row.selection[:62], fill=GOLD, font=_font(29, bold=True))
        detail = " · ".join(value for value in (row.odds, row.state.upper(), row.score) if value)
        draw.text((105, y + 140), detail, fill=MUTED, font=_font(24))
        y += 215
    draw.text((70, 1790), card.cta, fill=GOLD, font=_font(27, bold=True))
    draw.text((70, 1840), "18+ · Apuesta con responsabilidad", fill=MUTED, font=_font(23))
    return _jpeg(image)


def render_ticket_evidence_jpeg(ticket_jpeg: bytes, *, observed_label: str) -> bytes:
    with Image.open(BytesIO(ticket_jpeg)) as opened:
        source = opened.convert("RGB")
    background = ImageOps.fit(source, (1080, 1920), method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    background = Image.blend(background, Image.new("RGB", background.size, NAVY), 0.58)
    contained = ImageOps.contain(source, (960, 1580), method=Image.Resampling.LANCZOS)
    x, y = (1080 - contained.width) // 2, 170 + (1580 - contained.height) // 2
    background.paste(contained, (x, y))
    draw = ImageDraw.Draw(background)
    draw.text((60, 65), "EVIDENCIA ORIGINAL", fill=GOLD, font=_font(38, bold=True))
    draw.text((60, 1760), observed_label, fill=WHITE, font=_font(25))
    draw.text((60, 1815), "reytacopicks.com · 18+", fill=GOLD, font=_font(25, bold=True))
    return _jpeg(background)
```

Replace `backend/report_story_9_16.html` with a short archived notice that states it is not a production renderer and contains no hard-coded results or remote font imports.

- [ ] **Step 4: Run renderer and existing banner regressions**

Run: `python -m pytest tests/test_story_renderer.py tests/test_result_banner.py tests/test_social_banner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the renderer**

```powershell
git add backend/story_renderer.py backend/report_story_9_16.html tests/test_story_renderer.py
git commit -m "feat: render deterministic vertical stories"
```

## Task 3: Atomic Supabase ledger and temporary vertical storage

**Files:**

- Create: `supabase/migrations/20260824180000_vertical_media_delivery.sql`
- Create: `backend/vertical_repository.py`
- Create: `tests/test_vertical_repository.py`
- Modify: `tests/test_supabase_contract.py`

- [ ] **Step 1: Write failing repository and SQL-contract tests**

```python
from datetime import datetime, timedelta, timezone

from backend.vertical_repository import SupabaseVerticalRepository, VerticalClaim


def test_claim_uses_exact_content_destination_digest_and_attempt(fake_supabase):
    repo = SupabaseVerticalRepository(
        url="https://project.supabase.co", service_role_key="service-secret",
        client_factory=lambda *_: fake_supabase,
    )
    claim = repo.claim(batch_id="22222222-2222-4222-8222-222222222222",
                       portfolio_date="2026-08-24", content_kind="public_pick_story",
                       destination="instagram_story", digest="a" * 64,
                       template_version=1)
    assert claim.state in {"claimed", "complete", "ambiguous"}
    assert fake_supabase.rpc_calls[0][0] == "claim_vertical_media_delivery"


def test_vertical_migration_is_service_role_only_and_has_exact_destinations():
    sql = open("supabase/migrations/20260824180000_vertical_media_delivery.sql", encoding="utf-8").read()
    assert "instagram_story" in sql and "instagram_reel" in sql and "facebook_reel" in sql
    assert "revoke all" in sql.casefold()
    assert "service_role" in sql
```

- [ ] **Step 2: Run the tests and confirm missing repository/migration failure**

Run: `python -m pytest tests/test_vertical_repository.py tests/test_supabase_contract.py -q`

Expected: FAIL because the new repository and migration do not exist.

- [ ] **Step 3: Add the migration with an exact claim/complete contract**

```sql
begin;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('social-vertical', 'social-vertical', true, 52428800,
        array['image/jpeg','video/mp4'])
on conflict (id) do update set file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create table if not exists public.vertical_media_deliveries (
  id bigint generated by default as identity primary key,
  batch_id uuid not null,
  portfolio_date date not null,
  content_kind text not null check (content_kind in (
    'public_pick_story','vip_teaser_story','final_results_story',
    'verified_result_story','ticket_evidence_story','reel_cta_story','daily_results_reel')),
  destination text not null check (destination in (
    'instagram_story','instagram_reel','facebook_reel')),
  content_digest text not null check (content_digest ~ '^[0-9a-f]{64}$'),
  template_version integer not null check (template_version > 0),
  state text not null default 'pending' check (state in (
    'pending','claimed','complete','failed','pending_review')),
  attempt_id uuid,
  lease_expires_at timestamptz,
  receipt text not null default '',
  error text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (batch_id, content_kind, destination, content_digest, template_version)
);

create unique index if not exists vertical_one_reel_per_day_destination
  on public.vertical_media_deliveries(portfolio_date, destination)
  where content_kind='daily_results_reel';

alter table public.vertical_media_deliveries enable row level security;
revoke all on public.vertical_media_deliveries from anon, authenticated;

create or replace function public.claim_vertical_media_delivery(
  requested_batch_id uuid, requested_portfolio_date date,
  requested_content_kind text, requested_destination text,
  requested_content_digest text, requested_template_version integer,
  requested_attempt_id uuid, requested_lease_expires_at timestamptz
) returns table(state text, attempt_id uuid)
language plpgsql security definer set search_path=public,pg_temp as $$
declare selected public.vertical_media_deliveries%rowtype;
begin
  insert into public.vertical_media_deliveries(
    batch_id,portfolio_date,content_kind,destination,content_digest,template_version)
  values(requested_batch_id,requested_portfolio_date,requested_content_kind,
         requested_destination,requested_content_digest,requested_template_version)
  on conflict do nothing;
  if requested_content_kind='daily_results_reel' then
    select * into selected from public.vertical_media_deliveries
     where portfolio_date=requested_portfolio_date
       and content_kind='daily_results_reel'
       and destination=requested_destination for update;
  else
    select * into selected from public.vertical_media_deliveries
     where batch_id=requested_batch_id and content_kind=requested_content_kind
       and destination=requested_destination and content_digest=requested_content_digest
       and template_version=requested_template_version for update;
  end if;
  if selected.state='complete' then return query select 'complete', null::uuid; return; end if;
  if selected.state='claimed' and selected.lease_expires_at > now() then
    return query select 'ambiguous', null::uuid; return;
  end if;
  if requested_content_kind='daily_results_reel' then
    update public.vertical_media_deliveries set batch_id=requested_batch_id,
      content_digest=requested_content_digest, template_version=requested_template_version
      where id=selected.id;
  end if;
  update public.vertical_media_deliveries set state='claimed',
    attempt_id=requested_attempt_id, lease_expires_at=requested_lease_expires_at,
    updated_at=now(), error='' where id=selected.id;
  return query select 'claimed', requested_attempt_id;
end $$;

create or replace function public.complete_vertical_media_delivery(
  requested_batch_id uuid, requested_content_kind text,
  requested_destination text, requested_content_digest text,
  requested_template_version integer, requested_attempt_id uuid,
  requested_success boolean, requested_receipt text, requested_error text
) returns table(completed boolean)
language plpgsql security definer set search_path=public,pg_temp as $$
begin
  update public.vertical_media_deliveries set
    state=case when requested_success then 'complete' else 'failed' end,
    receipt=case when requested_success then requested_receipt else '' end,
    error=case when requested_success then '' else requested_error end,
    attempt_id=null, lease_expires_at=null, updated_at=now()
  where batch_id=requested_batch_id and content_kind=requested_content_kind
    and destination=requested_destination and content_digest=requested_content_digest
    and template_version=requested_template_version and state='claimed'
    and attempt_id=requested_attempt_id;
  return query select found;
end $$;

revoke all on function public.claim_vertical_media_delivery(uuid,date,text,text,text,integer,uuid,timestamptz) from public,anon,authenticated;
grant execute on function public.claim_vertical_media_delivery(uuid,date,text,text,text,integer,uuid,timestamptz) to service_role;
revoke all on function public.complete_vertical_media_delivery(uuid,text,text,text,integer,uuid,boolean,text,text) from public,anon,authenticated;
grant execute on function public.complete_vertical_media_delivery(uuid,text,text,text,integer,uuid,boolean,text,text) to service_role;

commit;
```

- [ ] **Step 4: Implement the strict Python repository**

```python
@dataclass(frozen=True, slots=True)
class VerticalClaim:
    state: Literal["claimed", "complete", "ambiguous"]
    attempt_id: str | None


class SupabaseVerticalRepository:
    BUCKET = "social-vertical"

    def claim(self, *, batch_id: str, portfolio_date: str, content_kind: str,
              destination: str, digest: str, template_version: int) -> VerticalClaim:
        attempt_id = str(uuid4())
        lease = datetime.now(timezone.utc) + timedelta(minutes=8)
        raw = self._client.rpc("claim_vertical_media_delivery", {
            "requested_batch_id": batch_id,
            "requested_portfolio_date": portfolio_date,
            "requested_content_kind": content_kind,
            "requested_destination": destination,
            "requested_content_digest": digest,
            "requested_template_version": template_version,
            "requested_attempt_id": attempt_id,
            "requested_lease_expires_at": lease.isoformat(),
        }).execute().data
        value = _one_exact(raw, {"state", "attempt_id"})
        if value == {"state": "claimed", "attempt_id": attempt_id}:
            return VerticalClaim("claimed", attempt_id)
        if value["state"] in {"complete", "ambiguous"} and value["attempt_id"] is None:
            return VerticalClaim(value["state"], None)
        raise RuntimeError("vertical claim returned invalid data")

    def complete(self, *, package: VerticalCard | ReelPackage, destination: str, attempt_id: str,
                 success: bool, receipt: str = "", error: str = "") -> None:
        arguments = _validated_completion(package, destination, attempt_id, success, receipt, error)
        value = self._client.rpc("complete_vertical_media_delivery", arguments).execute().data
        if _one_exact(value, {"completed"}) != {"completed": True}:
            raise RuntimeError("vertical completion was not persisted")


def _validated_completion(package: VerticalCard | ReelPackage, destination: str,
                          attempt_id: str, success: bool, receipt: str,
                          error: str) -> dict[str, object]:
    if destination not in {"instagram_story", "instagram_reel", "facebook_reel"}:
        raise ValueError("vertical destination is invalid")
    if str(UUID(attempt_id)) != attempt_id or type(success) is not bool:
        raise ValueError("vertical completion identity is invalid")
    if success:
        if error or re.fullmatch(r"[A-Za-z0-9_:-]{1,256}", receipt) is None:
            raise ValueError("vertical success requires one safe receipt")
    elif receipt or error not in {"not_configured", "token_invalid", "delivery_failed", "media_invalid"}:
        raise ValueError("vertical failure requires one allowed error")
    return {
        "requested_batch_id": package.batch_id,
        "requested_content_kind": package.kind,
        "requested_destination": destination,
        "requested_content_digest": package.digest,
        "requested_template_version": package.template_version,
        "requested_attempt_id": attempt_id,
        "requested_success": success,
        "requested_receipt": receipt if success else "",
        "requested_error": "" if success else error,
    }


def _one_exact(value: object, keys: set[str]) -> dict[str, object]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict) or set(value) != keys:
        raise RuntimeError("vertical RPC returned invalid data")
    return dict(value)
```

The constructor must reuse the service-role JWT validation from
`social_repository.py`; `claim` must additionally validate canonical UUID/date,
the 64-character lowercase digest, content/destination allowlists, and a positive
template version before calling Supabase. Catch SDK exceptions and raise only
`vertical claim failed` or `vertical completion failed`.

- [ ] **Step 5: Run repository and contract tests, then commit**

Run: `python -m pytest tests/test_vertical_repository.py tests/test_supabase_contract.py -q`

Expected: PASS.

```powershell
git add supabase/migrations/20260824180000_vertical_media_delivery.sql backend/vertical_repository.py tests/test_vertical_repository.py tests/test_supabase_contract.py
git commit -m "feat: add vertical media delivery ledger"
```

## Task 4: Temporary media lifecycle

**Files:**

- Modify: `backend/vertical_repository.py`
- Modify: `tests/test_vertical_repository.py`

- [ ] **Step 1: Write failing upload/delete tests**

```python
def test_upload_story_uses_digest_key_and_exact_public_url(repository, fake_bucket, card, story_jpeg):
    asset = repository.upload_story(card=card, jpeg=story_jpeg)
    assert asset.object_key == f"stories/2026-08-24/{card.kind}-{card.digest}.jpg"
    assert asset.url.endswith(asset.object_key)
    assert fake_bucket.upload_calls[0]["file_options"]["content-type"] == "image/jpeg"


def test_delete_requires_the_same_bucket_and_exact_object_key(repository, fake_bucket, asset):
    repository.delete_temporary(asset)
    assert fake_bucket.remove_calls == [[asset.object_key]]
```

- [ ] **Step 2: Run the tests and confirm missing methods**

Run: `python -m pytest tests/test_vertical_repository.py -q`

Expected: FAIL with missing `upload_story` and `delete_temporary`.

- [ ] **Step 3: Implement exact media validation and cleanup**

```python
@dataclass(frozen=True, slots=True)
class TemporaryAsset:
    object_key: str
    url: str
    mime_type: Literal["image/jpeg", "video/mp4"]


def upload_story(self, *, card: VerticalCard, jpeg: bytes) -> TemporaryAsset:
    _validate_story_jpeg(jpeg)
    object_key = f"stories/{card.portfolio_date}/{card.kind}-{card.digest}.jpg"
    bucket = self._client.storage.from_(self.BUCKET)
    response = bucket.upload(path=object_key, file=jpeg,
        file_options={"content-type": "image/jpeg", "upsert": "true"})
    _validate_upload_response(response, bucket=self.BUCKET, object_key=object_key)
    url = _validated_public_url(bucket.get_public_url(object_key),
        supabase_url=self._url, bucket=self.BUCKET, object_key=object_key)
    return TemporaryAsset(object_key, url, "image/jpeg")


def delete_temporary(self, asset: TemporaryAsset) -> None:
    if not isinstance(asset, TemporaryAsset) or not asset.object_key.startswith(("stories/", "reels/", "evidence/")):
        raise ValueError("temporary asset key is invalid")
    try:
        result = self._client.storage.from_(self.BUCKET).remove([asset.object_key])
    except Exception:
        raise RuntimeError("temporary asset cleanup failed") from None
    _validate_remove_response(result, asset.object_key)
```

Add `_validate_story_jpeg` for immutable JPEG bytes, RGB mode, exact 1080×1920 dimensions and a 5 MiB cap. Add `upload_reel` in Task 8 with MP4-specific validation rather than accepting arbitrary bytes here.

- [ ] **Step 4: Run the storage tests**

Run: `python -m pytest tests/test_vertical_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the lifecycle**

```powershell
git add backend/vertical_repository.py tests/test_vertical_repository.py
git commit -m "feat: manage temporary vertical media"
```

## Task 5: Shared bounded Meta HTTP and Instagram Stories transport

**Files:**

- Create: `backend/meta_http.py`
- Create: `backend/vertical_meta.py`
- Create: `tests/test_vertical_meta.py`
- Modify: `backend/social_poster.py`
- Modify: `tests/test_social_poster.py`

- [ ] **Step 1: Write failing extraction and Story transport tests**

```python
def test_instagram_story_creates_polls_and_publishes(fake_session, meta_settings):
    fake_session.queue(
        (200, {"id": "story_container_1"}),
        (200, {"status_code": "FINISHED"}),
        (200, {"id": "story_media_1"}),
    )
    delivery = VerticalMetaHttpTransport(session=fake_session, sleep=lambda _: None).publish_instagram_story(
        image_url="https://project.supabase.co/storage/v1/object/public/social-vertical/stories/2026-08-24/a.jpg",
        settings=meta_settings,
    )
    assert delivery.status == "success"
    assert delivery.receipt == "story_media_1"
    assert fake_session.calls[0]["data"]["media_type"] == "STORIES"
    assert "caption" not in fake_session.calls[0]["data"]


def test_story_rejects_non_supabase_or_non_https_url_before_http(fake_session, meta_settings):
    delivery = VerticalMetaHttpTransport(session=fake_session).publish_instagram_story(
        image_url="http://attacker.example/story.jpg", settings=meta_settings)
    assert delivery.status == "media_invalid"
    assert fake_session.calls == []
```

- [ ] **Step 2: Run Meta tests and confirm failure**

Run: `python -m pytest tests/test_vertical_meta.py tests/test_social_poster.py -q`

Expected: FAIL because the shared helpers and vertical transport do not exist.

- [ ] **Step 3: Extract bounded response helpers without changing feed behavior**

Move the existing bounded stream parser, token-error recognition, safe-ID parser,
authorization header, and graph URL validation from `backend/social_poster.py` into
`backend/meta_http.py` with these public names:

```python
from collections.abc import Iterable, Mapping
import json
import re
from typing import Protocol

MAX_META_RESPONSE_BYTES = 256 * 1024

class MetaSettingsLike(Protocol):
    graph_version: str


class MetaResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]
    def iter_content(self, chunk_size: int) -> Iterable[bytes]:
        raise NotImplementedError
    def close(self) -> None:
        raise NotImplementedError


def read_meta_json(response: MetaResponse) -> tuple[int, object]:
    try:
        if type(response.status_code) is not int or not isinstance(response.headers, Mapping):
            raise ValueError("invalid Meta response")
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isascii() or not declared.isdecimal()
                                     or int(declared) > MAX_META_RESPONSE_BYTES):
            raise ValueError("invalid Meta response")
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            if not isinstance(chunk, bytes) or len(body) + len(chunk) > MAX_META_RESPONSE_BYTES:
                raise ValueError("invalid Meta response")
            body.extend(chunk)
        return response.status_code, json.loads(bytes(body).decode("utf-8"))
    finally:
        response.close()


def safe_meta_id(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("id")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_:-]{1,200}", value) else None


def meta_token_invalid(payload: object) -> bool:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("error"), Mapping):
        return False
    error = payload["error"]
    return error.get("code") == 190


def meta_auth_headers(token: str) -> dict[str, str]:
    if not token or token != token.strip() or any(ord(char) < 32 for char in token):
        raise ValueError("Meta token is unsafe")
    return {"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"}


def meta_graph_url(settings: MetaSettingsLike, path: str) -> str:
    if not re.fullmatch(r"v[0-9]+[.][0-9]+", settings.graph_version):
        raise ValueError("Meta graph version is invalid")
    if not path or path.startswith("/") or ".." in path or any(ord(char) < 32 for char in path):
        raise ValueError("Meta graph path is invalid")
    return f"https://graph.facebook.com/{settings.graph_version}/{path}"
```

Update `social_poster.py` to import these functions. Do not change method order,
timeouts, retry counts, log fields, or feed endpoint payloads.

- [ ] **Step 4: Implement Instagram Story publication**

```python
from collections.abc import Mapping
from dataclasses import dataclass
import re
import time
from typing import Literal
from urllib.parse import urlsplit

import requests

from backend.meta_http import (meta_auth_headers, meta_graph_url, meta_token_invalid,
                               read_meta_json, safe_meta_id)
from backend.social_poster import MetaSettings


VerticalStatus = Literal["success", "complete", "not_configured", "token_invalid",
                         "delivery_failed", "media_invalid"]

@dataclass(frozen=True, slots=True)
class VerticalDelivery:
    destination: Literal["instagram_story", "instagram_reel", "facebook_reel"]
    status: VerticalStatus
    receipt: str = ""


class VerticalMetaHttpTransport:
    def __init__(self, *, session=None, sleep=time.sleep, poll_interval: float = 2.0):
        if poll_interval <= 0 or poll_interval > 60:
            raise ValueError("poll interval is invalid")
        self._session = session or requests.Session()
        self._sleep = sleep
        self._poll_interval = poll_interval

    def _post(self, url: str, settings: MetaSettings, data: dict[str, str]) -> tuple[int, object]:
        response = self._session.post(url, headers=meta_auth_headers(settings.token),
                                      data=data, timeout=30, stream=True)
        return read_meta_json(response)

    def _wait_for_container(self, container_id: str, *, settings: MetaSettings,
                            destination: str) -> VerticalDelivery | None:
        for index in range(5):
            response = self._session.get(
                meta_graph_url(settings, f"{container_id}?fields=status_code"),
                headers=meta_auth_headers(settings.token), timeout=30, stream=True)
            status, payload = read_meta_json(response)
            failure = _meta_failure(destination, status, payload)
            if failure is not None:
                return failure
            media_status = payload.get("status_code") if isinstance(payload, Mapping) else None
            if media_status == "FINISHED":
                return None
            if media_status != "IN_PROGRESS" or index == 4:
                return VerticalDelivery(destination, "delivery_failed")
            self._sleep(self._poll_interval)
        return VerticalDelivery(destination, "delivery_failed")

    def publish_instagram_story(self, *, image_url: str, settings: MetaSettings) -> VerticalDelivery:
        if not settings.token or not settings.instagram_user_id:
            return VerticalDelivery("instagram_story", "not_configured")
        if not _validated_vertical_url(image_url, suffix=".jpg"):
            return VerticalDelivery("instagram_story", "media_invalid")
        created = self._post(meta_graph_url(settings, f"{settings.instagram_user_id}/media"),
            settings, {"image_url": image_url, "media_type": "STORIES"})
        container = _required_id(created, destination="instagram_story")
        if isinstance(container, VerticalDelivery):
            return container
        status = self._wait_for_container(container, settings=settings,
                                          destination="instagram_story")
        if status is not None:
            return status
        published = self._post(meta_graph_url(settings, f"{settings.instagram_user_id}/media_publish"),
            settings, {"creation_id": container})
        receipt = _required_id(published, destination="instagram_story")
        return receipt if isinstance(receipt, VerticalDelivery) else VerticalDelivery(
            "instagram_story", "success", receipt)


def _required_id(response: tuple[int, object], *, destination: str) -> str | VerticalDelivery:
    status, payload = response
    failure = _meta_failure(destination, status, payload)
    if failure is not None:
        return failure
    receipt = safe_meta_id(payload)
    return receipt if receipt is not None else VerticalDelivery(destination, "delivery_failed")


def _meta_failure(destination: str, status: int, payload: object) -> VerticalDelivery | None:
    if meta_token_invalid(payload):
        return VerticalDelivery(destination, "token_invalid")
    if status < 200 or status >= 300:
        return VerticalDelivery(destination, "delivery_failed")
    return None


def _validated_vertical_url(value: object, *, suffix: str) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and isinstance(parsed.hostname, str)
        and parsed.hostname.endswith(".supabase.co")
        and parsed.path.startswith("/storage/v1/object/public/social-vertical/")
        and parsed.path.endswith(suffix)
        and not parsed.query and not parsed.fragment
        and parsed.username is None and parsed.password is None
    )
```

Keep five bounded polls, a maximum 60-second poll interval, streamed/bounded JSON,
safe status classes, bearer headers, no token-bearing URLs, and no raw response logs.

- [ ] **Step 5: Run feed and Story Meta tests, then commit**

Run: `python -m pytest tests/test_vertical_meta.py tests/test_social_poster.py -q`

Expected: PASS with the existing feed test count unchanged.

```powershell
git add backend/meta_http.py backend/vertical_meta.py backend/social_poster.py tests/test_vertical_meta.py tests/test_social_poster.py
git commit -m "feat: publish Instagram stories safely"
```

## Task 6: Pre-event story orchestration and collector integration

**Files:**

- Create: `backend/vertical_publisher.py`
- Create: `tests/test_vertical_publisher.py`
- Modify: `.github/workflows/collector.yml`
- Create: `tests/test_vertical_workflows.py`

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_pre_event_publishes_public_then_teaser_and_records_each(fake_story_repository,
                                                                 fake_meta, fake_feed_batch):
    result = publish_pre_event_stories(
        batch=fake_feed_batch, portfolio_date="2026-08-24",
        repository=fake_story_repository, transport=fake_meta,
        settings=configured_settings(), renderer=lambda card: story_jpeg(card),
    )
    assert result == {"public_pick_story": "success", "vip_teaser_story": "success"}
    assert [call.kind for call in fake_story_repository.claim_calls] == [
        "public_pick_story", "vip_teaser_story"]
    assert [call.destination for call in fake_meta.calls] == [
        "instagram_story", "instagram_story"]


def test_completed_public_story_is_not_rendered_uploaded_or_sent(fake_story_repository,
                                                                  fake_meta, fake_feed_batch,
                                                                  story_renderer, settings):
    fake_story_repository.states["public_pick_story"] = "complete"
    result = publish_pre_event_stories(
        batch=fake_feed_batch, portfolio_date="2026-08-24",
        repository=fake_story_repository, transport=fake_meta,
        settings=settings, renderer=story_renderer,
    )
    assert result["public_pick_story"] == "complete"
    assert fake_story_repository.uploaded_kinds == ["vip_teaser_story"]


def test_incomplete_story_alert_contains_only_safe_kind_and_status(fake_telegram):
    notify_vertical_failures({"public_pick_story": "delivery_failed"},
                             telegram=fake_telegram, admin_chat_id="123")
    assert fake_telegram.messages == [
        "⚠️ Rey Taco · contenido vertical incompleto\n• public_pick_story: delivery_failed"]
```

- [ ] **Step 2: Run the publisher tests and confirm failure**

Run: `python -m pytest tests/test_vertical_publisher.py tests/test_vertical_workflows.py -q`

Expected: FAIL because `vertical_publisher.py` and the workflow step do not exist.

- [ ] **Step 3: Implement claim-render-upload-publish-complete-cleanup**

```python
from collections.abc import Callable, Mapping
import logging
from typing import Protocol

from backend.social_poster import MetaSettings
from backend.telegram_publisher import TelegramDestination
from backend.vertical_content import VerticalCard
from backend.vertical_meta import VerticalDelivery
from backend.vertical_repository import TemporaryAsset, VerticalClaim

LOGGER = logging.getLogger(__name__)


class VerticalRepository(Protocol):
    def claim(self, **kwargs: object) -> VerticalClaim:
        raise NotImplementedError
    def upload_story(self, *, card: VerticalCard, jpeg: bytes) -> TemporaryAsset:
        raise NotImplementedError
    def complete(self, **kwargs: object) -> None:
        raise NotImplementedError
    def delete_temporary(self, asset: TemporaryAsset) -> None:
        raise NotImplementedError


class VerticalTransport(Protocol):
    def publish_instagram_story(self, *, image_url: str,
                                settings: MetaSettings) -> VerticalDelivery:
        raise NotImplementedError


def _publish_story(card: VerticalCard, *, repository: VerticalRepository,
                   transport: VerticalTransport, settings: MetaSettings,
                   renderer: Callable[[VerticalCard], bytes]) -> str:
    claim = repository.claim(batch_id=card.batch_id, portfolio_date=card.portfolio_date,
        content_kind=card.kind, destination="instagram_story", digest=card.digest,
        template_version=card.template_version)
    if claim.state != "claimed":
        return claim.state
    assert claim.attempt_id is not None
    asset = None
    try:
        jpeg = renderer(card)
        asset = repository.upload_story(card=card, jpeg=jpeg)
        delivery = transport.publish_instagram_story(image_url=asset.url, settings=settings)
        success = delivery.status == "success"
        repository.complete(package=card, destination="instagram_story",
            attempt_id=claim.attempt_id, success=success,
            receipt=delivery.receipt if success else "",
            error="" if success else delivery.status)
        return delivery.status
    except Exception:
        repository.complete(package=card, destination="instagram_story",
            attempt_id=claim.attempt_id, success=False, error="delivery_failed")
        return "delivery_failed"
    finally:
        if asset is not None:
            try:
                repository.delete_temporary(asset)
            except RuntimeError:
                LOGGER.warning("vertical cleanup status=failed kind=%s", card.kind)


def publish_pre_event_stories(*, batch: MetaSocialBatch, portfolio_date: str, **deps) -> dict[str, str]:
    cards = (
        build_public_pick_story(batch, portfolio_date=portfolio_date),
        build_vip_teaser_story(batch, portfolio_date=portfolio_date),
    )
    return {card.kind: _publish_story(card, **deps) for card in cards}


def notify_vertical_failures(outcomes: Mapping[str, str], *, telegram, admin_chat_id: str) -> None:
    failures = [(name, status) for name, status in sorted(outcomes.items())
                if status not in {"success", "complete"}]
    if not failures or telegram is None or not admin_chat_id:
        return
    lines = ["⚠️ Rey Taco · contenido vertical incompleto"]
    lines.extend(f"• {name}: {status}" for name, status in failures)
    telegram(TelegramDestination("admin", admin_chat_id, "all"), "\n".join(lines))
```

The CLI `python -m backend.vertical_publisher --mode pre-event` loads the same exact
run key and `MetaSocialBatch` as `social_poster`, requires `DAILY_PORTFOLIO_DATE`,
supports `META_DRY_RUN`, prints only safe status summaries, and exits nonzero for a
configured incomplete story. It calls `notify_vertical_failures` with the existing
Telegram transport after all story attempts; alert failure is logged safely and
does not erase a Meta receipt.

- [ ] **Step 4: Add the collector step after feed publishing**

```yaml
      - name: Publish exact pre-event stories
        if: success() && steps.cloud_window.outputs.eligible == 'true'
        env:
          DAILY_PORTFOLIO_DATE: ${{ steps.cloud_window.outputs.portfolio_date }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          META_SYSTEM_USER_ACCESS_TOKEN: ${{ secrets.META_SYSTEM_USER_ACCESS_TOKEN }}
          IG_USER_ID: ${{ secrets.IG_USER_ID }}
          META_GRAPH_VERSION: v26.0
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m backend.vertical_publisher --mode pre-event
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_vertical_publisher.py tests/test_vertical_workflows.py tests/test_scraper_workflow.py -q`

Expected: PASS.

```powershell
git add backend/vertical_publisher.py tests/test_vertical_publisher.py tests/test_vertical_workflows.py .github/workflows/collector.yml
git commit -m "feat: orchestrate pre-event stories"
```

## Task 7: Original ticket evidence retrieval, privacy, and matching

**Files:**

- Create: `backend/ticket_evidence.py`
- Create: `tests/test_ticket_evidence.py`
- Modify: `backend/ticket_listener.py`
- Modify: `backend/vertical_repository.py`
- Modify: `tests/test_vertical_repository.py`
- Modify: `supabase/migrations/20260824180000_vertical_media_delivery.sql`
- Modify: `tests/test_supabase_contract.py`

- [ ] **Step 1: Write failing admin-origin, retrieval, privacy, and match tests**

```python
def test_listener_persists_admin_origin_and_unique_file_id(monkeypatch, admin_photo_update):
    ticket_listener.procesar_foto(admin_photo_update)
    inserted = fake_supabase.table_calls[0].inserted
    assert inserted["telegram_chat_id"] == ticket_listener.ADMIN_CHAT_ID
    assert inserted["file_unique_id"] == "unique-photo-1"


def test_fetcher_uses_get_file_then_exact_telegram_file_host(fake_telegram_session):
    data = TelegramTicketFetcher("bot-secret", session=fake_telegram_session).fetch("file-1")
    assert data.startswith(b"\xff\xd8")
    assert all("bot-secret" not in repr(call) for call in fake_telegram_session.safe_log)


def test_privacy_terms_force_pending_review(ticket_jpeg, final_report):
    result = EvidenceInspector(ocr=lambda _: "Saldo 1200 Carlos 5551234567").inspect(
        ticket_jpeg, report=final_report)
    assert result.state == "pending_review"


def test_exact_team_and_score_match_preserves_full_ticket_id(ticket_jpeg, final_report):
    text = "Aryans Sports 5-0 Nbp Rainbow AC ID: 5329224423"
    result = EvidenceInspector(ocr=lambda _: text).inspect(ticket_jpeg, report=final_report)
    assert result.state == "matched"
    assert result.ticket_id == "5329224423"
    assert result.pick_ids == (int(final_report.rows[0]["id"]),)
```

- [ ] **Step 2: Run evidence tests and confirm failure**

Run: `python -m pytest tests/test_ticket_evidence.py -q`

Expected: FAIL because `ticket_evidence.py` and the extra stored fields do not exist.

- [ ] **Step 3: Extend ticket persistence without changing forwarding behavior**

Add `telegram_chat_id`, `file_unique_id`, and `received_at` columns in the migration.
Update only the existing insert payload:

```sql
alter table if exists public.tickets_ganadores
  add column if not exists telegram_chat_id bigint,
  add column if not exists file_unique_id text,
  add column if not exists received_at timestamptz not null default now();

create table if not exists public.ticket_evidence_reviews (
  evidence_key text primary key,
  batch_id uuid not null,
  portfolio_date date not null,
  state text not null check (state in ('matched','pending_review')),
  ticket_id text not null default '',
  pick_ids bigint[] not null default '{}',
  media_digest text not null check (media_digest ~ '^[0-9a-f]{64}$'),
  ocr_digest text not null check (ocr_digest ~ '^[0-9a-f]{64}$'),
  reviewed_at timestamptz not null default now()
);
alter table public.ticket_evidence_reviews enable row level security;
revoke all on public.ticket_evidence_reviews from anon, authenticated;
```

Update only the existing insert payload:

```python
supabase.table("tickets_ganadores").insert({
    "archivo": filename,
    "caption": caption or "Ticket Ganador",
    "file_id": file_id,
    "file_unique_id": best_photo.get("file_unique_id", ""),
    "telegram_chat_id": chat_id,
    "received_at": datetime.now(timezone.utc).isoformat(),
}).execute()
```

Keep download, manifest update, channel forwarding, and admin response in their
current order.

- [ ] **Step 4: Implement the fail-closed evidence boundary**

```python
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import logging
import re
from typing import Callable, Literal
import unicodedata

import requests
from PIL import Image
import pytesseract

from backend.result_reporting import ResultReport

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    state: Literal["matched", "pending_review"]
    ticket_id: str
    pick_ids: tuple[int, ...]
    ocr_digest: str


@dataclass(frozen=True, slots=True)
class MatchedEvidence:
    evidence_id: str
    ticket_id: str
    media_digest: str
    pick_ids: tuple[int, ...]
    jpeg: bytes


class TelegramTicketFetcher:
    def __init__(self, token: str, *, session=None):
        if not isinstance(token, str) or not token or token != token.strip():
            raise ValueError("Telegram bot token is required")
        self._token = token
        self._session = session or requests.Session()

    def _bounded_json_post(self, method: str, payload: dict[str, str]) -> Mapping[str, object]:
        response = self._session.post(f"https://api.telegram.org/bot{self._token}/{method}",
                                      data=payload, timeout=30)
        raw = response.content
        if response.status_code != 200 or not isinstance(raw, bytes) or len(raw) > 256 * 1024:
            raise RuntimeError("Telegram file metadata failed")
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, Mapping) or parsed.get("ok") is not True or not isinstance(parsed.get("result"), Mapping):
            raise RuntimeError("Telegram file metadata failed")
        return parsed["result"]

    def fetch(self, file_id: str) -> bytes:
        metadata = self._bounded_json_post("getFile", {"file_id": file_id})
        file_path = _safe_telegram_path(metadata)
        response = self._session.get(
            f"https://api.telegram.org/file/bot{self._token}/{file_path}",
            timeout=30, stream=True)
        return _bounded_jpeg(response, max_bytes=10 * 1024 * 1024)


class EvidenceInspector:
    PRIVATE = re.compile(r"\b(?:saldo|tel[eé]fono|correo|email|usuario|clabe)\b", re.I)
    TICKET_ID = re.compile(r"\bID\s*[:#]?\s*([0-9]{6,20})\b", re.I)

    def __init__(self, *, ocr: Callable[[bytes], str]):
        self._ocr = ocr

    def inspect(self, jpeg: bytes, *, report: ResultReport) -> EvidenceDecision:
        text = " ".join(self._ocr(jpeg).split())
        digest = sha256(text.encode("utf-8")).hexdigest()
        ticket = self.TICKET_ID.search(text)
        if self.PRIVATE.search(text) or ticket is None:
            return EvidenceDecision("pending_review", "", (), digest)
        matched = tuple(int(row["id"]) for row in report.rows
                        if _event_and_score_match(text, row))
        if len(matched) not in {1, 6}:
            return EvidenceDecision("pending_review", ticket.group(1), (), digest)
        return EvidenceDecision("matched", ticket.group(1), matched, digest)


def _event_and_score_match(text: str, row: Mapping[str, object]) -> bool:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    event = unicodedata.normalize("NFKD", str(row["partido"])).encode("ascii", "ignore").decode().casefold()
    teams = [" ".join(team.split()) for team in re.split(r"\s+(?:vs[.]?|v[.]?)\s+", event) if team.strip()]
    score = " ".join(str(row["resultado_marcador"]).replace("–", "-").split()).casefold()
    return len(teams) == 2 and all(team in folded for team in teams) and score in folded


def _safe_telegram_path(payload: Mapping[str, object]) -> str:
    value = payload.get("file_path")
    if (not isinstance(value, str) or value != value.strip()
            or re.fullmatch(r"photos/[A-Za-z0-9_.-]{1,180}", value) is None):
        raise RuntimeError("Telegram file path was invalid")
    return value


def _bounded_jpeg(response: object, *, max_bytes: int) -> bytes:
    try:
        if getattr(response, "status_code", None) != 200:
            raise RuntimeError("Telegram ticket download failed")
        data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            if not isinstance(chunk, bytes) or len(data) + len(chunk) > max_bytes:
                raise RuntimeError("Telegram ticket download failed")
            data.extend(chunk)
        value = bytes(data)
        if not value.startswith(b"\xff\xd8") or not value.endswith(b"\xff\xd9"):
            raise RuntimeError("Telegram ticket download failed")
        return value
    finally:
        response.close()


def tesseract_ocr(jpeg: bytes) -> str:
    with Image.open(BytesIO(jpeg)) as image:
        image.load()
        return pytesseract.image_to_string(image.convert("RGB"), lang="spa+eng")


@dataclass(frozen=True, slots=True)
class TicketCandidate:
    evidence_key: str
    file_id: str
    file_unique_id: str
    received_at: str


class SupabaseTicketEvidenceRepository:
    def __init__(self, client: object):
        self._client = client

    def candidates(self, *, portfolio_date: str) -> tuple[TicketCandidate, ...]:
        response = (self._client.table("tickets_ganadores")
            .select("file_id,file_unique_id,received_at")
            .gte("received_at", f"{portfolio_date}T00:00:00-06:00")
            .lt("received_at", f"{portfolio_date}T23:59:59.999999-06:00")
            .order("received_at", desc=False).execute())
        rows = response.data
        if not isinstance(rows, list):
            raise RuntimeError("ticket evidence query failed")
        result = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"file_id", "file_unique_id", "received_at"}:
                raise RuntimeError("ticket evidence query returned invalid data")
            key = str(row["file_unique_id"] or row["file_id"])
            result.append(TicketCandidate(key, str(row["file_id"]),
                                          str(row["file_unique_id"] or ""),
                                          str(row["received_at"])))
        return tuple(result)

    def record(self, *, candidate: TicketCandidate, report: ResultReport,
               decision: EvidenceDecision, media_digest: str) -> None:
        payload = {"evidence_key": candidate.evidence_key, "batch_id": report.batch_id,
            "portfolio_date": report.portfolio_date, "state": decision.state,
            "ticket_id": decision.ticket_id, "pick_ids": list(decision.pick_ids),
            "media_digest": media_digest, "ocr_digest": decision.ocr_digest}
        response = self._client.table("ticket_evidence_reviews").upsert(
            payload, on_conflict="evidence_key").execute()
        if not isinstance(response.data, list) or len(response.data) != 1:
            raise RuntimeError("ticket evidence review was not persisted")


def collect_matched_evidence(report: ResultReport, *, repository: SupabaseTicketEvidenceRepository,
                             fetcher: TelegramTicketFetcher,
                             inspector: EvidenceInspector) -> tuple[MatchedEvidence, ...]:
    matched = []
    for candidate in repository.candidates(portfolio_date=report.portfolio_date):
        try:
            jpeg = fetcher.fetch(candidate.file_id)
            media_digest = sha256(jpeg).hexdigest()
            decision = inspector.inspect(jpeg, report=report)
            repository.record(candidate=candidate, report=report, decision=decision,
                              media_digest=media_digest)
        except Exception:
            LOGGER.warning("ticket evidence status=pending_review")
            continue
        if decision.state == "matched":
            matched.append(MatchedEvidence(candidate.evidence_key, decision.ticket_id,
                                           media_digest, decision.pick_ids, jpeg))
    return tuple(matched)
```

Wrap pytesseract with an injectable function. `TesseractNotFoundError`, malformed
JPEG, oversized response, Telegram error, or ambiguous OCR all produce a safe
`pending_review` outcome and never print OCR text.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_ticket_evidence.py tests/test_payment_review.py tests/test_supabase_contract.py -q`

Expected: PASS and existing ticket/payment behavior unchanged.

```powershell
git add backend/ticket_evidence.py backend/ticket_listener.py supabase/migrations/20260824180000_vertical_media_delivery.sql tests/test_ticket_evidence.py tests/test_supabase_contract.py
git commit -m "feat: validate original ticket evidence"
```

## Task 8: Final result and evidence stories

**Files:**

- Modify: `backend/vertical_publisher.py`
- Modify: `backend/vertical_repository.py`
- Modify: `backend/verificar_resultados.py`
- Modify: `tests/test_vertical_publisher.py`
- Modify: `tests/test_result_report_workflow.py`

- [ ] **Step 1: Write failing final-story behavior tests**

```python
def test_final_result_publishes_summary_card_then_original_evidence(final_report, matched_evidence, deps):
    outcomes = publish_final_stories(final_report, evidence=(matched_evidence,), **deps)
    assert list(outcomes) == ["final_results_story", "verified_result_story", "ticket_evidence_story"]
    assert deps.transport.urls[1].endswith(".jpg")
    assert deps.renderer.calls[-1].kind == "ticket_evidence_story"


def test_missing_or_ambiguous_evidence_does_not_block_result_summary(final_report, deps):
    outcomes = publish_final_stories(final_report, evidence=(), **deps)
    assert outcomes == {"final_results_story": "success"}


def test_verifier_attempts_vertical_after_existing_five_destinations(monkeypatch):
    order = []
    monkeypatch.setattr(verifier, "publish_result_report", lambda *a, **k: order.append("report") or healthy)
    monkeypatch.setattr(verifier, "publish_final_stories_from_runtime", lambda report: order.append("vertical") or {})
    verifier.publish_available_result_reports()
    assert order == ["report", "vertical"]
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m pytest tests/test_vertical_publisher.py tests/test_result_report_workflow.py -q`

Expected: FAIL because final vertical orchestration is not implemented.

- [ ] **Step 3: Implement ordered result/evidence publication**

```python
from collections.abc import Sequence

from backend.ticket_evidence import MatchedEvidence
from backend.vertical_content import build_ticket_evidence_card


def publish_final_stories(report: ResultReport, *, evidence: Sequence[MatchedEvidence], **deps) -> dict[str, str]:
    if report.kind != "final" or not report.terminal:
        raise ValueError("final stories require a final report")
    outcomes: dict[str, str] = {}
    summary = build_final_results_story(report)
    outcomes[summary.kind] = _publish_story(summary, **deps)
    if evidence:
        item = sorted(evidence, key=lambda value: (-len(value.pick_ids), value.evidence_id))[0]
        if len(item.pick_ids) == 1:
            card = build_verified_result_story(report, pick_id=item.pick_ids[0])
            outcomes[card.kind] = _publish_story(card, **deps)
        evidence_card = build_ticket_evidence_card(report, evidence_id=item.evidence_id,
                                                   media_digest=item.media_digest)
        outcomes[evidence_card.kind] = _publish_evidence_story(
            evidence_card, item.jpeg, **deps)
    return outcomes


def _publish_evidence_story(card: VerticalCard, original_jpeg: bytes, **deps) -> str:
    return _publish_story(
        card,
        renderer=lambda _card: render_ticket_evidence_jpeg(
            original_jpeg, observed_label=f"{card.portfolio_date} · CDMX"),
        **deps,
    )
```

The repository returns only matched, unconsumed evidence for the same portfolio.
After successful `ticket_evidence_story`, record the media receipt against that
evidence key. A later run sees it complete and does not resend it.

- [ ] **Step 4: Integrate with the verifier without weakening existing strict reports**

After `publish_result_report` returns for a final report, call
`publish_final_stories_from_runtime(report)`. Print its complete safe outcome map.
Keep `require_healthy_result_reports(published)` unchanged: the five existing
destinations remain strict. Vertical failures are recorded, alert admin, and leave
the verifier nonzero only when Meta is configured and a claimed vertical delivery
cannot complete; missing evidence is a healthy no-op.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_vertical_publisher.py tests/test_result_report_workflow.py tests/test_result_report_publisher.py -q`

Expected: PASS.

```powershell
git add backend/vertical_publisher.py backend/vertical_repository.py backend/verificar_resultados.py tests/test_vertical_publisher.py tests/test_result_report_workflow.py
git commit -m "feat: publish verified result stories"
```

## Task 9: Free local reel rendering and validation

**Files:**

- Create: `backend/reel_renderer.py`
- Create: `tests/test_reel_renderer.py`
- Modify: `backend/vertical_repository.py`
- Modify: `tests/test_vertical_repository.py`
- Modify: `tests/test_backend_requirements.py`

- [ ] **Step 1: Write failing FFmpeg and FFprobe contract tests**

```python
def test_reel_is_vertical_h264_and_between_eight_and_fifteen_seconds(story_frames, media_tools):
    video = ReelRenderer(ffmpeg=media_tools.ffmpeg, ffprobe=media_tools.ffprobe).render(story_frames)
    probe = media_tools.probe(video)
    assert probe["codec_name"] == "h264"
    assert (probe["width"], probe["height"]) == (1080, 1920)
    assert 8 <= float(probe["duration"]) <= 15
    assert probe["pix_fmt"] == "yuv420p"


def test_reel_rejects_fewer_than_three_or_more_than_five_frames(media_tools, story_jpeg):
    renderer = ReelRenderer(ffmpeg=media_tools.ffmpeg, ffprobe=media_tools.ffprobe)
    with pytest.raises(ValueError, match="three to five"):
        renderer.render([story_jpeg, story_jpeg])


def test_repository_uploads_validated_mp4_under_digest_key(repository, reel_package, reel_bytes):
    asset = repository.upload_reel(package=reel_package, mp4=reel_bytes)
    assert asset.object_key == f"reels/2026-08-24/daily_results_reel-{reel_package.digest}.mp4"
    assert asset.mime_type == "video/mp4"
```

- [ ] **Step 2: Run reel tests and confirm failure**

Run: `python -m pytest tests/test_reel_renderer.py -q`

Expected: FAIL because `reel_renderer.py` does not exist.

- [ ] **Step 3: Implement deterministic FFmpeg composition**

```python
from collections.abc import Mapping, Sequence
from io import BytesIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image

from backend.vertical_content import ReelPackage
from backend.vertical_repository import TemporaryAsset


class ReelRenderer:
    def __init__(self, *, ffmpeg: str, ffprobe: str):
        if not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
            raise ValueError("FFmpeg and FFprobe executables are required")
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    def render(self, frames: Sequence[bytes]) -> bytes:
        if not 3 <= len(frames) <= 5:
            raise ValueError("reel requires three to five story frames")
        with TemporaryDirectory(prefix="rey-taco-reel-") as directory:
            root = Path(directory)
            for index, data in enumerate(frames):
                _validate_story_jpeg(data)
                (root / f"frame-{index:02d}.jpg").write_bytes(data)
            manifest = root / "frames.txt"
            duration = 2.4
            manifest.write_text("".join(
                f"file '{(root / f'frame-{i:02d}.jpg').as_posix()}'\nduration {duration}\n"
                for i in range(len(frames))) +
                f"file '{(root / f'frame-{len(frames)-1:02d}.jpg').as_posix()}'\n",
                encoding="utf-8")
            output = root / "reel.mp4"
            _run_checked([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(manifest), "-vf", "fps=30,format=yuv420p",
                "-c:v", "libx264", "-movflags", "+faststart", "-an", str(output)], timeout=90)
            metadata = _probe(self._ffprobe, output)
            _validate_probe(metadata)
            return output.read_bytes()


# Add the following method to SupabaseVerticalRepository in
# backend/vertical_repository.py.
def upload_reel(self, *, package: ReelPackage, mp4: bytes) -> TemporaryAsset:
    if not isinstance(mp4, bytes) or len(mp4) < 12 or len(mp4) > 50 * 1024 * 1024:
        raise ValueError("reel must contain bounded immutable MP4 bytes")
    if mp4[4:8] != b"ftyp":
        raise ValueError("reel must use an MP4 container")
    object_key = f"reels/{package.portfolio_date}/daily_results_reel-{package.digest}.mp4"
    bucket = self._client.storage.from_(self.BUCKET)
    response = bucket.upload(path=object_key, file=mp4,
        file_options={"content-type": "video/mp4", "upsert": "true"})
    _validate_upload_response(response, bucket=self.BUCKET, object_key=object_key)
    url = _validated_public_url(bucket.get_public_url(object_key),
        supabase_url=self._url, bucket=self.BUCKET, object_key=object_key)
    return TemporaryAsset(object_key, url, "video/mp4")


# Keep these helpers in backend/reel_renderer.py.
def _validate_story_jpeg(data: bytes) -> None:
    if not isinstance(data, bytes) or len(data) > 5 * 1024 * 1024:
        raise ValueError("reel frame must be bounded JPEG bytes")
    with Image.open(BytesIO(data)) as image:
        image.load()
        if image.format != "JPEG" or image.mode != "RGB" or image.size != (1080, 1920):
            raise ValueError("reel frame must be an RGB 1080x1920 JPEG")


def _run_checked(arguments: list[str], *, timeout: int) -> None:
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError("FFmpeg rendering failed")


def _probe(ffprobe: str, path: Path) -> Mapping[str, object]:
    result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", str(path)], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=30, check=False)
    if result.returncode != 0 or len(result.stdout) > 256 * 1024:
        raise RuntimeError("FFprobe validation failed")
    value = json.loads(result.stdout.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("FFprobe validation failed")
    return value


def _validate_probe(metadata: Mapping[str, object]) -> None:
    streams = metadata.get("streams")
    form = metadata.get("format")
    if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], Mapping):
        raise RuntimeError("reel video stream was invalid")
    video = streams[0]
    duration = float(form.get("duration")) if isinstance(form, Mapping) else 0.0
    if (video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p"
            or (video.get("width"), video.get("height")) != (1080, 1920)
            or not 8 <= duration <= 15):
        raise RuntimeError("reel media contract failed")
```

Use a runner-provided FFmpeg/FFprobe pair. Do not download executables at runtime.
Keep subprocess output bounded, use argument arrays rather than shell strings, cap
execution at 90 seconds, and remove the temporary directory in all outcomes.

- [ ] **Step 4: Add dependency/runtime assertions and run tests**

Do not add an unnecessary Python media framework. Keep `backend/requirements.txt`
unchanged and update `tests/test_backend_requirements.py` to assert no
paid/generative video SDK was added.

Run: `python -m pytest tests/test_reel_renderer.py tests/test_vertical_repository.py tests/test_backend_requirements.py -q`

Expected: PASS on a host with FFmpeg and skip with an explicit reason when the test
tool fixture cannot locate both binaries.

- [ ] **Step 5: Commit the reel renderer**

```powershell
git add backend/reel_renderer.py backend/vertical_repository.py tests/test_reel_renderer.py tests/test_vertical_repository.py tests/test_backend_requirements.py
git commit -m "feat: render reels locally with ffmpeg"
```

## Task 10: Instagram and Facebook Reel transports

**Files:**

- Modify: `backend/vertical_meta.py`
- Modify: `tests/test_vertical_meta.py`

- [ ] **Step 1: Write failing transport sequence tests**

```python
def test_instagram_reel_uses_reels_container_and_share_to_feed(fake_session, settings):
    fake_session.queue((200, {"id": "ig-container"}), (200, {"status_code": "FINISHED"}),
                       (200, {"id": "ig-reel"}))
    result = transport(fake_session).publish_instagram_reel(video_url=VIDEO_URL, settings=settings)
    assert result == VerticalDelivery("instagram_reel", "success", "ig-reel")
    assert fake_session.calls[0]["data"] == {
        "video_url": VIDEO_URL, "media_type": "REELS", "share_to_feed": "true"}


def test_facebook_reel_runs_start_upload_finish_with_page_token(fake_session, settings, reel_bytes):
    fake_session.queue((200, {"video_id": "fb-video", "upload_url": "https://rupload.facebook.com/video-upload/v26.0/fb-video"}),
                       (200, {"success": True}), (200, {"success": True}))
    result = transport(fake_session).publish_facebook_reel(mp4=reel_bytes, settings=settings,
                                                            description="Resultados verificados")
    assert result == VerticalDelivery("facebook_reel", "success", "fb-video")
    assert [call["phase"] for call in fake_session.semantic_calls] == ["start", "upload", "finish"]
```

- [ ] **Step 2: Run transport tests and confirm missing methods**

Run: `python -m pytest tests/test_vertical_meta.py -q`

Expected: FAIL with missing reel methods.

- [ ] **Step 3: Implement Instagram Reel transport**

```python
def publish_instagram_reel(self, *, video_url: str, settings: MetaSettings) -> VerticalDelivery:
    if not settings.token or not settings.instagram_user_id:
        return VerticalDelivery("instagram_reel", "not_configured")
    if not _validated_vertical_url(video_url, suffix=".mp4"):
        return VerticalDelivery("instagram_reel", "media_invalid")
    created = self._post(meta_graph_url(settings, f"{settings.instagram_user_id}/media"),
        settings, {"video_url": video_url, "media_type": "REELS", "share_to_feed": "true"})
    container = _required_id(created, destination="instagram_reel")
    if isinstance(container, VerticalDelivery):
        return container
    waiting = self._wait_for_container(container, settings=settings, destination="instagram_reel")
    if waiting is not None:
        return waiting
    published = self._post(meta_graph_url(settings, f"{settings.instagram_user_id}/media_publish"),
        settings, {"creation_id": container})
    receipt = _required_id(published, destination="instagram_reel")
    return receipt if isinstance(receipt, VerticalDelivery) else VerticalDelivery(
        "instagram_reel", "success", receipt)
```

- [ ] **Step 4: Implement Facebook Page Reel transport**

Resolve the Page access token using the existing safe feed fallback, then:

```python
def publish_facebook_reel(self, *, mp4: bytes, settings: MetaSettings,
                          description: str) -> VerticalDelivery:
    if not settings.token or not settings.facebook_page_id:
        return VerticalDelivery("facebook_reel", "not_configured")
    if not isinstance(mp4, bytes) or len(mp4) < 12 or mp4[4:8] != b"ftyp":
        return VerticalDelivery("facebook_reel", "media_invalid")
    page_token = self._resolve_page_token(settings)
    if isinstance(page_token, VerticalDelivery):
        return page_token
    start_response = self._session.post(
        meta_graph_url(settings, f"{settings.facebook_page_id}/video_reels"),
        headers=meta_auth_headers(page_token), data={"upload_phase": "start"},
        timeout=30, stream=True)
    status, payload = read_meta_json(start_response)
    failure = _meta_failure("facebook_reel", status, payload)
    if failure is not None:
        return failure
    start = _safe_reel_start(payload)
    if start is None:
        return VerticalDelivery("facebook_reel", "delivery_failed")
    video_id, upload_url = start
    if not _exact_rupload_url(upload_url, video_id=video_id, version=settings.graph_version):
        return VerticalDelivery("facebook_reel", "delivery_failed")
    uploaded = self._session.post(upload_url, headers={
        "Authorization": f"OAuth {page_token}", "offset": "0",
        "file_size": str(len(mp4)), "Content-Type": "application/octet-stream",
        "Accept-Encoding": "identity"}, data=mp4, timeout=90, stream=True)
    upload_status, upload_payload = read_meta_json(uploaded)
    if upload_status < 200 or upload_status >= 300 or upload_payload != {"success": True}:
        return VerticalDelivery("facebook_reel", "delivery_failed")
    finished = self._session.post(
        meta_graph_url(settings, f"{settings.facebook_page_id}/video_reels"),
        headers=meta_auth_headers(page_token), data={"upload_phase": "finish",
            "video_id": video_id, "video_state": "PUBLISHED", "description": description},
        timeout=30, stream=True)
    finish_status, finish_payload = read_meta_json(finished)
    if finish_status < 200 or finish_status >= 300 or finish_payload != {"success": True}:
        return VerticalDelivery("facebook_reel", "delivery_failed")
    return VerticalDelivery("facebook_reel", "success", video_id)


def _resolve_page_token(self, settings: MetaSettings) -> str | VerticalDelivery:
    response = self._session.get(
        meta_graph_url(settings, f"{settings.facebook_page_id}?fields=access_token"),
        headers=meta_auth_headers(settings.token), timeout=30, stream=True)
    status, payload = read_meta_json(response)
    failure = _meta_failure("facebook_reel", status, payload)
    if failure is not None:
        return failure
    value = payload.get("access_token") if isinstance(payload, Mapping) else None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 4096:
        return VerticalDelivery("facebook_reel", "delivery_failed")
    return value


def _safe_reel_start(payload: object) -> tuple[str, str] | None:
    if not isinstance(payload, Mapping) or set(payload) != {"video_id", "upload_url"}:
        return None
    video_id, upload_url = payload["video_id"], payload["upload_url"]
    if not isinstance(video_id, str) or re.fullmatch(r"[A-Za-z0-9_:-]{1,200}", video_id) is None:
        return None
    return (video_id, upload_url) if isinstance(upload_url, str) else None


def _exact_rupload_url(value: str, *, video_id: str, version: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.hostname == "rupload.facebook.com"
            and parsed.path == f"/video-upload/{version}/{video_id}"
            and not parsed.query and not parsed.fragment)
```

Reject redirects or upload hosts other than `rupload.facebook.com`, bound every
response, and never log the Page token or response body.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_vertical_meta.py tests/test_social_poster.py -q`

Expected: PASS.

```powershell
git add backend/vertical_meta.py tests/test_vertical_meta.py
git commit -m "feat: publish reels to Instagram and Facebook"
```

## Task 11: Daily reel orchestration, workflow recovery, and host checks

**Files:**

- Modify: `backend/vertical_publisher.py`
- Modify: `backend/vertical_repository.py`
- Modify: `backend/verificar_resultados.py`
- Modify: `.github/workflows/scraper.yml`
- Modify: `.github/workflows/delivery-recovery.yml`
- Modify: `scripts/windows/Test-ReyTacoRunnerHost.ps1`
- Modify: `tests/test_vertical_publisher.py`
- Modify: `tests/test_vertical_workflows.py`
- Modify: `tests/test_windows_host_check.py`

- [ ] **Step 1: Write failing daily-reel and recovery tests**

```python
def test_daily_reel_renders_once_and_completes_destinations_independently(final_report, deps):
    outcomes = publish_daily_reel(final_report, evidence=deps.evidence, **deps.kwargs)
    assert outcomes == {"instagram_reel": "success", "facebook_reel": "success"}
    assert deps.reel_renderer.calls == 1


def test_retry_calls_only_failed_facebook_destination(final_report, deps):
    deps.repository.states.update(instagram_reel="complete", facebook_reel="failed")
    outcomes = publish_daily_reel(final_report, evidence=deps.evidence, **deps.kwargs)
    assert outcomes["instagram_reel"] == "complete"
    assert deps.instagram.calls == []
    assert len(deps.facebook.calls) == 1


def test_second_settled_batch_same_portfolio_date_does_not_create_second_reel(
        first_final_report, second_final_report, deps):
    publish_daily_reel(first_final_report, evidence=(), **deps.kwargs)
    outcomes = publish_daily_reel(second_final_report, evidence=(), **deps.kwargs)
    assert outcomes == {"instagram_reel": "complete", "facebook_reel": "complete"}
    assert deps.reel_renderer.calls == 1


def test_workflows_install_ffmpeg_and_tesseract_only_for_result_media():
    workflow = Path(".github/workflows/scraper.yml").read_text(encoding="utf-8")
    assert "ffmpeg" in workflow and "tesseract-ocr" in workflow
    assert "backend.vertical_publisher --mode final" in workflow
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_vertical_publisher.py tests/test_vertical_workflows.py tests/test_windows_host_check.py -q`

Expected: FAIL because final reel orchestration and runner checks are absent.

- [ ] **Step 3: Implement one-render/two-destination reel delivery**

```python
def frames_for_daily_reel(report: ResultReport, *, evidence: Sequence[MatchedEvidence]) -> tuple[bytes, ...]:
    summary = build_final_results_story(report)
    featured_row = next((row for row in report.rows if row["estado"] == "ganado"), report.rows[0])
    detail = build_verified_result_story(report, pick_id=int(featured_row["id"]))
    closing = build_reel_cta_story(report)
    frames = [render_story_jpeg(summary), render_story_jpeg(detail)]
    if evidence:
        selected = sorted(evidence, key=lambda item: (-len(item.pick_ids), item.evidence_id))[0]
        frames.append(render_ticket_evidence_jpeg(
            selected.jpeg, observed_label=f"{report.portfolio_date} · CDMX"))
    frames.append(render_story_jpeg(closing))
    return tuple(frames)


def publish_daily_reel(report: ResultReport, *, frames: Sequence[bytes], repository,
                       renderer, transport, settings) -> dict[str, str]:
    card = build_daily_reel_package(report)
    claims = {destination: repository.claim(
        batch_id=card.batch_id, portfolio_date=card.portfolio_date,
        content_kind="daily_results_reel", destination=destination,
        digest=card.digest, template_version=card.template_version)
        for destination in ("instagram_reel", "facebook_reel")}
    active = {name: claim for name, claim in claims.items() if claim.state == "claimed"}
    outcomes = {name: claim.state for name, claim in claims.items() if claim.state != "claimed"}
    if not active:
        return outcomes
    mp4 = renderer.render(frames)
    asset = repository.upload_reel(package=card, mp4=mp4)
    try:
        for destination, claim in active.items():
            assert claim.attempt_id is not None
            delivery = (transport.publish_instagram_reel(video_url=asset.url, settings=settings)
                        if destination == "instagram_reel" else
                        transport.publish_facebook_reel(mp4=mp4, settings=settings,
                                                        description=card.caption))
            repository.complete(package=card, destination=destination,
                attempt_id=claim.attempt_id, success=delivery.status == "success",
                receipt=delivery.receipt if delivery.status == "success" else "",
                error="" if delivery.status == "success" else delivery.status)
            outcomes[destination] = delivery.status
    finally:
        try:
            repository.delete_temporary(asset)
        except RuntimeError:
            LOGGER.warning("vertical cleanup status=failed kind=daily_results_reel")
    return outcomes
```

- [ ] **Step 4: Add runtime tools and recovery**

In `.github/workflows/scraper.yml`, before dependency installation:

```yaml
      - name: Install local media inspection tools
        run: sudo apt-get update && sudo apt-get install -y ffmpeg tesseract-ocr tesseract-ocr-spa
```

Pass the existing Supabase, Telegram, Meta, Facebook, and Instagram secrets to
`python -m backend.vertical_publisher --mode final`. Add an equivalent vertical
recovery step to `delivery-recovery.yml` using the same ledger; install the same
`ffmpeg`, `tesseract-ocr`, and `tesseract-ocr-spa` packages in that job, and do not
invoke the scraper. The recovery command is
`python -m backend.vertical_publisher --mode recover`; it loads only final reports
and incomplete ledger destinations.

Add `ffmpeg`, `ffprobe`, and `tesseract` SETUP checks to
`Test-ReyTacoRunnerHost.ps1` using `Get-Command`. The script only reports missing
tools; it does not install software or open a window.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_vertical_publisher.py tests/test_vertical_workflows.py tests/test_windows_host_check.py tests/test_result_report_workflow.py -q`

Expected: PASS.

```powershell
git add backend/vertical_publisher.py backend/vertical_repository.py backend/verificar_resultados.py .github/workflows/scraper.yml .github/workflows/delivery-recovery.yml scripts/windows/Test-ReyTacoRunnerHost.ps1 tests/test_vertical_publisher.py tests/test_vertical_workflows.py tests/test_windows_host_check.py
git commit -m "feat: orchestrate and recover daily reels"
```

## Task 12: Configuration, security scan, dry-run preview, and release verification

**Files:**

- Modify: `.env.example`
- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `tests/test_source_security.py`
- Modify: `tests/test_vertical_workflows.py`
- Modify: `tests/test_result_report_workflow.py`

- [ ] **Step 1: Write failing configuration and security tests**

```python
def test_examples_name_vertical_configuration_without_values():
    for path in (Path(".env.example"), Path("backend/.env.example")):
        text = path.read_text(encoding="utf-8")
        assert "VERTICAL_MEDIA_BUCKET=social-vertical" in text
        assert "VERTICAL_DRY_RUN=false" in text
        assert "TELEGRAM_BOT_TOKEN=" in text
        assert "bot-secret" not in text


def test_vertical_modules_do_not_log_secrets_or_control_browser():
    names = ("vertical_content.py", "story_renderer.py", "vertical_repository.py",
             "meta_http.py", "vertical_meta.py", "ticket_evidence.py",
             "reel_renderer.py", "vertical_publisher.py")
    sources = "\n".join((Path("backend") / name).read_text(encoding="utf-8") for name in names)
    assert "webdriver" not in sources
    assert "pyautogui" not in sources
    assert "print(settings.token" not in sources
```

- [ ] **Step 2: Run the security tests and confirm failure**

Run: `python -m pytest tests/test_source_security.py tests/test_vertical_workflows.py -q`

Expected: FAIL until examples and documentation include the new safe variables.

- [ ] **Step 3: Document exact commands and safe configuration**

Add these name-only settings:

```dotenv
VERTICAL_MEDIA_BUCKET=social-vertical
VERTICAL_DRY_RUN=false
VERTICAL_DRY_RUN_OUTPUT=
META_GRAPH_VERSION=v26.0
```

Document:

```powershell
python -m backend.vertical_publisher --mode pre-event --dry-run
python -m backend.vertical_publisher --mode final --dry-run
python -m pytest tests/test_vertical_content.py tests/test_story_renderer.py tests/test_vertical_repository.py tests/test_vertical_meta.py tests/test_ticket_evidence.py tests/test_reel_renderer.py tests/test_vertical_publisher.py tests/test_vertical_workflows.py -q
```

Explain that Facebook Story appearance is a validated crosspost, not an API receipt,
and that a real publication requires explicit `--live` plus configured secrets.

- [ ] **Step 4: Run the complete automated verification**

Run:

```powershell
python -m pytest -q
python -m backend.vertical_publisher --mode pre-event --dry-run
python -m backend.vertical_publisher --mode final --dry-run
git diff --check
```

Expected:

- entire pytest suite PASS;
- dry-run writes reviewed JPEG/MP4 artifacts locally and makes no Meta call;
- `git diff --check` returns no whitespace errors;
- no browser window appears.

- [ ] **Step 5: Commit the production documentation**

```powershell
git add .env.example backend/.env.example README.md tests/test_source_security.py tests/test_vertical_workflows.py tests/test_result_report_workflow.py
git commit -m "docs: add stories and reels operations"
```

- [ ] **Step 6: Apply migration and run one controlled live story**

Run the pinned database migration workflow, verify remote migration history, then:

```powershell
python -m backend.vertical_publisher --mode final --live --stories-only
```

Expected: one reviewed Instagram Story receipt is stored in
`vertical_media_deliveries`; rerunning the same command returns `complete` and does
not publish again. Confirm whether Meta crossposts it to the Facebook Page and
record `confirmed` or `crosspost_unverified` without changing the Instagram receipt.

- [ ] **Step 7: Run one controlled reel and verify both receipts**

```powershell
python -m backend.vertical_publisher --mode final --live --reel-only
```

Expected: one Instagram Reel ID and one Facebook Reel video ID are stored; a rerun
makes zero publishing calls. Verify the rendered MP4, public posts, temporary object
cleanup, admin status message, and absence of token/raw OCR text in logs.

- [ ] **Step 8: Final commit/push gate**

```powershell
git status --short
git log --oneline -12
git push origin master
```

Expected: only intentional files are committed, unrelated ticket images and local
worktree changes remain untouched, and `origin/master` matches `HEAD`.
