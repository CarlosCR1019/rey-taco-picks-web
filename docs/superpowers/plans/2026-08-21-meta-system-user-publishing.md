# Meta System User Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the exact audited public pick for the current scraper run to Facebook and Instagram with one permanent Meta system-user token, durable per-destination receipts, safe free fallbacks for copy and artwork, and no duplicate successful posts.

**Architecture:** Add a service-role-only Supabase boundary that returns one eligible public pick and records independent social deliveries. Convert that row into a strict immutable content package, optionally enhance only its generic background and wording, render one deterministic 1080×1080 JPEG locally, upload it to a dedicated public bucket, and deliver through an injectable Meta Graph transport. The workflow recovers the exact current run even after a Telegram failure; successful destination receipts make retries idempotent.

**Tech Stack:** Python 3.11, pytest, Supabase/PostgreSQL RPC and Storage, Pillow, Selenium with headless Chrome, requests, Groq SDK, Cloudflare Workers AI REST API, Meta Graph API v26.0, GitHub Actions, Vitest/TypeScript for regression verification.

---

## Non-negotiable implementation boundaries

- Work on `master`, as explicitly approved, but preserve unrelated user changes and commit after each cohesive task.
- Follow red-green-refactor for every production change: first add a focused failing test, run it and confirm the expected failure, implement only enough behavior, then rerun the focused test and the affected regression suite.
- Never print, inspect, copy, return, or persist `META_SYSTEM_USER_ACCESS_TOKEN` outside the runtime request. Do not read the GitHub secret back during verification.
- Never use `FB_PAGE_ACCESS_TOKEN` as a fallback. One system-user token authenticates both destinations.
- Never publish a row loaded from `frontend/public/picks.json`; production accepts only the exact run-key RPC result.
- Never expose `razonamiento`, premium rows, source HTML, sportsbook evidence, credentials, or raw provider responses to Meta, Groq, Cloudflare, Storage, logs, or artifacts.
- The local branded renderer and deterministic captions are mandatory. Groq and Cloudflare are optional decorators and cannot block publication.
- The Psalms code, data, schedule, and content path are outside the files in this plan and must remain untouched.
- Automated tests make no live Meta, Groq, Cloudflare, or Supabase request. The final live publication is a separately approved gate.

## Task 1: Create the exact-run Supabase social contract

**Files:**

- Create: `supabase/migrations/20260821010000_meta_social_delivery.sql`
- Modify: `tests/test_supabase_contract.py`

- [ ] **Step 1: Add migration contract tests that fail before the migration exists**

Add a `META_SOCIAL_SQL` path constant and tests that normalize SQL whitespace and assert:

```python
META_SOCIAL_SQL = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260821010000_meta_social_delivery.sql"
)

def _function_body(sql: str, function_name: str) -> str:
    start = sql.index(f"create or replace function public.{function_name}")
    end = sql.index("$$;", start)
    return sql[start:end]

def test_meta_social_migration_has_public_jpeg_bucket_and_exact_run_rpc():
    sql = " ".join(META_SOCIAL_SQL.read_text(encoding="utf-8").lower().split())
    assert "insert into storage.buckets" in sql
    assert "'social-media'" in sql
    assert "array['image/jpeg']" in sql
    assert "create or replace function public.get_meta_social_batch" in sql
    assert "where runs.run_key = requested_run_key" in sql
    assert "picks.visibility = 'public'" in sql
    assert "picks.es_parlay = false" in sql
    assert "picks.estado = 'pendiente'" in sql
    assert "razonamiento" not in _function_body(sql, "get_meta_social_batch")

def test_meta_social_delivery_is_separate_from_telegram_destinations():
    sql = " ".join(META_SOCIAL_SQL.read_text(encoding="utf-8").lower().split())
    body = _function_body(sql, "record_meta_social_delivery")
    assert "('facebook', 'instagram')" in body
    assert "('admin', 'vip', 'free')" not in body
    assert "'receipt'" in body
    assert "token_invalid" in body
    assert "delivery_failed" in body
    assert "not_configured" in body
```

Also assert both new functions are `security definer`, use `search_path=public, pg_temp`, are revoked from `public`, `anon`, and `authenticated`, and are executable only by `service_role`. Preserve existing assertions proving `record_scraper_delivery` accepts only `admin`, `vip`, and `free`.

- [ ] **Step 2: Run the new contract tests and confirm the intended red state**

Run:

```powershell
python -m pytest tests/test_supabase_contract.py -q
```

Expected: failure because `20260821010000_meta_social_delivery.sql` does not exist.

- [ ] **Step 3: Implement the storage bucket and read RPC**

Create an idempotent transaction. The bucket statement must set `public = true`, `file_size_limit = 5242880`, and `allowed_mime_types = array['image/jpeg']` for `social-media` on both insert and conflict update.

Implement this exact RPC signature:

```sql
create or replace function public.get_meta_social_batch(
    requested_run_key text
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
```

Required behavior:

1. Reject a null or blank run key before querying.
2. Return SQL `null` when no `scraper_runs` row with that key is in `published` or `partial` status.
3. Require exactly one active `pick_batches` row for the matched run; raise a generic integrity exception otherwise.
4. Require exactly one row from that batch with `active = true`, `estado = 'pendiente'`, `visibility = 'public'`, and `es_parlay = false`.
5. Return SQL `null` if that row has a missing audit field, a future `source_observed_at`, or `source_starts_at <= clock_timestamp()`.
6. Return only `run_id`, `batch_id`, `delivery_status`, and a `public_pick` object with this allowlist:

