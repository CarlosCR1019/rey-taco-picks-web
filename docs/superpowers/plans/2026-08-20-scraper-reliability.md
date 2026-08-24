# Scraper Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every scraper run correctly configured, idempotent, observable, public/private safe, and retryable without duplicating picks or Telegram deliveries.

**Architecture:** Keep `backend/scraper.py` as the orchestration entry point while extracting configuration, persistence, and Telegram delivery into focused modules. Supabase owns the atomic run/batch lifecycle; Python constructs one validated payload, writes only the public projection locally, and records each delivery independently.

**Tech Stack:** Python 3.11+, unittest/pytest, Supabase/PostgreSQL RPC, Selenium, urllib, GitHub Actions.

---

## File Structure

- Create `backend/scraper_config.py` for environment validation and absolute project paths.
- Create `backend/pick_publisher.py` for Supabase batch publication and public-file projection.
- Create `backend/telegram_publisher.py` for bounded, isolated Telegram deliveries.
- Modify `backend/scraper.py` so it contains one phase-7 implementation and returns meaningful exit codes.
- Create `supabase/migrations/20260820233000_scraper_run_ledger.sql` for atomic run claims, batches, and active-pick lifecycle.
- Modify `.github/workflows/scraper.yml`, `.env.example`, and `backend/.env.example` so runtime configuration matches the hardened backend.
- Create focused regression tests under `tests/` and extend the operations runbook.

### Task 1: Resolve configuration and paths independently of the current directory

**Files:**
- Create: `backend/scraper_config.py`
- Create: `tests/test_scraper_config.py`
- Modify: `backend/.env.example`
- Modify: `.env.example`

- [ ] **Step 1: Write failing configuration tests**

```python
from pathlib import Path
import pytest

from backend.scraper_config import ConfigError, load_settings


def test_paths_are_repo_relative_when_started_elsewhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = load_settings(
        values={"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "service"},
        dry_run=False,
    )
    root = Path(__file__).resolve().parents[1]
    assert settings.public_picks_path == root / "frontend" / "public" / "picks.json"
    assert settings.queue_path == root / "backend" / "channel_queue.json"


def test_production_requires_service_role():
    with pytest.raises(ConfigError, match="SUPABASE_SERVICE_ROLE_KEY"):
        load_settings(values={"SUPABASE_URL": "https://example.supabase.co"}, dry_run=False)


def test_dry_run_accepts_missing_write_credentials():
    assert load_settings(values={}, dry_run=True).dry_run is True
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_scraper_config.py -q`

Expected: FAIL because `backend.scraper_config` does not exist.

- [ ] **Step 3: Implement typed settings and explicit dotenv loading**

```python
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScraperSettings:
    dry_run: bool
    supabase_url: str
    service_role_key: str
    groq_api_key: str
    odds_api_key: str
    telegram_token: str
    telegram_admin_id: str
    telegram_vip_id: str
    telegram_free_id: str
    public_picks_path: Path
    queue_path: Path


def load_settings(
    values: Mapping[str, str | None] | None = None,
    *,
    dry_run: bool,
) -> ScraperSettings:
    merged = {**dotenv_values(BACKEND_DIR / ".env"), **os.environ} if values is None else dict(values)
    url = str(merged.get("SUPABASE_URL") or "").strip()
    service = str(merged.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not dry_run and (not url or not service):
        raise ConfigError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for publishing")
    return ScraperSettings(
        dry_run=dry_run,
        supabase_url=url,
        service_role_key=service,
        groq_api_key=str(merged.get("GROQ_API_KEY") or "").strip(),
        odds_api_key=str(merged.get("ODDS_API_KEY") or "").strip(),
        telegram_token=str(merged.get("TELEGRAM_BOT_TOKEN") or "").strip(),
        telegram_admin_id=str(merged.get("TELEGRAM_ADMIN_ID") or merged.get("TELEGRAM_CHAT_ID") or "").strip(),
        telegram_vip_id=str(merged.get("TELEGRAM_VIP_CHANNEL_ID") or merged.get("TELEGRAM_CHANNEL_ID") or "").strip(),
        telegram_free_id=str(merged.get("TELEGRAM_FREE_CHANNEL_ID") or "").strip(),
        public_picks_path=REPO_ROOT / "frontend" / "public" / "picks.json",
        queue_path=BACKEND_DIR / "channel_queue.json",
    )
```

