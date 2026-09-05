# Rey Taco: R2, Remotion, Mini App y medición — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir almacenamiento multimedia durable, video vertical reproducible, Mini App de Telegram y medición opcional sin cambiar el scraper, la selección de picks, la separación Free/VIP, el historial ni la publicación textual existente.

**Architecture:** La fuente autoritativa seguirá siendo Supabase. R2 será un adaptador opt-in de objetos; Remotion recibirá un paquete JSON ya persistido y permanecerá desactivado en producción al principio; la Mini App usará una Edge Function de solo lectura que valida `initData` antes de consultar membresía. La ruta Supabase/FFmpeg actual permanecerá como fallback explícito.

**Tech Stack:** Python 3, pytest, Supabase/Postgres, Cloudflare R2 mediante API S3-compatible, Vite + TypeScript + Vitest, Deno Edge Functions, React + Remotion + FFmpeg/FFprobe, Plausible opcional.

---

## Guardas de compatibilidad obligatorias

Antes de cada tarea, conservar estas invariantes:

1. `.github/workflows/collector.yml`, `backend/scraper.py`, `backend/pick_selection.py`, `backend/pick_publisher.py`, `backend/telegram_publisher.py` y `backend/telegram_dispatcher.py` no se modifican en esta entrega.
2. `backend/vertical_repository.py` y `backend/reel_renderer.py` siguen siendo la ruta por defecto mientras no estén configuradas las banderas nuevas.
3. Los valores iniciales son `MEDIA_STORAGE_BACKEND=supabase`, `REMOTION_ENABLED=false` y Plausible desactivado si falta `VITE_PLAUSIBLE_DOMAIN`.
4. Ningún test, preview, build o workflow puede llamar a Meta, Telegram, Cloudflare R2 o una cuenta real de Supabase. Los dobles de prueba deben fallar si reciben secretos reales o URLs de publicación.
5. Los fallos de R2, Remotion, Mini App o analítica no cambian picks ni bloquean Telegram textual.
6. No se imprimen tokens, `initData`, IDs de Telegram, `file_id`, correos, cuotas, IDs de picks ni URLs privadas en logs, snapshots o nombres de objetos.

## Mapa de archivos

### Archivos nuevos

- `backend/media_store.py`: protocolo inmutable del almacenamiento de objetos.
- `backend/r2_media_store.py`: implementación Cloudflare R2, fail-closed y sin creación automática de bucket.
- `backend/supabase_media_store.py`: adaptador del bucket Supabase existente para el mismo protocolo, usado por default.
- `backend/media_storage.py`: selección de backend con Supabase como default.
- `backend/media_object_repository.py`: registro de objetos aprobados en Supabase.
- `backend/remotion_input.py`: construcción y validación del `ReelInput` desde datos persistidos.
- `backend/remotion_renderer.py`: puente opcional entre Python y el paquete Remotion, con fallback explícito a FFmpeg.
- `tests/test_media_store.py`, `tests/test_r2_media_store.py`, `tests/test_media_object_repository.py`, `tests/test_remotion_input.py`: contratos y límites.
- `tests/test_supabase_media_store.py`, `tests/test_remotion_renderer.py`: fallback y selección de backend.
- `supabase/migrations/20260906120000_media_objects.sql`: ledger de objetos, sin reemplazar `vertical_media_delivery`.
- `social-video/package.json`, `social-video/tsconfig.json`, `social-video/vitest.config.ts` y `social-video/src/*`: paquete independiente de Remotion.
- `social-video/src/contracts.ts`, `social-video/src/Root.tsx`, `social-video/src/cli.ts`, `social-video/src/ReyTacoResultsReel.tsx`, `social-video/src/ReyTacoTeaserReel.tsx`: contrato, composición, entrada CLI y dos variantes iniciales.
- `social-video/src/contracts.test.ts`, `social-video/src/Root.test.tsx`: pruebas del paquete de video.
- `frontend/src/app/telegram.ts`, `frontend/src/app/telegram.test.ts`: estado, DTO y render de la Mini App.
- `supabase/functions/telegram-mini-app/index.ts`, `supabase/functions/telegram-mini-app/index.test.ts`: validación de identidad y DTO de solo lectura.
- `docs/operations/media-rollout.md`: procedimiento de canario, rollback y revisión de recibos.

### Archivos modificados de forma controlada

- `backend/requirements.txt`: dependencia S3 mínima para el adaptador R2.
- `backend/.env.example` y `.env.example`: nombres de configuración no secreta y banderas con defaults seguros.
- `frontend/.env.example`: `VITE_PLAUSIBLE_DOMAIN` opcional y URL de Mini App.
- `frontend/src/services/analytics.ts`: transportador Plausible opcional conservando `dataLayer`.
- `frontend/src/app/template.ts`, `frontend/src/main.ts`, `frontend/src/style.css`: nueva ruta `/telegram` y navegación, sin eliminar la página existente.
- `frontend/package.json`: ninguna dependencia de producción innecesaria; solo se modifica si el SDK de Telegram se carga por URL en lugar de paquete.