```text
id, categoria, partido, pick, cuota, confianza, estado, es_parlay,
liga, mercado, riesgo, fecha_generacion, fecha_evento, horario,
tiene_valor, visibility, source, source_event_id, source_market_key,
source_selection_key, source_observed_at, source_starts_at
```

Do not use `to_jsonb(picks)` because future schema columns could silently cross the public boundary.

- [ ] **Step 4: Implement independent receipt-bearing social delivery**

Use this exact signature:

```sql
create or replace function public.record_meta_social_delivery(
    requested_run_id uuid,
    requested_destination text,
    requested_success boolean,
    requested_receipt text default '',
    requested_error text default ''
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
```

Validate before mutation:

- destination is exactly `facebook` or `instagram`;
- success is non-null;
- a success has an empty error and a receipt matching `^[A-Za-z0-9_:-]{1,200}$`;
- a failure has an empty receipt and an error exactly in `token_invalid`, `delivery_failed`, or `not_configured`.

Write the destination object into `scraper_runs.delivery_status`:

```sql
jsonb_build_object(
    'success', requested_success,
    'receipt', requested_receipt,
    'error', requested_error,
    'updated_at', now()
)
```

Lock and update only a known run whose status is `published` or `partial`. Recompute the run status using the complete ledger: `published` only when every present delivery entry has `success = true`, otherwise `partial`. Do not modify `record_scraper_delivery`.

- [ ] **Step 5: Lock down function permissions**

At the end of the migration:

```sql
revoke all on function public.get_meta_social_batch(text)
    from public, anon, authenticated;
revoke all on function public.record_meta_social_delivery(uuid, text, boolean, text, text)
    from public, anon, authenticated;
grant execute on function public.get_meta_social_batch(text) to service_role;
grant execute on function public.record_meta_social_delivery(uuid, text, boolean, text, text)
    to service_role;
```

Keep all statements between `begin;` and `commit;`.

- [ ] **Step 6: Run contract and security regressions**

Run:

```powershell
python -m pytest tests/test_supabase_contract.py tests/test_source_security.py -q
```

Expected: all selected tests pass and the original Telegram RPC assertions remain unchanged.

- [ ] **Step 7: Commit the database contract**

```powershell
git add supabase/migrations/20260821010000_meta_social_delivery.sql tests/test_supabase_contract.py
git commit -m "feat: add durable Meta social delivery contract"
```

## Task 2: Build the strict public content package and deterministic captions

**Files:**

- Create: `backend/social_content.py`
- Create: `tests/test_social_content.py`

- [ ] **Step 1: Write failing domain tests**

Cover a valid current public pick and reject each of these independently: missing row, multiple rows, `visibility != public`, parlay, non-pending status, missing source audit value, observation in the future, expired event, event not after observation, blank event/selection, invalid odds, and an unexpected key named `razonamiento`.

Define the expected immutable interface in the test:

```python
content = content_from_public_pick(valid_row, reference_at=NOW)
assert content.pick_id == "1780000000000000"
assert content.event == "América vs Tigres"
assert content.selection == "América gana"
assert content.odds_text == "1.80"
assert content.object_key(
    batch_id="11111111-1111-4111-8111-111111111111"
) == (
    "daily/11111111-1111-4111-8111-111111111111/1780000000000000.jpg"
)
```

Add caption assertions for both platforms:

```python
captions = build_fallback_captions(content)
for caption in (captions.facebook, captions.instagram):
    assert content.event in caption
    assert content.selection in caption
    assert "Momio observado: 1.80" in caption
    assert "reytacopicks.com" in caption
    assert "18+" in caption
    assert "Apuesta con responsabilidad" in caption
    assert "segura" not in caption.lower()
    assert "%" not in caption
```

- [ ] **Step 2: Confirm the missing-module failure**

Run:

```powershell
python -m pytest tests/test_social_content.py -q
```

Expected: collection fails with `ModuleNotFoundError: backend.social_content`.

- [ ] **Step 3: Implement immutable typed content**

Create frozen dataclasses with this public surface:

```python
@dataclass(frozen=True)
class SocialContent:
    pick_id: str
    category: str
    event: str
    selection: str
    odds_text: str
    schedule: str
    observed_at: datetime
    starts_at: datetime
    league: str
    market: str
    risk_label: str
    evidence_label: str
    has_value_signal: bool
    is_demo: bool = False

    def object_key(self, *, batch_id: str) -> str:
        normalized_batch_id = str(UUID(batch_id))
        if normalized_batch_id != batch_id.lower():
            raise ValueError("batch_id must be a canonical UUID")
        return f"daily/{normalized_batch_id}/{self.pick_id}.jpg"

@dataclass(frozen=True)
class SocialCaptions:
    facebook: str
    instagram: str

def content_from_public_pick(
    row: Mapping[str, object], *, reference_at: datetime
) -> SocialContent:
    """Validate and normalize the allowlisted persisted public row."""

def build_fallback_captions(content: SocialContent) -> SocialCaptions:
    """Return factual platform captions from normalized public facts only."""

def demo_social_content(*, reference_at: datetime) -> SocialContent:
    """Return a visibly non-current preview fixture with is_demo set to true."""
```