- [ ] **Step 4: Align both environment examples**

Ensure both examples contain these empty canonical entries and no secret values:

```dotenv
GROQ_API_KEY=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
ODDS_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_ID=
TELEGRAM_FREE_CHANNEL_ID=
TELEGRAM_VIP_CHANNEL_ID=
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_scraper_config.py -q`

Expected: `3 passed`.

```bash
git add backend/scraper_config.py tests/test_scraper_config.py .env.example backend/.env.example
git commit -m "feat: validate scraper runtime configuration"
```

### Task 2: Add the atomic Supabase run and batch lifecycle

**Files:**
- Create: `supabase/migrations/20260820233000_scraper_run_ledger.sql`
- Modify: `tests/test_supabase_contract.py`

- [ ] **Step 1: Add failing SQL contract tests**

```python
RUN_LEDGER_SQL = SQL.parent / "20260820233000_scraper_run_ledger.sql"


def test_scraper_batches_are_atomic_and_idempotent(self):
    text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
    self.assertIn("create table if not exists public.scraper_runs", text)
    self.assertIn("run_key text not null unique", text)
    self.assertIn("create table if not exists public.pick_batches", text)
    self.assertIn("create or replace function public.publish_pick_batch", text)
    self.assertIn("create or replace function public.record_scraper_delivery", text)
    self.assertIn("on conflict (run_key)", text)
    self.assertIn("set active = false", text)
    self.assertIn("then 'premium'", text)


def test_visible_picks_only_exposes_the_active_pending_batch(self):
    text = " ".join(RUN_LEDGER_SQL.read_text(encoding="utf-8").lower().split())
    self.assertIn("p.estado = 'pendiente' and p.active", text)
    self.assertIn("p.estado <> 'pendiente'", text)
    self.assertIn("revoke all on table public.scraper_runs from anon, authenticated", text)
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `python -m pytest tests/test_supabase_contract.py -q`

Expected: FAIL because the run-ledger migration does not exist.

- [ ] **Step 3: Create the run-ledger schema and atomic RPC**

The migration must contain the following complete objects:

```sql
begin;

create table if not exists public.scraper_runs (
    id uuid primary key default gen_random_uuid(),
    run_key text not null unique,
    status text not null default 'running'
        check (status in ('running', 'published', 'partial', 'failed')),
    source_hash text not null,
    delivery_status jsonb not null default '{}'::jsonb,
    error_message text,
    created_at timestamptz not null default now(),
    finished_at timestamptz
);

create table if not exists public.pick_batches (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null unique references public.scraper_runs(id) on delete cascade,
    active boolean not null default false,
    created_at timestamptz not null default now()
);

alter table public.picks
    add column if not exists batch_id uuid references public.pick_batches(id),
    add column if not exists active boolean not null default false;

create index if not exists picks_active_batch_idx
    on public.picks (batch_id, active, estado);