## Task 1: Baseline, contratos y banderas seguras

**Files:**
- Create: `backend/media_store.py`
- Create: `backend/media_storage.py`
- Create: `tests/test_media_store.py`
- Modify: `backend/.env.example`
- Modify: `.env.example`
- Modify: `frontend/.env.example`

- [ ] **Step 1: Escribir el test de contrato que fija el backend actual como default**

```python
from backend.media_storage import media_storage_backend, remotion_enabled


def test_storage_backend_defaults_to_supabase(monkeypatch):
    monkeypatch.delenv("MEDIA_STORAGE_BACKEND", raising=False)
    assert media_storage_backend() == "supabase"


def test_unknown_storage_backend_fails_closed(monkeypatch):
    monkeypatch.setenv("MEDIA_STORAGE_BACKEND", "unknown")
    try:
        media_storage_backend()
    except RuntimeError as error:
        assert str(error) == "unsupported media storage backend"
    else:
        raise AssertionError("unsupported backend must fail")


def test_remotion_is_disabled_without_explicit_flag(monkeypatch):
    monkeypatch.delenv("REMOTION_ENABLED", raising=False)
    assert remotion_enabled() is False
```

- [ ] **Step 2: Ejecutar el test nuevo y verificar que falla por símbolos ausentes**

Run: `python -m pytest tests/test_media_store.py -q`

Expected: FAIL con errores de importación para `media_storage_backend` y `remotion_enabled`.

- [ ] **Step 3: Implementar el protocolo y la lectura de configuración**

```python
# backend/media_store.py
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaObject:
    object_key: str
    content_type: str
    digest: str
    size_bytes: int
    public: bool


class MediaStore(Protocol):
    def put(
        self,
        object_key: str,
        payload: bytes,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> MediaObject: ...

    def get(self, object_key: str) -> bytes: ...

    def temporary_delivery_url(self, object_key: str, expires_in: int) -> str: ...

    def delete_temporary(self, object_key: str) -> None: ...

    def exists(self, object_key: str) -> bool: ...
```

```python
# backend/media_storage.py
from __future__ import annotations

import os


def media_storage_backend() -> str:
    value = os.getenv("MEDIA_STORAGE_BACKEND", "supabase").strip().lower()
    if value not in {"supabase", "r2"}:
        raise RuntimeError("unsupported media storage backend")
    return value


def remotion_enabled() -> bool:
    return os.getenv("REMOTION_ENABLED", "false").strip().lower() == "true"
```

- [ ] **Step 4: Ejecutar el test y conservar los defaults seguros**

Run: `python -m pytest tests/test_media_store.py -q`

Expected: PASS.

- [ ] **Step 5: Documentar solo nombres de variables, nunca sus valores**

Añadir a los tres archivos `.env.example` estas líneas, sin tokens ni contraseñas:

```dotenv
MEDIA_STORAGE_BACKEND=supabase
REMOTION_ENABLED=false
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=
R2_PUBLIC_BASE_URL=
VITE_PLAUSIBLE_DOMAIN=
VITE_TELEGRAM_MINI_APP_PATH=/telegram
```

- [ ] **Step 6: Ejecutar la regresión mínima y hacer commit aislado**

Run: `python -m pytest tests/test_media_store.py tests/test_vertical_repository.py tests/test_reel_renderer.py -q`

Expected: todos los tests PASS y ningún cambio en snapshots de la ruta existente.

Commit: `git add backend/media_store.py backend/media_storage.py tests/test_media_store.py backend/.env.example .env.example frontend/.env.example; git commit -m "feat: add safe media storage contracts"`

## Task 2: Adaptador R2 y ledger independiente

**Files:**
- Create: `backend/r2_media_store.py`
- Create: `backend/supabase_media_store.py`
- Create: `backend/media_object_repository.py`
- Create: `tests/test_r2_media_store.py`
- Create: `tests/test_supabase_media_store.py`
- Create: `tests/test_media_object_repository.py`
- Create: `supabase/migrations/20260906120000_media_objects.sql`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Escribir pruebas que impidan fugas y operaciones destructivas**