Use one explicit `SOCIAL_PICK_FIELDS` set matching Task 1. Reject unknown sensitive keys, including `razonamiento`, rather than ignoring them. Parse timestamps as timezone-aware UTC, format the observed time in `America/Mexico_City`, normalize `confianza` with `format_evidence_support`, and normalize decimal odds without floating-point arithmetic. Require a digits-only pick ID and a canonical UUID batch ID before constructing an object key; tests must reject slashes, traversal strings, and noncanonical IDs. `demo_social_content` sets `is_demo=True` and uses a visibly fictional non-current event; `content_from_public_pick` always sets it to false. The exact string `DEMO NO VIGENTE` is included in every demo caption and never in production persisted content.

Captions must remain factual. They may say `Señal de valor comparada` only when the persisted boolean is exactly true; confidence is presented as data support, never as win probability. Limit Instagram to four fixed brand/category hashtags and Facebook to two.

- [ ] **Step 4: Run focused and adjacent domain tests**

Run:

```powershell
python -m pytest tests/test_social_content.py tests/test_evidence_messaging.py tests/test_pick_publisher.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the public content boundary**

```powershell
git add backend/social_content.py tests/test_social_content.py
git commit -m "feat: validate public social content"
```

## Task 3: Add optional Groq copy with a fail-closed semantic validator

**Files:**

- Create: `backend/social_copy.py`
- Create: `tests/test_social_copy.py`

- [ ] **Step 1: Write failing adapter and validator tests**

Use a fake Groq client; never patch the network. Cover:

- missing key returns deterministic captions without constructing a client;
- default model is `openai/gpt-oss-20b`;
- request uses `response_format={"type": "json_object"}` and low reasoning effort;
- valid JSON with exactly `facebook` and `instagram` is accepted;
- malformed JSON, empty content, timeout, rate limit, extra keys, excess hashtags, missing fact, invented number, guarantee, probability, unsafe call to action, or missing responsible-use footer selects the deterministic fallback;
- provider exceptions and response bodies never appear in captured logs.

The fake response should prove semantic behavior:

```python
unsafe = {
    "facebook": "América gana seguro con 92% de probabilidad",
    "instagram": "Apuesta todo hoy #uno #dos #tres #cuatro #cinco",
}
assert provider.captions(content) == build_fallback_captions(content)
```

- [ ] **Step 2: Confirm the missing-module failure**

```powershell
python -m pytest tests/test_social_copy.py -q
```

Expected: collection fails with `ModuleNotFoundError: backend.social_copy`.

- [ ] **Step 3: Implement the injected Groq provider**

Use this interface:

```python
class CaptionProvider(Protocol):
    def captions(self, content: SocialContent) -> SocialCaptions:
        """Return validated captions or the deterministic fallback."""

class GroqCopyProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "openai/gpt-oss-20b",
        client_factory: Callable[[], object] | None = None,
    ) -> None:
        """Configure the optional provider without making a request."""

    def captions(self, content: SocialContent) -> SocialCaptions:
        """Generate, validate, and fall back without propagating provider errors."""
```

Send only an allowlisted dictionary derived from `SocialContent`. Request JSON object output, `reasoning_effort="low"`, temperature no greater than `0.3`, and a bounded token budget. Set no premium reasoning in the prompt.

Implement `_validate_candidate(candidate, content)` with these exact rules:

1. Candidate is an object with exactly two string keys: `facebook`, `instagram`.
2. Both strings include the normalized event, selection, odds, observation label, site, `18+`, and responsible-use wording.
3. Every numeric token in generated copy belongs to the allowlist built from odds, dates/times already provided, `18`, and the domain name.
4. Reject `%`, probability language, `garantizado`, `seguro/segura`, `sin riesgo`, `apuesta todo`, and claims of wins or sponsorship.
5. Instagram has at most four hashtags; Facebook has at most two.
6. When validating a preview marked demo, require the exact `DEMO NO VIGENTE` label in both captions.

Catch provider exceptions at the adapter boundary, log only `groq_copy status=fallback exception=<class>`, and return `build_fallback_captions(content)`.

- [ ] **Step 4: Run copy and content tests**

```powershell
python -m pytest tests/test_social_copy.py tests/test_social_content.py -q
```

Expected: all selected tests pass without network access.

- [ ] **Step 5: Commit the optional copy adapter**

```powershell
git add backend/social_copy.py tests/test_social_copy.py
git commit -m "feat: add safe optional Groq social copy"
```

## Task 4: Replace the banner path with an exact 1080×1080 JPEG renderer

**Files:**

- Create: `backend/social_background.py`
- Create: `tests/test_social_background.py`
- Modify: `backend/banner_template.html`
- Modify: `backend/render_html_banner.py`
- Modify: `backend/social_banner.py`
- Delete: `backend/temp_banner.html`
- Modify: `tests/test_render_html_banner.py`
- Modify: `tests/test_social_banner.py`

- [ ] **Step 1: Write failing local renderer tests**

Replace tests that pass arbitrary pick lists with one `SocialContent`. Assert:

```python
jpeg = render_social_jpeg(content, generated_at=NOW, driver_factory=fake_driver)
with Image.open(BytesIO(jpeg)) as image:
    assert image.size == (1080, 1080)
    assert image.mode == "RGB"
    assert image.format == "JPEG"