create or replace function public.publish_pick_batch(
    requested_run_key text,
    requested_source_hash text,
    requested_picks jsonb
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    claimed_run public.scraper_runs%rowtype;
    created_batch uuid;
begin
    if jsonb_typeof(requested_picks) <> 'array' or jsonb_array_length(requested_picks) = 0 then
        raise exception 'requested_picks must be a non-empty array';
    end if;

    insert into public.scraper_runs (run_key, source_hash)
    values (requested_run_key, requested_source_hash)
    on conflict (run_key) do nothing;

    select * into claimed_run
    from public.scraper_runs
    where run_key = requested_run_key
    for update;

    if claimed_run.status in ('published', 'partial') then
        return jsonb_build_object(
            'run_id', claimed_run.id,
            'batch_id', (select id from public.pick_batches where run_id = claimed_run.id),
            'created', false
        );
    end if;

    update public.pick_batches set active = false where active;
    update public.picks
    set active = false,
        visibility = case
            when estado = 'pendiente' and visibility = 'public' then 'premium'
            else visibility
        end
    where active;

    insert into public.pick_batches (run_id, active)
    values (claimed_run.id, true)
    returning id into created_batch;

    insert into public.picks (
        id, categoria, partido, pick, cuota, confianza, razonamiento,
        es_parlay, tiene_valor, estado, fecha_generacion, fecha_evento,
        horario, odds_mercado, ganancia_simulada, visibility, batch_id, active
    )
    select
        (extract(epoch from clock_timestamp()) * 1000000)::bigint + item.ordinality,
        item.value->>'categoria', item.value->>'partido', item.value->>'pick',
        item.value->>'cuota', item.value->>'confianza', item.value->>'razonamiento',
        coalesce((item.value->>'es_parlay')::boolean, false),
        coalesce((item.value->>'tiene_valor')::boolean, false),
        'pendiente', (item.value->>'fecha_generacion')::date,
        (item.value->>'fecha_evento')::date, item.value->>'horario',
        item.value->>'odds_mercado',
        coalesce((item.value->>'ganancia_simulada')::numeric, 0),
        item.value->>'visibility', created_batch, true
    from jsonb_array_elements(requested_picks) with ordinality as item(value, ordinality);

    update public.scraper_runs
    set status = 'published', finished_at = now()
    where id = claimed_run.id;

    return jsonb_build_object('run_id', claimed_run.id, 'batch_id', created_batch, 'created', true);
end;
$$;

create or replace function public.get_visible_picks()
returns setof public.picks
language sql stable security definer
set search_path = public, pg_temp
as $$
    select p.*
    from public.picks p
    where (
        p.estado = 'pendiente'
        and p.active
        and (p.visibility = 'public' or public.is_active_subscriber(auth.uid()))
    ) or (
        p.estado <> 'pendiente'
        and p.visibility = 'public'
    );
$$;

create or replace function public.record_scraper_delivery(
    requested_run_id uuid,
    requested_destination text,
    requested_success boolean,
    requested_error text default ''
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.scraper_runs
    set delivery_status = jsonb_set(
            delivery_status,
            array[requested_destination],
            jsonb_build_object('success', requested_success, 'error', left(requested_error, 200), 'updated_at', now()),
            true
        ),
        status = case when requested_success then status else 'partial' end
    where id = requested_run_id;
end;
$$;

revoke all on table public.scraper_runs from anon, authenticated;
revoke all on table public.pick_batches from anon, authenticated;
revoke all on function public.publish_pick_batch(text, text, jsonb) from public, anon, authenticated;
revoke all on function public.record_scraper_delivery(uuid, text, boolean, text) from public, anon, authenticated;
grant execute on function public.publish_pick_batch(text, text, jsonb) to service_role;
grant execute on function public.record_scraper_delivery(uuid, text, boolean, text) to service_role;
grant execute on function public.get_visible_picks() to anon, authenticated;

commit;
```

- [ ] **Step 4: Run SQL contract tests and commit**

Run: `python -m pytest tests/test_supabase_contract.py -q`

Expected: all Supabase contract tests pass.

```bash
git add supabase/migrations/20260820233000_scraper_run_ledger.sql tests/test_supabase_contract.py
git commit -m "feat: add atomic scraper batch ledger"
```

### Task 3: Publish one idempotent batch and one public fallback

**Files:**
- Create: `backend/pick_publisher.py`
- Create: `tests/test_pick_publisher.py`

- [ ] **Step 1: Write failing publisher tests**

```python
import json

from backend.pick_publisher import publish_batch


class FakeRepository:
    def __init__(self):
        self.calls = []

    def publish(self, run_key, source_hash, picks):
        self.calls.append((run_key, source_hash, picks))
        return {"run_id": "run-1", "batch_id": "batch-1", "created": len(self.calls) == 1}


def test_public_file_contains_only_the_public_pick(tmp_path):
    repository = FakeRepository()
    rows = [
        {"pick": "Gratis", "visibility": "public", "es_parlay": False},
        {"pick": "Secreto", "visibility": "premium", "es_parlay": False},
    ]
    result = publish_batch(repository, rows, "2026-08-20T16", tmp_path / "picks.json")
    assert result.batch_id == "batch-1"
    assert json.loads((tmp_path / "picks.json").read_text(encoding="utf-8")) == [rows[0]]


def test_dry_run_never_calls_repository_or_writes_file(tmp_path):
    repository = FakeRepository()
    output = tmp_path / "picks.json"
    result = publish_batch(repository, [{"pick": "Gratis", "visibility": "public"}], "run", output, dry_run=True)
    assert result.dry_run is True
    assert repository.calls == []
    assert not output.exists()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_pick_publisher.py -q`

Expected: FAIL because `backend.pick_publisher` does not exist.

- [ ] **Step 3: Implement the publisher and Supabase repository**

```python
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from backend.publishing_policy import public_payload


class BatchRepository(Protocol):
    def publish(self, run_key: str, source_hash: str, picks: list[dict]) -> dict: ...


@dataclass(frozen=True)
class PublicationResult:
    run_id: str | None
    batch_id: str | None
    created: bool
    dry_run: bool = False


class SupabaseBatchRepository:
    def __init__(self, client):
        self.client = client

    def publish(self, run_key: str, source_hash: str, picks: list[dict]) -> dict:
        response = self.client.rpc("publish_pick_batch", {
            "requested_run_key": run_key,
            "requested_source_hash": source_hash,
            "requested_picks": picks,
        }).execute()
        return response.data

    def record_delivery(self, run_id: str, destination: str, success: bool, error: str = "") -> None:
        self.client.rpc("record_scraper_delivery", {
            "requested_run_id": run_id,
            "requested_destination": destination,
            "requested_success": success,
            "requested_error": error,
        }).execute()


def _source_hash(picks: list[dict]) -> str:
    canonical = json.dumps(picks, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_public_file(path: Path, picks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(public_payload(picks), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def publish_batch(repository, picks, run_key, public_path, *, dry_run=False):
    if dry_run:
        return PublicationResult(None, None, False, True)
    response = repository.publish(run_key, _source_hash(picks), picks)
    _write_public_file(Path(public_path), picks)
    return PublicationResult(
        str(response["run_id"]),
        str(response["batch_id"]),
        bool(response["created"]),
    )
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_pick_publisher.py -q`

Expected: `2 passed`.

```bash
git add backend/pick_publisher.py tests/test_pick_publisher.py
git commit -m "feat: publish idempotent pick batches"
```

### Task 4: Isolate and bound Telegram delivery

**Files:**
- Create: `backend/telegram_publisher.py`
- Create: `tests/test_telegram_publisher.py`

- [ ] **Step 1: Write failing delivery tests**

```python
from backend.telegram_publisher import TelegramDestination, chunk_message, deliver_batch


def test_chunks_stay_below_telegram_limit():
    chunks = chunk_message("A" * 9000, limit=4000)
    assert [len(chunk) for chunk in chunks] == [4000, 4000, 1000]


def test_destination_failures_are_isolated_and_free_receives_one_pick():
    calls = []

    def transport(destination, text):
        calls.append((destination, text))
        if destination == "admin":
            raise TimeoutError("admin unavailable")

    picks = [
        {"pick": "Gratis", "visibility": "public"},
        {"pick": "VIP", "visibility": "premium"},
    ]
    result = deliver_batch(
        picks,
        [TelegramDestination("admin", "1", "all"), TelegramDestination("vip", "2", "all"), TelegramDestination("free", "3", "public")],
        transport,
    )
    assert result["admin"].success is False
    assert result["vip"].success is True
    assert result["free"].success is True
    assert "VIP" not in "".join(text for destination, text in calls if destination == "free")


def test_retry_skips_destinations_already_recorded_as_successful():
    calls = []
    deliver_batch(
        [{"pick": "Gratis", "visibility": "public"}],
        [TelegramDestination("vip", "2", "all"), TelegramDestination("free", "3", "public")],
        lambda destination, text: calls.append(destination),
        completed={"vip"},
    )
    assert calls == ["free"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_telegram_publisher.py -q`

Expected: FAIL because `backend.telegram_publisher` does not exist.

- [ ] **Step 3: Implement isolated delivery and bounded HTTP transport**

```python
from dataclasses import dataclass
import json
import time
import urllib.request

from backend.publishing_policy import public_payload


@dataclass(frozen=True)
class TelegramDestination:
    name: str
    chat_id: str
    audience: str


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    error: str = ""


def chunk_message(text: str, limit: int = 4000) -> list[str]:
    return [text[index:index + limit] for index in range(0, len(text), limit)] or [""]


def format_batch(picks: list[dict]) -> str:
    return "\n\n".join(
        f"{row.get('partido', '')}\nPick: {row.get('pick', '')} @ {row.get('cuota', '')}\n{row.get('razonamiento', '')}".strip()
        for row in picks
    )


def deliver_batch(picks, destinations, transport, *, completed=frozenset()):
    results = {}
    for destination in destinations:
        if destination.name in completed:
            results[destination.name] = DeliveryResult(True)
            continue
        rows = public_payload(picks) if destination.audience == "public" else picks
        try:
            for chunk in chunk_message(format_batch(rows)):
                transport(destination.name, chunk)
            results[destination.name] = DeliveryResult(True)
        except Exception as exc:
            results[destination.name] = DeliveryResult(False, type(exc).__name__)
    return results


class TelegramHttpTransport:
    def __init__(self, token: str, chat_ids: dict[str, str], timeout: float = 10, retries: int = 2):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_ids = chat_ids
        self.timeout = timeout
        self.retries = retries

    def __call__(self, destination: str, text: str) -> None:
        payload = json.dumps({"chat_id": self.chat_ids[destination], "text": text}).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, headers={"Content-Type": "application/json"})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if response.getcode() != 200:
                        raise RuntimeError(f"Telegram HTTP {response.getcode()}")
                    return
            except Exception:
                if attempt == self.retries:
                    raise
                time.sleep(2 ** attempt)
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_telegram_publisher.py -q`

Expected: `3 passed`.

After delivery, the phase-7 orchestrator must call `repository.record_delivery(publication.run_id, name, result.success, result.error)` for every attempted destination. On an idempotent retry it must read successful names from the run ledger and pass them through `completed` so they are not resent.

```bash
git add backend/telegram_publisher.py tests/test_telegram_publisher.py
git commit -m "feat: isolate bounded Telegram deliveries"
```

### Task 5: Remove shadowed scraper code and repair the fallback

**Files:**
- Modify: `backend/scraper.py`
- Create: `tests/test_scraper_structure.py`

- [ ] **Step 1: Write failing AST and fallback regression tests**

```python
import ast
from pathlib import Path


SCRAPER = Path(__file__).resolve().parents[1] / "backend" / "scraper.py"


def test_scraper_has_no_duplicate_top_level_functions():
    tree = ast.parse(SCRAPER.read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert len(names) == len(set(names))


def test_fallback_uses_the_function_argument_not_an_undefined_global():
    text = SCRAPER.read_text(encoding="utf-8")
    assert "if len(picks_fallback) < 3 and partidos_data:" in text
    assert "for p in partidos_data:" in text
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_scraper_structure.py -q`

Expected: FAIL for duplicate functions and references to `partidos`.

- [ ] **Step 3: Keep one phase-7 implementation and fix the fallback**

Delete the first shadowed `fase7_guardar_y_notificar`, `_guardar_local`, and `_enviar_telegram` blocks. Replace both fallback references exactly:

```python
if len(picks_fallback) < 3 and partidos_data:
    for p in partidos_data:
```

The remaining phase 7 must call the extracted publisher and Telegram modules; it must not contain direct `urlopen`, direct local JSON writes, or timestamp-derived database IDs.

Also remove the unused `date`, `timezone`, and `By` imports, the inner `timezone` re-import, unnecessary `f` prefixes on strings without placeholders, and the unused response binding reported by pyflakes.

- [ ] **Step 4: Run structure, static, and existing policy tests**

Run: `python -m pytest tests/test_scraper_structure.py tests/test_publishing_policy.py tests/test_source_security.py -q && python -m pyflakes backend/scraper.py`

Expected: all tests pass and pyflakes reports no undefined names or redefinitions.

- [ ] **Step 5: Commit**

```bash
git add backend/scraper.py tests/test_scraper_structure.py
git commit -m "refactor: remove shadowed scraper publishing code"
```

### Task 6: Add dry-run behavior, schema probing, and truthful exit codes

**Files:**
- Modify: `backend/scraper.py`
- Modify: `backend/pick_publisher.py`
- Create: `tests/test_scraper_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
from backend.scraper import ExitCode, run_main


class FakeResult:
    def __init__(self, event_count=2, pick_count=1, persisted=False, failed_deliveries=()):
        self.event_count = event_count
        self.pick_count = pick_count
        self.persisted = persisted
        self.failed_deliveries = failed_deliveries


class FakePipeline:
    def __init__(self, result):
        self.result = result
        self.publications = 0
        self.deliveries = 0

    def run(self):
        return self.result


def test_configuration_failure_returns_nonzero():
    assert run_main([], values={}) == ExitCode.CONFIGURATION


def test_dry_run_skips_writes_and_returns_success():
    fake_pipeline = FakePipeline(FakeResult())
    code = run_main(["--dry-run"], values={}, pipeline=fake_pipeline)
    assert code == ExitCode.SUCCESS
    assert fake_pipeline.publications == 0
    assert fake_pipeline.deliveries == 0


def test_no_verified_picks_is_not_reported_as_success():
    pipeline = FakePipeline(FakeResult(pick_count=0))
    assert run_main(["--dry-run"], values={}, pipeline=pipeline) == ExitCode.NO_CANDIDATES
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_scraper_cli.py -q`

Expected: FAIL because `ExitCode` and `run_main` do not exist.

- [ ] **Step 3: Implement the command boundary**

Add this boundary and inject the existing pipeline through a small adapter:

```python
from argparse import ArgumentParser
from enum import IntEnum

from backend.scraper_config import ConfigError, load_settings


class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIGURATION = 2
    NO_EVENTS = 3
    NO_CANDIDATES = 4
    PERSISTENCE = 5
    DELIVERY = 6
    UNEXPECTED = 10


def parse_args(argv):
    parser = ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run_main(argv=None, *, values=None, pipeline=None):
    args = parse_args(argv)
    try:
        settings = load_settings(values, dry_run=args.dry_run)
        active_pipeline = pipeline or build_pipeline(settings)
        result = active_pipeline.run()
        if result.event_count == 0:
            return ExitCode.NO_EVENTS
        if result.pick_count == 0:
            return ExitCode.NO_CANDIDATES
        if not result.persisted and not settings.dry_run:
            return ExitCode.PERSISTENCE
        if result.failed_deliveries:
            return ExitCode.DELIVERY
        return ExitCode.SUCCESS
    except ConfigError as exc:
        print(f"configuration_error={exc}")
        return ExitCode.CONFIGURATION
    except Exception as exc:
        print(f"unexpected_error={type(exc).__name__}: {exc}")
        return ExitCode.UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(run_main())
```

Before starting Chrome, `build_pipeline` must call a read-only schema probe for `public_picks` and `publish_pick_batch` when not in dry-run mode. A 404 or missing RPC raises `ConfigError("secure Supabase scraper migration is not applied")`.

- [ ] **Step 4: Run CLI and full Python tests**

Run: `python -m pytest tests/test_scraper_cli.py -q && python -m pytest tests -q`

Expected: CLI tests and the complete Python suite pass.

- [ ] **Step 5: Commit**

```bash
git add backend/scraper.py backend/pick_publisher.py tests/test_scraper_cli.py
git commit -m "feat: add safe scraper dry run and exit codes"
```

### Task 7: Correct the scheduled workflow and downstream posting

**Files:**
- Modify: `.github/workflows/scraper.yml`
- Create: `tests/test_scraper_workflow.py`

- [ ] **Step 1: Write failing workflow source tests**

```python
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scraper.yml"


def test_workflow_uses_service_role_and_prevents_overlap():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}" in text
    assert "SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}" not in text
    assert "concurrency:" in text
    assert "cancel-in-progress: false" in text


def test_scraper_waits_for_verification_and_social_requires_success():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "needs: verificar" in text
    assert "needs.verificar.result == 'success' || needs.verificar.result == 'skipped'" in text
    social = text[text.index("Auto-Post Social Media Banner"):]
    assert "if: success()" in social
    assert "if: always()" not in social
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_scraper_workflow.py -q`

Expected: FAIL because the workflow still uses `SUPABASE_KEY`, lacks `needs`, and posts social content with `always()`.

- [ ] **Step 3: Update the workflow control flow**

Add at workflow level:

```yaml
concurrency:
  group: rey-taco-scraper
  cancel-in-progress: false
```

Use this scraper job boundary:

```yaml
  scraper:
    needs: verificar
    if: >-
      always() &&
      (needs.verificar.result == 'success' || needs.verificar.result == 'skipped')
    runs-on: ubuntu-latest
    timeout-minutes: 30
```

Pass the privileged key to both backend jobs:

```yaml
SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
```

Change the social step condition to:

```yaml
if: success()
```

- [ ] **Step 4: Run workflow tests and commit**

Run: `python -m pytest tests/test_scraper_workflow.py -q`

Expected: `2 passed`.

```bash
git add .github/workflows/scraper.yml tests/test_scraper_workflow.py
git commit -m "ci: serialize scraper after result verification"
```

### Task 8: Document and verify the controlled rollout

**Files:**
- Modify: `docs/operations/security-and-payments.md`
- Modify: `README.md`

- [ ] **Step 1: Add exact operator commands**

Document these commands and state that none of them should be run until the service-role secret is configured:

```powershell
supabase db push
python backend/scraper.py --dry-run
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
deno test --allow-env supabase/functions/*/index.test.ts
```

Document the controlled production check: one manual workflow dispatch, confirm one active batch/one public pick, verify admin/VIP/free delivery statuses, then observe two scheduled runs.

- [ ] **Step 2: Run the complete reliability verification**

Run:

```powershell
python -m pyflakes backend/scraper.py backend/scraper_config.py backend/pick_publisher.py backend/telegram_publisher.py
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
deno test --allow-env supabase/functions/*/index.test.ts
git diff --check
```

Expected: every command exits `0`; Python, frontend, and Deno report zero failed tests; no diff-check warnings.

- [ ] **Step 3: Run a non-mutating smoke test**

Run: `python backend/scraper.py --dry-run`

Expected: the run reports collected events and candidate counts, reports `dry_run=true`, performs no Supabase write and no Telegram delivery, and exits `0` only when verified candidates exist.

- [ ] **Step 4: Commit documentation**

```bash
git add docs/operations/security-and-payments.md README.md
git commit -m "docs: add controlled scraper rollout"
```