```python
import pytest
from backend.r2_media_store import R2MediaStore, derived_object_key, evidence_object_key


def test_object_keys_are_content_addressed():
    assert derived_object_key("2026-09-05", "daily_results_reel", "a" * 64, "mp4") == (
        "derived/2026-09-05/daily_results_reel/" + "a" * 64 + ".mp4"
    )
    assert evidence_object_key("2026-09-05", "b" * 64, "jpg") == (
        "evidence/2026-09-05/" + "b" * 64 + ".jpg"
    )


def test_r2_requires_complete_configuration(monkeypatch):
    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="R2 configuration is incomplete"):
        R2MediaStore.from_environment(client_factory=lambda **_: object())


def test_delete_temporary_rejects_approved_derived_objects(fake_r2):
    store = R2MediaStore("account", "key", "secret", "bucket", client=fake_r2)
    with pytest.raises(ValueError, match="temporary object key is invalid"):
        store.delete_temporary("derived/2026-09-05/daily_results_reel/" + "c" * 64 + ".mp4")


def test_put_returns_digest_without_logging_payload(fake_r2, caplog):
    store = R2MediaStore("account", "key", "secret", "bucket", client=fake_r2)
    result = store.put("derived/2026-09-05/reel/" + "d" * 64 + ".mp4", b"bytes", "video/mp4", {})
    assert result.digest == "d" * 64
    assert "bytes" not in caplog.text
    assert "secret" not in caplog.text


class FakeR2Client:
    def put_object(self, **kwargs):
        return {"ETag": '"test"'}

    def head_object(self, **kwargs):
        return {"ContentLength": 5, "ContentType": "video/mp4"}

    def get_object(self, **kwargs):
        return {"Body": type("Body", (), {"read": lambda self: b"bytes"})()}

    def generate_presigned_url(self, **kwargs):
        return "https://r2.invalid/temporary"

    def delete_object(self, **kwargs):
        return {}


@pytest.fixture
def fake_r2():
    return FakeR2Client()
```

- [ ] **Step 2: Ejecutar las pruebas para confirmar que el adaptador todavía no existe**

Run: `python -m pytest tests/test_r2_media_store.py -q`

Expected: FAIL por importación de `R2MediaStore` y las funciones de clave.

- [ ] **Step 3: Implementar la validación de claves y configuración**

La implementación debe:

```python
def derived_object_key(portfolio_date: str, content_kind: str, digest: str, extension: str) -> str:
    # Validar fecha ISO, kind de una lista fija, digest hexadecimal de 64 caracteres
    # y extensión alfanumérica de 1-5 caracteres antes de interpolar.
    return f"derived/{portfolio_date}/{content_kind}/{digest}.{extension}"


def evidence_object_key(received_date: str, digest: str, extension: str) -> str:
    # Usar la misma validación de fecha/digest/extensión y nunca texto libre.
    return f"evidence/{received_date}/{digest}.{extension}"
```

`R2MediaStore` debe crear un cliente S3 únicamente con configuración completa, usar el endpoint `https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com`, calcular el digest de los bytes, verificar que coincide con el digest de una clave `derived/` o `evidence/`, imponer MIME permitido (`image/jpeg`, `video/mp4`), limitar historias a 5 MiB y reels a 50 MiB, y no imprimir argumentos del cliente.

- [ ] **Step 4: Implementar operaciones S3 con errores genéricos y URL temporal**

El método `temporary_delivery_url` solo acepta una clave validada y un TTL entero entre 60 y 900 segundos. `delete_temporary` solo acepta claves bajo `tmp/` y elimina con best effort desde el orquestador, nunca como limpieza automática de `derived/` o `evidence/`. `exists` convierte únicamente un `404` en `False`; otros errores se propagan como `RuntimeError("R2 existence check failed")`.

- [ ] **Step 5: Ejecutar pruebas del adaptador**

Run: `python -m pytest tests/test_r2_media_store.py -q`

Expected: PASS, incluidos los casos de configuración incompleta, MIME inválido, clave manipulada, TTL fuera de límites y eliminación de objeto aprobado.

- [ ] **Step 6: Escribir el ledger SQL antes de tocar el repositorio**

La migración debe crear una tabla `media_objects` con:

```sql
create table public.media_objects (
  object_key text primary key,
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  content_kind text not null,
  content_type text not null check (content_type in ('image/jpeg', 'video/mp4')),
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 52428800),
  portfolio_date date not null,
  source_batch_id uuid,
  storage_backend text not null check (storage_backend in ('supabase', 'r2')),
  visibility text not null check (visibility in ('private', 'public')),
  state text not null check (state in ('approved', 'temporary', 'failed')),
  created_at timestamptz not null default now(),
  approved_at timestamptz,
  unique (digest, content_kind, portfolio_date)
);

alter table public.media_objects enable row level security;
create policy media_objects_public_derived on public.media_objects
  for select using (visibility = 'public' and state = 'approved');
```

La migración no modifica ni borra filas de `vertical_media_delivery`, `picks` o `result_reports` y debe incluir una consulta de verificación que compruebe las restricciones y RLS.

- [ ] **Step 7: Añadir el repositorio de ledger con upsert idempotente**

`MediaObjectRepository.register_approved` recibe un `MediaObject`, fecha, `content_kind`, `source_batch_id` opcional y backend; valida la identidad antes de ejecutar un upsert. Devuelve el mismo `object_key` cuando el registro ya existe con digest y tipo idénticos; rechaza conflictos con `RuntimeError("media object identity conflict")`. No acepta ni registra secretos.

- [ ] **Step 8: Probar el ledger y la migración sin conexión real**

Run: `python -m pytest tests/test_media_object_repository.py -q`

Expected: PASS con dobles que cubran primer insert, reintento idempotente, conflicto de digest, estado no aprobado y payload que contiene un secreto; el último debe ser rechazado y no aparecer en logs.