```

Also assert:

- HTML escapes event and selection text;
- only one card is rendered;
- missing/premium/parlay rows cannot reach the renderer because its argument type is `SocialContent`;
- logo data is embedded as a `data:image/jpeg;base64,` URI;
- rendered HTML contains no `http://`, `https://`, Google Fonts import, or repo-relative logo path;
- temporary HTML and PNG files are removed after success and after driver failure;
- output bytes fail if the screenshot is not exactly 1080×1080;
- no production function reads `frontend/public/picks.json` or writes `backend/temp_banner.html`.

- [ ] **Step 2: Write failing Cloudflare fallback tests**

Test a `CloudflareBackgroundProvider` through an injected HTTP session. Missing account/token, timeout, non-200 response, invalid base64, non-image bytes, wrong dimensions, or image decode error must return `None`. A valid response returns normalized image bytes, and the prompt must contain `text-free`, `logo-free`, and `generic sports atmosphere` while excluding the content's event, teams, league, market, sportsbook, and athlete names.

- [ ] **Step 3: Confirm the red state**

```powershell
python -m pytest tests/test_render_html_banner.py tests/test_social_banner.py tests/test_social_background.py -q
```

Expected: failures because the explicit JPEG API and background provider do not exist and the current renderer produces a PNG element screenshot that is not 1080×1080.

- [ ] **Step 4: Implement the optional generic background provider**

Use this interface and endpoint construction:

```python
class CloudflareBackgroundProvider:
    MODEL = "@cf/black-forest-labs/flux-2-dev"

    def __init__(self, *, account_id: str, api_token: str, session: object) -> None:
        """Store injected configuration; do not make a request here."""

    def create(self) -> bytes | None:
        """Return a validated generic bitmap or None for local fallback."""
```

POST to:

```text
https://api.cloudflare.com/client/v4/accounts/<account-id>/ai/run/@cf/black-forest-labs/flux-2-dev
```

Use a 20-second timeout, authorization header, and a constant generic prompt. Do not include pick facts. Decode and validate through Pillow, crop to square, resize to 1080×1080, darken locally, and return JPEG/PNG bytes only. Log only a safe fallback class.

- [ ] **Step 5: Implement a self-contained deterministic template**

Update `banner_template.html` to:

- keep `html`, `body`, and `#banner-root` fixed at 1080×1080;
- use the logo palette and a system font stack;
- accept substitution slots for one escaped card, date, embedded logo, and optional embedded background;
- include `Momio observado`, observation time, `reytacopicks.com`, `18+`, and `Apuesta con responsabilidad`;
- remove the premium upsell language from the public artwork;
- remove all external URLs and font imports.

The optional generated bitmap is only a dark background layer; all text, numbers, logo, and notices remain local overlays.

- [ ] **Step 6: Implement the new renderer**

Use this surface:

```python
def render_social_jpeg(
    content: SocialContent,
    *,
    generated_at: datetime,
    background_bytes: bytes | None = None,
    driver_factory: Callable[[webdriver.ChromeOptions], WebDriver] | None = None,
) -> bytes:
    """Render one self-contained branded square and return JPEG bytes."""
```

Implementation requirements:

1. Read the approved logo from `frontend/public/logo.jpg` and embed it as base64.
2. Build HTML only from `SocialContent`, `html.escape`, and local assets.
3. Create a `TemporaryDirectory`, write the HTML there, and open its resolved `file:///` URI.
4. Use standard Selenium `webdriver.Chrome`, not `undetected_chromedriver`, with headless mode, hidden scrollbars, device scale factor 1, and CDP device metrics 1080×1080.
5. Capture a full viewport PNG, load it with Pillow, reject any size other than 1080×1080, convert to RGB, and return quality-92 JPEG bytes.
6. Always call `driver.quit()` and let `TemporaryDirectory` clean files.
7. Do not sleep for web fonts; wait only for `document.readyState === 'complete'` with a short bound.

Retain `banner_date_label` for existing date tests. Convert `backend/social_banner.py` into a compatibility wrapper around the local renderer or remove its production entry points; it must contain no Pollinations URL, `urllib.request`, random remote prompt, or arbitrary JSON fallback. Delete tracked `backend/temp_banner.html`.

- [ ] **Step 7: Run renderer tests and inspect one non-current demo artifact**

```powershell
python -m pytest tests/test_render_html_banner.py tests/test_social_banner.py tests/test_social_background.py -q
python -m backend.render_html_banner --demo --output "$env:TEMP\rey-taco-social-demo.jpg"
```

Expected: all tests pass; the file is exactly 1080×1080 JPEG and visibly says `DEMO NO VIGENTE`. Inspect it with the local image viewer before continuing. The demo command must never load a persisted current pick or publish anything.

- [ ] **Step 8: Commit the renderer replacement**

```powershell
git add backend/banner_template.html backend/render_html_banner.py backend/social_banner.py backend/social_background.py tests/test_render_html_banner.py tests/test_social_banner.py tests/test_social_background.py
git add -u backend/temp_banner.html
git commit -m "feat: render deterministic social JPEG"
```

## Task 5: Add the Supabase batch and Storage adapter

**Files:**