- [ ] **Step 9: Mantener Supabase como adaptador default y seleccionar R2 solo por configuración**

Implementar `SupabaseMediaStore` sobre el cliente/bucket que ya usa `SupabaseVerticalRepository` y añadir a `backend/media_storage.py` una función `build_media_store()` que devuelva `SupabaseMediaStore` por default y `R2MediaStore` solo cuando `MEDIA_STORAGE_BACKEND=r2`. El selector tendrá esta forma, con clientes inyectables para pruebas:

```python
def build_media_store(*, supabase_client, supabase_url: str, service_role_key: str) -> MediaStore:
    if media_storage_backend() == "r2":
        return R2MediaStore.from_environment()
    return SupabaseMediaStore(
        client=supabase_client,
        supabase_url=supabase_url,
        service_role_key=service_role_key,
    )
```

No se cambiarán `SupabaseVerticalRepository.upload_story`, `upload_reel`, `claim` ni `complete`; el publisher actual seguirá utilizando su clase existente hasta que una integración posterior cambie explícitamente el backend. Si R2 falla durante una prueba o un canario, el caller conserva la ruta Supabase y Telegram textual.

- [ ] **Step 10: Ejecutar regresión Python y commit**

Run: `python -m pytest tests/test_r2_media_store.py tests/test_supabase_media_store.py tests/test_media_object_repository.py tests/test_vertical_repository.py tests/test_vertical_publisher.py tests/test_reel_renderer.py -q`

Expected: PASS.

Commit: `git add backend/r2_media_store.py backend/supabase_media_store.py backend/media_object_repository.py backend/media_store.py backend/media_storage.py backend/requirements.txt tests/test_r2_media_store.py tests/test_supabase_media_store.py tests/test_media_object_repository.py supabase/migrations/20260906120000_media_objects.sql; git commit -m "feat: add opt-in R2 media ledger"`

## Task 3: Remotion independiente con fallback FFmpeg

**Files:**
- Create: `backend/remotion_input.py`
- Create: `backend/remotion_renderer.py`
- Create: `tests/test_remotion_input.py`
- Create: `tests/test_remotion_renderer.py`
- Create: `social-video/package.json`
- Create: `social-video/tsconfig.json`
- Create: `social-video/vitest.config.ts`
- Create: `social-video/src/contracts.ts`
- Create: `social-video/src/Root.tsx`
- Create: `social-video/src/ReyTacoResultsReel.tsx`
- Create: `social-video/src/ReyTacoTeaserReel.tsx`
- Create: `social-video/src/cli.ts`
- Create: `social-video/src/contracts.test.ts`
- Create: `social-video/src/Root.test.tsx`

- [ ] **Step 1: Escribir el test Python del paquete de entrada**

```python
from datetime import date
import pytest
from backend.remotion_input import ReelInput, build_reel_input


def test_reel_input_contains_only_persisted_public_data():
    value = build_reel_input(
        batch_id="11111111-1111-1111-1111-111111111111",
        portfolio_date=date(2026, 9, 5),
        picks=[{"partido": "A vs B", "pick": "A", "cuota": "1.80"}],
        template_digest="e" * 64,
    )
    assert isinstance(value, ReelInput)
    assert value.picks[0]["pick"] == "A"
    assert "token" not in value.to_json().lower()


def test_reel_input_rejects_private_or_unbounded_fields():
    with pytest.raises(ValueError, match="reel input contains forbidden field"):
        build_reel_input(
            batch_id="11111111-1111-1111-1111-111111111111",
            portfolio_date=date(2026, 9, 5),
            picks=[{"partido": "A", "pick": "A", "cuota": "1.80", "telegram_id": "1"}],
            template_digest="e" * 64,
        )
```

- [ ] **Step 2: Ejecutar el test para confirmar el contrato ausente**

Run: `python -m pytest tests/test_remotion_input.py -q`

Expected: FAIL por importación de `backend.remotion_input`.

- [ ] **Step 3: Implementar `ReelInput` y el constructor seguro**

El dataclass debe tener exactamente `batch_id`, `portfolio_date`, `kind`, `picks`, `editorial_text`, `template_digest`, `approved_image_refs`; validar UUID/fecha/digest, limitar de 1 a 6 picks y aceptar únicamente campos `partido`, `pick`, `cuota`, `categoria`, `estado`, sin nombres premium, tokens, URLs permanentes ni IDs personales. `to_json()` debe ordenar claves y no incorporar horas locales ambiguas.

- [ ] **Step 4: Probar el contrato Python**

Run: `python -m pytest tests/test_remotion_input.py -q`

Expected: PASS.

- [ ] **Step 5: Crear el paquete Node aislado y sus scripts**

`social-video/package.json` debe declarar scripts `test`, `typecheck`, `preview` y `render`, dependencias `remotion`, `@remotion/cli`, `react` y `react-dom`, y no importar Supabase, Telegram, Meta, Playdoit ni SDKs de publicación. El script `render` debe recibir un JSON local y escribir un MP4 solo dentro del directorio indicado por la CLI.

- [ ] **Step 6: Escribir las pruebas TypeScript del contrato**

```typescript
import { describe, expect, it } from 'vitest';
import { parseReelInput } from './contracts';

describe('ReelInput', () => {
  it('accepts a bounded persisted payload', () => {
    expect(parseReelInput({
      batch_id: '11111111-1111-1111-1111-111111111111',
      portfolio_date: '2026-09-05',
      kind: 'results',
      picks: [{ partido: 'A vs B', pick: 'A', cuota: '1.80', estado: 'ganado' }],
      editorial_text: 'Resultados verificados',
      template_digest: 'f'.repeat(64),
      approved_image_refs: [],
    }).picks).toHaveLength(1);
  });

  it('rejects hidden identity and unbounded text', () => {
    expect(() => parseReelInput({ telegram_id: '1' })).toThrow('invalid reel input');
    expect(() => parseReelInput({ editorial_text: 'x'.repeat(1001) })).toThrow('invalid reel input');
  });
});
```

- [ ] **Step 7: Implementar composiciones deterministas**

`Root.tsx` registrará dos composiciones de 1080×1920 a 30 FPS: `ReyTacoResultsReel` y `ReyTacoTeaserReel`. Cada una usará entre 240 y 450 frames, tres a cinco escenas, colores y tipografía locales, texto escapado desde `ReelInput`, CTA `reytacopicks.com`, `18+` y juego responsable. No incluirá música, fuentes remotas o datos que no estén en el JSON. La composición no hace fetch ni crea picks.

- [ ] **Step 8: Implementar la CLI y validación de salida**

`cli.ts` debe rechazar archivos fuera del directorio de trabajo, validar el JSON antes de renderizar, llamar a Remotion con `--codec=h264`, `--pixel-format=yuv420p`, `--frames=...`, `--every=1` y `--pro` solo cuando se solicite explícitamente, y ejecutar FFprobe después. Si el contrato falla, el proceso termina con código 2 sin crear un archivo parcial.

- [ ] **Step 9: Probar el paquete sin publicación**

Run: `npm --prefix social-video install --ignore-scripts; npm --prefix social-video run test; npm --prefix social-video run typecheck`

Expected: PASS; no llamadas de red ni archivos fuera de `social-video/.tmp`.

- [ ] **Step 10: Mantener FFmpeg como fallback y añadir bandera de integración**

Crear `backend/remotion_renderer.py` como puente separado. Solo podrá invocar el CLI cuando `REMOTION_ENABLED=true`; ante error de proceso, contrato o FFprobe, debe seleccionar el `ReelRenderer` existente y registrar un error seguro. Con el valor por defecto `false`, ninguna ruta importa Remotion y las pruebas existentes de `backend/reel_renderer.py` deben producir exactamente la misma validación H.264/1080×1920/yuv420p/8–15 segundos. El puente debe exponer una función inyectable con esta firma:

```python
from collections.abc import Sequence


def render_with_fallback(
    package: ReelInput,
    *,
    remotion_command: list[str],
    fallback_renderer: ReelRenderer,
    fallback_frames: Sequence[bytes],
    enabled: bool,
) -> bytes:
    if not enabled:
        return fallback_renderer.render(fallback_frames)
    try:
        return _run_remotion_and_validate(package, remotion_command)
    except (OSError, RuntimeError, ValueError):
        return fallback_renderer.render(fallback_frames)
```

- [ ] **Step 11: Ejecutar toda la regresión y commit**

Run: `python -m pytest tests/test_remotion_input.py tests/test_reel_renderer.py tests/test_vertical_workflows.py -q; npm --prefix social-video run test; npm --prefix social-video run typecheck`

Expected: PASS.

Commit: `git add backend/remotion_input.py backend/remotion_renderer.py tests/test_remotion_input.py tests/test_remotion_renderer.py social-video; git commit -m "feat: add disabled-by-default Remotion reels"`

## Task 4: Mini App de Telegram de solo lectura

**Files:**
- Create: `frontend/src/app/telegram.ts`
- Create: `frontend/src/app/telegram.test.ts`
- Create: `supabase/functions/telegram-mini-app/index.ts`
- Create: `supabase/functions/telegram-mini-app/index.test.ts`
- Modify: `frontend/src/app/template.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/style.css`
- Modify: `frontend/.env.example`

- [ ] **Step 1: Escribir pruebas del DTO frontend y de los cuatro estados**

```typescript
import { describe, expect, it } from 'vitest';
import { miniAppWindowState, publicMiniAppDto } from './telegram';

describe('Telegram Mini App', () => {
  it('keeps four visible windows including empty ones', () => {
    const dto = publicMiniAppDto({ date: '2026-09-05', windows: [] });
    expect(dto.windows).toHaveLength(4);
    expect(dto.windows.every(window => window.status === 'Sin selección')).toBe(true);
  });

  it('uses the same CDMX boundaries as the existing time board', () => {
    expect(miniAppWindowState('2026-09-05T17:00:00.000Z', '2026-09-05', 1)).toBe('En curso');
    expect(miniAppWindowState('2026-09-05T23:59:00.000Z', '2026-09-05', 0)).toBe('Cerrado');
  });
});
```