- Create: `backend/social_repository.py`
- Create: `tests/test_social_repository.py`

- [ ] **Step 1: Write failing repository tests with a fake Supabase client**

Cover:

- blank run key is rejected before an RPC;
- `get_meta_social_batch` is called with exactly `{"requested_run_key": run_key}`;
- SQL null becomes `None` and performs no Storage call;
- the response must contain one run ID, batch ID, mapping ledger, and public pick;
- malformed or extra sensitive public-pick keys are rejected;
- deterministic path is `daily/<batch-id>/<pick-id>.jpg`;
- upload targets bucket `social-media` with `content-type: image/jpeg` and `upsert: true`;
- non-JPEG bytes and oversized payloads are rejected before upload;
- the returned public URL must be HTTPS and contain `/storage/v1/object/public/social-media/<exact-key>`;
- delivery writes call the five-argument social RPC and reject raw/free-form errors.

- [ ] **Step 2: Confirm the missing-module failure**

```powershell
python -m pytest tests/test_social_repository.py -q
```

Expected: collection fails with `ModuleNotFoundError: backend.social_repository`.

- [ ] **Step 3: Implement typed repository records and protocol**

```python
@dataclass(frozen=True)
class MetaSocialBatch:
    run_id: str
    batch_id: str
    delivery_status: Mapping[str, object]
    content: SocialContent

class SocialRepository(Protocol):
    def get_batch(self, *, run_key: str, reference_at: datetime) -> MetaSocialBatch | None:
        """Return the exact eligible batch or None."""
    def upload_jpeg(self, *, batch: MetaSocialBatch, jpeg: bytes) -> str:
        """Upload the validated deterministic public JPEG and return its URL."""
    def record_delivery(self, *, run_id: str, result: "MetaDelivery") -> None:
        """Persist one sanitized destination result immediately."""

class SupabaseSocialRepository:
    BUCKET = "social-media"
    MAX_BYTES = 5 * 1024 * 1024
```

Construct the Supabase client only from explicit `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` arguments. Never accept the anon key. Normalize the SDK's RPC/storage response shapes in small private functions so tests can fail closed on unexpected objects.

Before upload, verify JPEG magic bytes, Pillow format/mode/dimensions, content length, and exact deterministic key. Obtain the public URL from the SDK, parse with `urllib.parse.urlsplit`, require `https`, and compare the decoded path to the exact bucket and object key.

- [ ] **Step 4: Run focused repository and content tests**

```powershell
python -m pytest tests/test_social_repository.py tests/test_social_content.py -q
```

Expected: all selected tests pass with fake clients only.

- [ ] **Step 5: Commit the data adapter**

```powershell
git add backend/social_repository.py tests/test_social_repository.py
git commit -m "feat: add exact-run social repository"
```

## Task 6: Rewrite Meta delivery and orchestration around the system user

**Files:**

- Rewrite: `backend/social_poster.py`
- Create: `tests/test_social_poster.py`

- [ ] **Step 1: Write failing settings and transport tests**

Assert the settings contract:

```python
settings = MetaSettings.from_mapping({
    "META_SYSTEM_USER_ACCESS_TOKEN": "runtime-secret",
    "FB_PAGE_ID": "1311611272037375",
    "IG_USER_ID": "17841441356316454",
})
assert settings.graph_version == "v26.0"
assert settings.token == "runtime-secret"
```

Prove that `FB_PAGE_ACCESS_TOKEN` and any Instagram user-token variable are ignored. Verify blank token/IDs yield per-destination `not_configured` results rather than fallback credentials.

Using a fake HTTP session, assert:

- Facebook POST is `https://graph.facebook.com/v26.0/<page-id>/photos`, sends the JPEG as `source`, caption as `message`, and token only in form data or header;
- Instagram create POST is `/<ig-id>/media` with the exact public JPEG URL;
- status GET is `/<container-id>?fields=status_code` and uses a bounded poll sequence;
- publish POST is `/<ig-id>/media_publish` with `creation_id`;
- success requires a nonempty, safe receipt ID;
- code 190/OAuth maps to `token_invalid` without logging raw JSON;
- invalid JSON, timeout, non-2xx, terminal media error, missing ID, and poll exhaustion map to `delivery_failed`;
- no request URL, log record, exception message, or result contains the token or raw provider body.

- [ ] **Step 2: Write failing orchestration tests**

Use fakes for repository, renderer, copy provider, background provider, and transport. Cover:

1. No exact batch: no render, upload, Meta request, or ledger write; exit code 0.
2. Both ledger destinations already succeeded: skip render/upload and return two `skipped` results.
3. Facebook succeeded previously and Instagram did not: render/upload once and call only Instagram.
4. Facebook succeeds and Instagram fails: record Facebook immediately, still attempt Instagram, record its sanitized failure, exit code 1.
5. Facebook fails and Instagram succeeds: both are recorded independently, exit code 1.
6. Missing optional Groq/Cloudflare settings: local image and captions still publish.
7. `META_DRY_RUN=true`: fetch and render the exact batch, validate the JPEG and captions, optionally write the reviewed local artifact, but do not upload, call Meta, or write delivery state.
8. A renderer or validation failure makes no Meta request and returns a sanitized nonzero result.
9. A Storage failure records Instagram as `delivery_failed` while Facebook can still publish and retain its success receipt.