- [ ] **Step 2: Ejecutar la prueba y comprobar que el módulo no existe**

Run: `npm --prefix frontend test -- src/app/telegram.test.ts`

Expected: FAIL por importación de `./telegram`.

- [ ] **Step 3: Definir el DTO mínimo y la lógica de presentación**

`telegram.ts` debe exportar tipos `MiniAppWindow`, `MiniAppPick`, `MiniAppDto`, `miniAppWindowState`, `publicMiniAppDto`, `renderTelegramMiniApp` y `initTelegramMiniApp`. Los cuatro bloques deben permanecer visibles; público recibe solo `partido`, `pick`, `cuota`, `categoria`, `estado` y `source_starts_at`; no vinculado recibe solo `vip_count` agregado y CTA. `initTelegramMiniApp` debe llamar `Telegram.WebApp.ready()` solo si existe `window.Telegram?.WebApp`, y debe funcionar sin ese SDK.

- [ ] **Step 4: Añadir la ruta `/telegram` sin reemplazar la web existente**

En `template.ts`, agregar un contenedor `#telegram-mini-app` y un enlace de entrada. En `main.ts`, detectar `window.location.pathname === '/telegram'` y montar la vista de Mini App, dejando intacto el montaje actual para `/`. Añadir CSS scoped bajo `.telegram-app` para la opción C refinada: encabezado, ventana actual, cuatro tarjetas, bloque VIP, historial y CTA. No eliminar métricas, anuncios, checkout ni navegación existentes.

- [ ] **Step 5: Probar el render y hacer build frontend**

Run: `npm --prefix frontend test -- src/app/telegram.test.ts; npm --prefix frontend run typecheck; npm --prefix frontend run build`

Expected: PASS y build generado sin cambiar el contenido de la página raíz fuera de la ruta nueva.

- [ ] **Step 6: Escribir pruebas criptográficas de la Edge Function**

```typescript
import { describe, expect, it } from 'vitest';
import { buildTelegramDataCheckString, verifyTelegramInitData } from './index';

describe('telegram initData', () => {
  it('sorts fields and ignores hash while building the check string', () => {
    expect(buildTelegramDataCheckString('z=2&auth_date=10&hash=ignored&a=1')).toBe('a=1\nauth_date=10\nz=2');
  });

  it('rejects stale or tampered payloads', async () => {
    await expect(verifyTelegramInitData('auth_date=1&hash=bad', 'bot-secret', 1000)).rejects.toThrow('invalid telegram init data');
  });
});
```

- [ ] **Step 7: Implementar verificación HMAC fail-closed**

La función debe calcular la clave secreta con HMAC-SHA256 usando `WebAppData` y el token del bot, ordenar todos los pares salvo `hash`, comparar el hash en tiempo constante, exigir `auth_date` entero dentro de una hora y extraer el `id` del JSON `user` verificado. Nunca debe leer `initDataUnsafe` como autoridad, registrar el cuerpo, devolver el token ni aceptar una solicitud sin `Content-Type: application/json` y `initData` string.

- [ ] **Step 8: Implementar el DTO de solo lectura con service role aislado**

Después de validar identidad, la función consultará únicamente la vista/queries existentes para picks públicos, ventanas, historial permitido, perfil vinculado y membresía activa. Un visitante anónimo solo obtiene datos públicos. Un usuario VIP recibe los detalles premium solo después de la comprobación server-side. No habrá métodos `POST` de edición, checkout, administración, resultados o borrado; respuestas de error serán genéricas y CORS permitirá únicamente el dominio configurado más `https://telegram.org` cuando aplique.

- [ ] **Step 9: Probar válido, vencido, manipulado, no vinculado y VIP**

Run: `npm --prefix supabase/functions/telegram-mini-app test` si existe un runner local; de lo contrario `deno test --allow-env supabase/functions/telegram-mini-app/index.test.ts`.

Expected: PASS, ningún caso imprime `initData`, `telegram_id`, bot secret o filas premium en el caso no vinculado.

- [ ] **Step 10: Añadir deep link sin cambiar el bot textual**

El CTA construirá `https://t.me/<VITE_TELEGRAM_BOT_USERNAME>?startapp=telegram` con `encodeURIComponent`, y el bot conservará sus enlaces actuales. La Mini App solo consume el parámetro `startapp` como vista; no lo usa como autorización.

- [ ] **Step 11: Ejecutar regresión frontend/Supabase y commit**

Run: `npm --prefix frontend test; npm --prefix frontend run typecheck; npm --prefix frontend run build; git diff --check`

Expected: PASS; las pruebas existentes de picks, historial, membresía, checkout y anuncios permanecen PASS.

Commit: `git add frontend/src/app/telegram.ts frontend/src/app/telegram.test.ts frontend/src/app/template.ts frontend/src/main.ts frontend/src/style.css supabase/functions/telegram-mini-app; git commit -m "feat: add read-only Telegram mini app"`

## Task 5: Plausible opcional y medición de conversión

**Files:**
- Create or modify: `frontend/src/services/analytics.ts`
- Modify: `frontend/src/services/analytics.test.ts`
- Modify: `frontend/src/app/telegram.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/.env.example`

- [ ] **Step 1: Escribir pruebas del allowlist y del fallback**

```typescript
import { describe, expect, it, vi } from 'vitest';
import { trackConversion, resetAnalyticsForTests } from './analytics';

describe('analytics transport', () => {
  it('keeps dataLayer and sends no network request without a domain', () => {
    resetAnalyticsForTests();
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(new Response());
    delete (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env.VITE_PLAUSIBLE_DOMAIN;
    trackConversion('miniapp_opened', { surface: 'telegram_miniapp', window_slot: '11am' });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect((window as Window & { dataLayer?: unknown[] }).dataLayer).toEqual([
      { event: 'miniapp_opened' },
    ]);
    fetchSpy.mockRestore();
  });

  it('drops identifiers and free-form values from plausible properties', () => {
    resetAnalyticsForTests();
    trackConversion('free_pick_viewed', {
      surface: 'web', window_slot: '11pm', pick_id: 'secret', partido: 'A vs B', cuota: '1.8',
    });
    // La petición solo podrá contener surface y window_slot.
  });
});
```

- [ ] **Step 2: Ejecutar las pruebas para capturar el comportamiento actual**

Run: `npm --prefix frontend test -- src/services/analytics.test.ts`

Expected: el test nuevo falla hasta que exista el transportador opcional y el reset de test.

- [ ] **Step 3: Implementar el transportador sin quitar `dataLayer`**

Mantener los eventos actuales y ampliar el tipo a `miniapp_opened`. `trackConversion(event, properties)` debe deduplicar por evento/superficie/ventana, añadir siempre el evento a `dataLayer`, y solo llamar `window.plausible` o `fetch('/api/event')` cuando `VITE_PLAUSIBLE_DOMAIN` está configurado. El objeto permitido debe filtrarse a `{surface: 'web'|'telegram_miniapp', window_slot: '12am'|'6am'|'12pm'|'6pm'}`. Quedan prohibidos correo, Telegram ID, pick ID, partido, cuota, token, IP y texto libre.

- [ ] **Step 4: Cargar Plausible de manera condicional**

Añadir el script solo cuando el dominio sea una cadena no vacía y válida; `onerror` debe dejar la aplicación funcionando. Si falta el dominio, no debe existir solicitud externa. `trackWhenVisible` conservará su observador y usará el mismo allowlist.

- [ ] **Step 5: Conectar la Mini App y CTAs existentes**

Emitir `miniapp_opened` una vez por superficie, `free_pick_viewed`, `vip_offer_viewed`, `telegram_clicked`, `checkout_started` y `subscription_confirmed` con propiedades agregadas únicamente. No cambiar la semántica ni eliminar los eventos ya usados por la web.

- [ ] **Step 6: Ejecutar pruebas y commit**

Run: `npm --prefix frontend test; npm --prefix frontend run typecheck; npm --prefix frontend run build; git diff --check`

Expected: PASS; sin dominio no hay solicitudes; con un stub de Plausible solo se envían propiedades permitidas.

Commit: `git add frontend/src/services/analytics.ts frontend/src/services/analytics.test.ts frontend/src/app/telegram.ts frontend/src/main.ts frontend/.env.example; git commit -m "feat: add privacy-safe optional analytics"`

## Task 6: Quiniela semanal y contenido AdSense como entrega separada

**Files:**
- Create: `docs/superpowers/specs/2026-09-06-quiniela-adsense-design.md`
- Create: `docs/superpowers/plans/2026-09-06-quiniela-adsense.md`
- Modify: ninguno de los módulos de picks en esta fase.

- [ ] **Step 1: No añadir código de quiniela ni páginas de relleno durante el MVP multimedia**

La aceptación de esta tarea es que los documentos definan, sin implementación prematura, corte semanal, una entrada por cuenta, fuente de resultados, desempate, ledger idempotente, premio de una semana VIP, autoría, método, fuentes, límites, FAQ, resultados, privacidad, términos y juego responsable. No se crearán afirmaciones de ganancias, contenido repetitivo ni una quiniela que alimente el scraper.

- [ ] **Step 2: Verificar independencia**

Run: `rg -n "quiniela|adsense|ad sense" backend frontend supabase/functions .github/workflows`

Expected: no cambios de código en esta fase que conecten quiniela, AdSense o publicidad con selección, ranking, membresía o publicación de picks.

- [ ] **Step 3: Commit documental independiente**

Commit: `git add docs/superpowers/specs/2026-09-06-quiniela-adsense-design.md docs/superpowers/plans/2026-09-06-quiniela-adsense.md; git commit -m "docs: separate quiniela and adsense scope"`

## Task 7: Integración, canario y verificación de no regresión