- [ ] **Step 3: Confirm the old implementation fails the new contract**

```powershell
python -m pytest tests/test_social_poster.py -q
```

Expected: failures because the old module reads `FB_PAGE_ACCESS_TOKEN`, uses v19.0, logs raw responses, and posts only Facebook from its entry point.

- [ ] **Step 4: Implement immutable results and sanitized settings**

Use these exact public types:

```python
MetaStatus = Literal[
    "success", "skipped", "not_configured", "token_invalid", "delivery_failed"
]

@dataclass(frozen=True)
class MetaDelivery:
    destination: Literal["facebook", "instagram"]
    status: MetaStatus
    receipt: str = ""

    @property
    def success(self) -> bool:
        return self.status in {"success", "skipped"}

@dataclass(frozen=True)
class MetaSettings:
    token: str
    facebook_page_id: str
    instagram_user_id: str
    graph_version: str = "v26.0"
    dry_run: bool = False
    dry_run_output: str = ""
```

Keep error details out of `MetaDelivery`; its status is the only failure text eligible for persistence. Validate Graph version against `^v[0-9]+[.][0-9]+$` and IDs against digits. Do not log the settings representation.

- [ ] **Step 5: Implement injectable Meta Graph transport**

```python
class MetaHttpTransport:
    def publish_facebook(
        self, *, jpeg: bytes, caption: str, settings: MetaSettings
    ) -> MetaDelivery:
        """Publish the local JPEG to the configured Facebook Page."""

    def publish_instagram(
        self, *, image_url: str, caption: str, settings: MetaSettings
    ) -> MetaDelivery:
        """Create, wait for, and publish one Instagram media container."""
```

Use an `Authorization: Bearer <token>` header for every request, never a token query parameter or logged form value. Use 30-second request timeouts and at most five Instagram status polls with an injected sleep function and fixed short interval. Accept `FINISHED` as ready, keep polling `IN_PROGRESS`, and fail on `ERROR` or an unknown terminal status. Parse response bodies privately and discard them after extracting a safe ID or code. Log only lines shaped like:

```text
meta destination=instagram status=delivery_failed exception=Timeout
meta destination=facebook status=success receipt=<safe-id>
```

- [ ] **Step 6: Implement exact-run orchestration**

Expose an injectable function and a thin CLI:

```python
def publish_meta(
    *,
    run_key: str,
    reference_at: datetime,
    settings: MetaSettings,
    repository: SocialRepository,
    transport: MetaHttpTransport,
    copy_provider: CaptionProvider,
    background_provider: object | None,
) -> tuple[MetaDelivery, MetaDelivery]:
    """Publish or skip both destinations for one exact persisted run."""

def main(environ: Mapping[str, str] | None = None) -> int:
    """Build runtime adapters, execute the orchestrator, and return a process code."""
```

Flow:

1. Resolve run key from `SCRAPER_RUN_KEY`; otherwise derive exactly `github-run:<GITHUB_RUN_ID>`.
2. Fetch exact batch and return 0 on `None`.
3. Read the ledger before any expensive work and produce `skipped` for a destination whose entry has `success: true` and a safe receipt.
4. If all destinations skip, return without rendering.
5. Build captions through Groq with deterministic fallback.
6. Ask Cloudflare for a background only when configured; render locally in all cases.
7. In dry-run mode validate and log safe statuses, optionally write the JPEG to `META_DRY_RUN_OUTPUT`, then stop before Storage/Meta/ledger.
8. Publish Facebook from local bytes and record its result without depending on Storage or Instagram.
9. If Instagram needs delivery, upload once, reuse the deterministic URL on retry, then call and record Instagram. A Storage failure records only Instagram as `delivery_failed`; it does not erase or block a Facebook success.
10. Call and record each needed destination independently, immediately after its result. Never record a synthetic `skipped` result over an existing success receipt.
11. Persist `not_configured`, `token_invalid`, and `delivery_failed` with an empty receipt; persist success with its receipt.
12. Return nonzero if any configured destination has `token_invalid` or `delivery_failed`. A `not_configured` destination is visible in logs/ledger but does not make the other destination fail.

The CLI loads `backend/.env` for local use but environment variables win. It must not print secret lengths, token prefixes, request payloads, or exception messages from providers.

- [ ] **Step 7: Run all social unit tests**

```powershell
python -m pytest tests/test_social_poster.py tests/test_social_repository.py tests/test_social_copy.py tests/test_social_content.py tests/test_render_html_banner.py tests/test_social_background.py -q
```

Expected: all selected tests pass; no test performs a network request.

- [ ] **Step 8: Commit the delivery rewrite**

```powershell
git add backend/social_poster.py tests/test_social_poster.py
git commit -m "feat: publish Meta posts with system user"
```

## Task 7: Wire GitHub Actions, environment examples, and operations documentation

**Files:**

- Modify: `.github/workflows/scraper.yml`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Modify: `tests/test_scraper_workflow.py`
- Modify: `tests/test_source_security.py`
- Modify: `docs/operations/security-and-payments.md`

- [ ] **Step 1: Write failing workflow and source-security assertions**

Update the social-step test to require:

```python
assert " ".join(social["if"].split()) == "always() && !cancelled()"
assert social["env"]["META_SYSTEM_USER_ACCESS_TOKEN"] == (
    "${{ secrets.META_SYSTEM_USER_ACCESS_TOKEN }}"
)
assert social["env"]["SUPABASE_SERVICE_ROLE_KEY"] == SERVICE_ROLE_EXPRESSION
assert social["env"]["META_GRAPH_VERSION"] == "v26.0"
assert "FB_PAGE_ACCESS_TOKEN" not in WORKFLOW.read_text(encoding="utf-8")
```

Also assert the step receives `GITHUB_RUN_ID` automatically through the runner environment, executes from repository root with `python -m backend.social_poster`, and does not condition on `steps.scraper.outputs.resumed`. Keep the existing pinned-action count unchanged; no upload-artifact action is added.

Update source-security tests so they scan runtime Python, YAML, dotenv examples, and `docs/operations/security-and-payments.md` for:

- obsolete `FB_PAGE_ACCESS_TOKEN`;
- literal Meta token patterns and `access_token=` in URLs/log strings;
- Pollinations production endpoints;
- raw response logging patterns such as `print(res)` and `response.text`;
- the old runbook claim that resumed runs omit social delivery.

- [ ] **Step 2: Confirm the old workflow fails the new expectations**

```powershell
python -m pytest tests/test_scraper_workflow.py tests/test_source_security.py -q
```

Expected: failures on the old secret name, `success()` condition, and obsolete operations text.

- [ ] **Step 3: Update the workflow**

Keep the social step after the scraper step in the same job, but set:

```yaml
- name: Auto-Post Social Media Banner (Facebook & Instagram)
  if: always() && !cancelled()
  env:
    SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
    SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
    META_SYSTEM_USER_ACCESS_TOKEN: ${{ secrets.META_SYSTEM_USER_ACCESS_TOKEN }}
    FB_PAGE_ID: ${{ secrets.FB_PAGE_ID }}
    IG_USER_ID: ${{ secrets.IG_USER_ID }}
    META_GRAPH_VERSION: v26.0
    GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
    GROQ_CONTENT_MODEL: openai/gpt-oss-20b
    CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
    CLOUDFLARE_AI_API_TOKEN: ${{ secrets.CLOUDFLARE_AI_API_TOKEN }}
  run: python -m backend.social_poster
```

Do not add `SCRAPER_RUN_KEY` in Actions; the CLI derives `github-run:<GITHUB_RUN_ID>`, exactly matching scraper configuration. Keep `META_DRY_RUN` absent in production so the default is false.

- [ ] **Step 4: Update dotenv examples with names only**

Both example files must contain empty values for:

```dotenv
META_SYSTEM_USER_ACCESS_TOKEN=
FB_PAGE_ID=
IG_USER_ID=
META_GRAPH_VERSION=v26.0
GROQ_CONTENT_MODEL=openai/gpt-oss-20b
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_AI_API_TOKEN=
META_DRY_RUN=false
META_DRY_RUN_OUTPUT=
```

Remove `FB_PAGE_ACCESS_TOKEN`. Keep the existing Supabase and scraper variables. Do not alter local untracked or ignored `.env` files.

- [ ] **Step 5: Update the operations runbook**

Document:

1. Apply migrations in timestamp order through `20260821010000_meta_social_delivery.sql` before enabling the step.
2. Required GitHub secret names and optional Groq/Cloudflare names, never their values.
3. Exact-run recovery: the social step always evaluates the current GitHub run and safely no-ops if persistence never occurred.
4. Ledger query showing `facebook` and `instagram` success, receipt, safe error, and update time alongside Telegram entries.
5. Local `META_DRY_RUN=true` command and expected safe log fields.
6. Rotation: generate a new system-user token, replace the one GitHub secret, perform an approved controlled validation, then revoke the old token.
7. `token_invalid` recovery without printing Meta's response.
8. The public `social-media` bucket contains only retained public JPEGs.
9. Groq/Cloudflare failure falls back locally and Psalms remain independent and unchanged.

- [ ] **Step 6: Run workflow/security tests and syntax checks**

```powershell
python -m pytest tests/test_scraper_workflow.py tests/test_source_security.py -q
python -c "import yaml, pathlib; yaml.load(pathlib.Path('.github/workflows/scraper.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader); print('workflow yaml ok')"
```

Expected: all selected tests pass and the YAML parser prints `workflow yaml ok`.

- [ ] **Step 7: Commit workflow and documentation**

```powershell
git add .github/workflows/scraper.yml .env.example backend/.env.example tests/test_scraper_workflow.py tests/test_source_security.py docs/operations/security-and-payments.md
git commit -m "chore: wire resilient Meta social publishing"
```

## Task 8: Verify locally, deploy the schema deliberately, and gate the first live post

**Files:**

- Verify only; change files solely to correct failures found by the checks below.

- [ ] **Step 1: Run focused backend verification from a clean process**

```powershell
python -m pytest tests/test_supabase_contract.py tests/test_social_content.py tests/test_social_copy.py tests/test_social_background.py tests/test_render_html_banner.py tests/test_social_banner.py tests/test_social_repository.py tests/test_social_poster.py tests/test_scraper_workflow.py tests/test_source_security.py -q
```

Expected: all focused tests pass, with no external requests.

- [ ] **Step 2: Run the complete Python regression suite**

```powershell
python -m pytest -q
```

Expected: every test passes. If a failure is unrelated and pre-existing, stop and report its exact test name and evidence rather than hiding it.