**Files:**
- Create: `docs/operations/media-rollout.md`
- Modify: `README.md` solo para enlazar el procedimiento, sin cambiar instrucciones del scraper.

- [ ] **Step 1: Documentar la configuración inicial segura**

El procedimiento debe fijar:

```dotenv
MEDIA_STORAGE_BACKEND=supabase
REMOTION_ENABLED=false
VITE_PLAUSIBLE_DOMAIN=
```

R2 solo pasa a `r2` después de verificar manualmente en Cloudflare el bucket y dominio exactos. Los valores secretos se introducen únicamente en el gestor de secretos; nunca en Git, issues, logs, capturas o mensajes.

- [ ] **Step 2: Crear preview local sin red real**

Run: `python -m pytest tests/test_media_store.py tests/test_r2_media_store.py tests/test_remotion_input.py tests/test_vertical_workflows.py -q`

Expected: PASS; el doble de almacenamiento no recibe credenciales reales y el publisher no recibe una llamada de publicación.

- [ ] **Step 3: Validar el frontend completo**

Run: `npm --prefix frontend test; npm --prefix frontend run typecheck; npm --prefix frontend run build`

Expected: PASS; la ruta raíz y la ruta `/telegram` compilan juntas.

- [ ] **Step 4: Validar el paquete de video completo**

Run: `npm --prefix social-video test; npm --prefix social-video run typecheck`

Expected: PASS; el paquete no contiene imports de Supabase, Telegram, Meta, Playdoit ni llamadas de red.

- [ ] **Step 5: Ejecutar la suite global y revisar el diff**

Run: `python -m pytest; npm --prefix frontend test; npm --prefix frontend run typecheck; npm --prefix frontend run build; npm --prefix social-video test; npm --prefix social-video run typecheck; git diff --check`

Expected: PASS en todas las suites y `git diff --check` sin salida.

- [ ] **Step 6: Hacer una revisión de regresión de archivos sensibles**

Run: `git diff -- backend/scraper.py backend/pick_selection.py backend/pick_publisher.py backend/telegram_publisher.py backend/telegram_dispatcher.py .github/workflows/collector.yml .github/workflows/pick-release.yml`

Expected: diff vacío. Si aparece cualquier cambio, detener la integración y revertir únicamente el cambio nuevo antes de continuar; no usar `git reset --hard`.

- [ ] **Step 7: Ejecutar un canario con publicación desactivada**

Usar el procedimiento existente con `publish=false`, `MEDIA_STORAGE_BACKEND=supabase` y `REMOTION_ENABLED=false`. Confirmar en logs solo los contadores de staging, render y DTO; no confirmar por el mero éxito de GitHub Actions.

Expected: picks e historial no cambian, Telegram textual no se llama, no hay publicación social, y los tests verifican que los objetos de preview no se conservan como aprobados.

- [ ] **Step 8: Aceptación por fases**

Aceptar R2 solo cuando exista un objeto derivado y uno privado de evidencia con digest, MIME, tamaño, fecha, backend y estado correctos. Aceptar Remotion solo con un MP4 validado por FFprobe y fallback FFmpeg probado. Aceptar Mini App solo con `initData` válido, vencido, manipulado, no vinculado y VIP cubiertos. Aceptar Plausible solo cuando un stub demuestre ausencia de PII. En todos los casos, mantener los defaults apagados hasta la revisión del canario.

- [ ] **Step 9: Commit documental final**

Commit: `git add docs/operations/media-rollout.md README.md; git commit -m "docs: define safe media rollout"`

## Autorización de integración

No se hará merge, push, migración remota, publicación ni configuración de secretos como parte de este plan. Cada PR debe conservar los commits pequeños, mostrar la suite correspondiente y recibir una revisión posterior antes de activar cualquier bandera. La primera salida productiva requiere observar un ciclo completo de staging, liberación, entrega, visualización y recibos; un workflow verde por sí solo no es evidencia suficiente.

## Revisión propia contra la especificación aprobada

- R2 durable, claves por contenido, evidencia privada, URL temporal y ledger: Tasks 1–2.
- Remotion aislado, dos composiciones, contrato MP4 y fallback FFmpeg: Task 3.
- Mini App `/telegram`, cuatro ventanas, estado VIP, historial, CTA, HMAC y deep link: Task 4.
- Plausible opcional, `dataLayer` conservado y allowlist sin PII: Task 5.
- Quiniela y AdSense separados para no bloquear ni contaminar picks: Task 6.
- Dry-run, previews, regresiones, canario y aceptación basada en recibos: Task 7.
- No se cambia Playdoit, ranking de IA, fuente de picks, Crear Apuesta ni historial: guardas y Task 7.

La revisión no encuentra marcadores de trabajo pendientes ni tareas con nombres vagos; cada acción tiene archivo, comando y resultado esperado. Los tipos `MediaObject`, `MediaStore`, `ReelInput`, `MiniAppDto` y los nombres de flags quedan definidos antes de usarse en tareas posteriores.