- [ ] **Step 3: Verify the frontend and prove Psalms remain intact**

```powershell
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
git diff --name-only c52c501..HEAD | rg -i "salmo|psalm"
```

Expected: Vitest, typecheck, and build pass; the final command has no output because no Psalm file was changed.

- [ ] **Step 4: Run repository integrity checks**

```powershell
git diff --check
git status --short
rg -n "FB_PAGE_ACCESS_TOKEN|image[.]pollinations[.]ai|graph[.]facebook[.]com/v19[.]0" backend .github .env.example backend/.env.example docs/operations
rg -n "META_SYSTEM_USER_ACCESS_TOKEN=[^[:space:]]+" . --glob "!.git/**" --glob "!backend/.env" --glob "!.env"
```

Expected: `git diff --check` is silent, status contains no uncommitted implementation files, and both searches are silent. Do not open ignored dotenv files or echo any runtime secret.

- [ ] **Step 5: Perform a local dry run against a deliberately selected exact run**

Set `SCRAPER_RUN_KEY` to a known current persisted run in the local environment and set `META_DRY_RUN=true`; do not set or print the Meta token for this check.

```powershell
$env:META_DRY_RUN = 'true'
$env:META_DRY_RUN_OUTPUT = Join-Path $env:TEMP 'rey-taco-exact-run-preview.jpg'
python -m backend.social_poster
Remove-Item Env:META_DRY_RUN
Remove-Item Env:META_DRY_RUN_OUTPUT
```

Expected: the command either reports `no_batch` safely or renders and validates one exact 1080×1080 JPEG; it performs no Storage upload, Meta request, or ledger mutation. If the production schema lacks the new RPC, this step is expected to stop safely and confirms the migration gate.

- [ ] **Step 6: Stop for explicit approval before changing production Supabase**

Show the user:

- complete test/build evidence;
- exact migration filename;
- read-only diff summary of the SQL;
- confirmation that no live social request has occurred.

Obtain explicit approval immediately before running any production schema command. Do not infer approval from the earlier design approval.

- [ ] **Step 7: Apply and verify the migration after approval**

First inspect CLI/project linkage without mutation:

```powershell
supabase --version
supabase migration list
```

After confirming the linked project is the intended Rey Taco production project, run the repository's approved deployment method once. If the project uses the Supabase CLI link, the mutation is:

```powershell
supabase db push
```

Then perform read-only checks through the service-role client:

- `get_meta_social_batch` exists and rejects anon/authenticated execution;
- `record_meta_social_delivery` exists and rejects anon/authenticated execution;
- `social-media` is public, JPEG-only, and limited to 5 MiB;
- the existing Telegram delivery RPC still accepts only its original destinations.

Never print the service-role key or RPC response fields outside the public allowlist.

- [ ] **Step 8: Repeat the exact-run dry run after migration**

Run the dry-run command again with a current run key. Inspect the generated local JPEG visually and confirm:

- exact 1080×1080 dimensions;
- one public pick only;
- correct event, selection, observed odds, and observation time;
- no reasoning or premium selection;
- logo palette, readable layout, `18+`, and responsible-use notice;
- no `DEMO NO VIGENTE` label on a real current persisted pick.

- [ ] **Step 9: Stop for explicit approval before the first live Meta publication**

Present the reviewed image and factual captions to the user. Ask for one-time approval to publish that exact pick to the official Facebook Page and Instagram account. Design approval, token setup, migration approval, and dry-run approval do not authorize the live post.

- [ ] **Step 10: Perform one controlled live publication after approval**

Use the existing GitHub `workflow_dispatch` so the production secret stays inside GitHub Actions. Confirm the selected run is current before dispatch. Observe safe status classes only; never expose Actions environment data.

Acceptance evidence:

1. Facebook returns and stores one safe receipt ID.
2. Instagram returns and stores one safe media ID.
3. Supabase ledger entries match the same run ID and batch ID.
4. The public Storage URL uses the deterministic path.
5. The posts display the reviewed image and captions.

- [ ] **Step 11: Prove idempotency with one rerun**

Rerun social delivery for the same stable run key. Expected: both destinations report `skipped`, no new Meta media is created, and the original receipts remain unchanged.

- [ ] **Step 12: Record final verification without secrets**

Update only the operations runbook if actual commands or recovery details differed from the documented path. Then run:

```powershell
git diff --check
git status --short --branch
git log -6 --oneline
```

If documentation changed, commit it:

```powershell
git add docs/operations/security-and-payments.md
git commit -m "docs: record Meta publishing validation"
```

## Completion criteria

The implementation is complete only when all of the following are evidenced:

- one system-user secret drives both Meta destinations and no legacy token fallback exists;
- only one exact, current, audited public non-parlay pick crosses the database boundary;
- local deterministic copy and artwork succeed without Groq or Cloudflare;
- the JPEG is exactly 1080×1080, public only at the deterministic Storage path, and contains no premium reasoning;
- Facebook and Instagram successes/failures are independent and durable;
- a successful destination is skipped on retry;
- configured failures return nonzero with sanitized logs;
- complete Python and frontend suites pass;
- production migration and first live publication each received their own immediate approval;
- scraper, Telegram, frontend, membership, payments, result grading, and Psalms behavior remain unchanged.
