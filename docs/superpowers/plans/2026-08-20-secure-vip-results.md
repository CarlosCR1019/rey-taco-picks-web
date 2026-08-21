# Secure VIP and Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace client-trusted VIP access and unsafe result/payment automation with server-authorized membership, conservative grading, and fail-closed operations.

**Architecture:** Pure Python domain functions grade completed events and keep ambiguity pending for review. Supabase RLS and RPC functions define public/premium contracts, while Stripe and Telegram/SPEI integrations only change subscription state through authenticated server paths.

**Tech Stack:** Python 3 `unittest`, Supabase/PostgreSQL, Deno TypeScript Edge Functions, Stripe Checkout/Webhooks, Telegram Bot API.

---

### Task 1: Add security regression coverage and remove tracked credentials

**Files:**
- Create: `tests/test_source_security.py`
- Create: `.env.example`
- Create: `backend/.env.example`
- Modify: `backend/set_photo.py:1-12`
- Modify: `backend/social_poster.py:1-22`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing source-security test**

```python
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("010319NyC", "TACOVIP2026", "8684914807:AA", "EAGMJ4QmnNEI")

class SourceSecurityTests(unittest.TestCase):
    def test_tracked_source_has_no_known_live_secrets(self):
        files = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        searchable = [p for p in files if not p.startswith("docs/")]
        hits = []
        for relative in searchable:
            path = ROOT / relative
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for marker in FORBIDDEN:
                if marker in text:
                    hits.append(f"{relative}: {marker}")
        self.assertEqual(hits, [])

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the expected failure**

Run: `python -m unittest tests.test_source_security -v`

Expected: FAIL listing `backend/set_photo.py`, `backend/social_poster.py`, `frontend/src/main.ts`, and built `dist` assets.

- [ ] **Step 3: Read all runtime credentials from the environment**

Use this fail-closed pattern in `backend/set_photo.py` and `backend/social_poster.py`:

```python
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
```

Add variable names without values to the example files. Add `.superpowers/` and `.worktrees/` to `.gitignore`. Remove hardcoded admin/password/promo-code markers from frontend source; the rebuilt `dist` is handled after the frontend plan.

- [ ] **Step 4: Run the test after the frontend and dist cleanup**

Run: `python -m unittest tests.test_source_security -v`

Expected: PASS with one test and no source hits.

- [ ] **Step 5: Commit**

```bash
git add .gitignore .env.example backend/.env.example backend/set_photo.py backend/social_poster.py tests/test_source_security.py
git commit -m "security: remove tracked service credentials"
```

### Task 2: Build conservative result-domain functions

**Files:**
- Create: `backend/results_domain.py`
- Create: `tests/test_results_domain.py`

- [ ] **Step 1: Write failing tests for team matching and final-state gating**

```python
import unittest
from backend.results_domain import EventResult, match_event, grade_pick

class ResultDomainTests(unittest.TestCase):
    def setUp(self):
        self.final = EventResult("Tigres UANL", "Club America", 2, 1, True)

    def test_both_teams_must_match(self):
        self.assertTrue(match_event("Tigres vs America", self.final))
        self.assertFalse(match_event("Tigres vs Monterrey", self.final))

    def test_incomplete_event_stays_pending(self):
        live = EventResult("Tigres UANL", "Club America", 2, 1, False)
        self.assertEqual(grade_pick("Más de 2.5 goles", live), "pendiente")

    def test_totals_are_graded_from_score(self):
        self.assertEqual(grade_pick("Más de 2.5 goles", self.final), "ganado")
        self.assertEqual(grade_pick("Menos de 2.5 goles", self.final), "perdido")

    def test_corners_without_stats_require_review(self):
        self.assertEqual(grade_pick("Más de 8.5 córners", self.final), "revision_pendiente")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `python -m unittest tests.test_results_domain -v`

Expected: ERROR with `ModuleNotFoundError: backend.results_domain`.

- [ ] **Step 3: Implement the minimal result domain**

```python
from dataclasses import dataclass
import re
import unicodedata

@dataclass(frozen=True)
class EventResult:
    home: str
    away: str
    home_score: float
    away_score: float
    completed: bool
    home_corners: float | None = None
    away_corners: float | None = None

def normalize_team(value: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()
    return {token for token in re.findall(r"[a-z0-9]+", plain) if token not in {"fc", "cf", "club", "deportivo"}}

def _team_matches(expected: str, actual: str) -> bool:
    left, right = normalize_team(expected), normalize_team(actual)
    return bool(left and right and (left <= right or right <= left or len(left & right) / max(len(left), len(right)) >= 0.67))

def match_event(label: str, event: EventResult) -> bool:
    parts = re.split(r"\s+(?:vs\.?|v\.?|-)\s+", label, maxsplit=1, flags=re.I)
    return len(parts) == 2 and _team_matches(parts[0], event.home) and _team_matches(parts[1], event.away)

def grade_pick(selection: str, event: EventResult) -> str:
    if not event.completed:
        return "pendiente"
    normalized = unicodedata.normalize("NFKD", selection.lower()).encode("ascii", "ignore").decode()
    if "corner" in normalized or "esquina" in normalized:
        if event.home_corners is None or event.away_corners is None:
            return "revision_pendiente"
        total = event.home_corners + event.away_corners
    else:
        total = event.home_score + event.away_score
    threshold = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if threshold and ("mas de" in normalized or "menos de" in normalized):
        line = float(threshold.group(1))
        won = total > line if "mas de" in normalized else total < line
        return "ganado" if won else "perdido"
    return "revision_pendiente"
```

- [ ] **Step 4: Run tests and verify green**

Run: `python -m unittest tests.test_results_domain -v`

Expected: PASS, four tests.

- [ ] **Step 5: Commit**

```bash
git add backend/results_domain.py tests/test_results_domain.py
git commit -m "feat: grade completed results conservatively"
```

### Task 3: Integrate safe grading into the automatic verifier

**Files:**
- Modify: `backend/verificar_resultados.py:1-290`
- Modify: `tests/test_results_domain.py`

- [ ] **Step 1: Add a failing unit-result test**

```python
from backend.results_domain import unit_result

def test_unit_result_uses_decimal_odds(self):
    assert unit_result("ganado", 1.80) == 0.8
    assert unit_result("perdido", 1.80) == -1.0
    assert unit_result("revision_pendiente", 1.80) == 0.0
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m unittest tests.test_results_domain -v`

Expected: FAIL because `unit_result` is absent.

- [ ] **Step 3: Add the function and route verifier decisions through the domain module**

```python
def unit_result(status: str, decimal_odds: float) -> float:
    if status == "ganado":
        return round(float(decimal_odds) - 1.0, 4)
    if status == "perdido":
        return -1.0
    return 0.0
```

In `verificar_resultados.py`, construct `EventResult` only from API events, skip events where `completed` is false, require `match_event(pick["partido"], event)`, call `grade_pick`, and update only when the returned state is not `pendiente`. Store audit columns when available and never special-case every corner pick as won.

- [ ] **Step 4: Run all backend unit tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS with no network calls.

- [ ] **Step 5: Commit**

```bash
git add backend/verificar_resultados.py backend/results_domain.py tests/test_results_domain.py
git commit -m "fix: prevent false automatic pick wins"
```

### Task 4: Make SPEI proof review manual and private

**Files:**
- Create: `backend/payment_review.py`
- Create: `tests/test_payment_review.py`
- Modify: `backend/ticket_listener.py:215-292`

- [ ] **Step 1: Write the failing review-policy test**

```python
import unittest
from backend.payment_review import classify_receipt

class PaymentReviewTests(unittest.TestCase):
    def test_ocr_never_approves_membership(self):
        result = classify_receipt("BBVA transferencia exitosa 299 Rey Taco")
        self.assertEqual(result.status, "pending_review")
        self.assertTrue(result.detected_amount)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify import failure**

Run: `python -m unittest tests.test_payment_review -v`

Expected: ERROR with `ModuleNotFoundError`.

- [ ] **Step 3: Implement a non-approving classifier**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ReceiptReview:
    status: str
    detected_amount: bool
    detected_bank: bool

def classify_receipt(text: str) -> ReceiptReview:
    normalized = text.lower()
    return ReceiptReview(
        status="pending_review",
        detected_amount="299" in normalized,
        detected_bank="bbva" in normalized or "spei" in normalized,
    )
```

Change `procesar_comprobante_cliente` to store or forward the receipt to the administrator with `pending_review`, never set `is_premium`, and never approve a Telegram join request. Keep the user message as “recibido y pendiente de revisión.” Store payment receipts outside `frontend/public/tickets`.

- [ ] **Step 4: Run tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/payment_review.py backend/ticket_listener.py tests/test_payment_review.py
git commit -m "security: require manual SPEI receipt approval"
```

### Task 5: Add Supabase schema and RLS contracts

**Files:**
- Create: `supabase/migrations/20260820220000_secure_membership.sql`
- Create: `tests/test_supabase_contract.py`

- [ ] **Step 1: Write a failing migration-contract test**

```python
from pathlib import Path
import unittest

SQL = (Path(__file__).parents[1] / "supabase/migrations/20260820220000_secure_membership.sql")

class SupabaseContractTests(unittest.TestCase):
    def test_migration_enables_rls_and_public_view(self):
        text = SQL.read_text(encoding="utf-8").lower()
        self.assertIn("enable row level security", text)
        self.assertIn("public_picks", text)
        self.assertIn("is_active_subscriber", text)
        self.assertNotIn("using (true)", text)
```

- [ ] **Step 2: Run and verify missing-file failure**

Run: `python -m unittest tests.test_supabase_contract -v`

Expected: ERROR with `FileNotFoundError`.

- [ ] **Step 3: Create the migration**

The migration must create `subscriptions`, `promo_codes`, and `payment_reviews`; add `visibility`, result-audit, and unit columns to `picks`; enable RLS; expose `public_picks` without premium selection/reasoning; define `is_active_subscriber(auth.uid())`; and grant premium reads only through a security-invoker view/RPC that checks the signed user.

Use this active-state predicate consistently:

```sql
status in ('active', 'trialing')
and current_period_end > now()
```

- [ ] **Step 4: Run the contract and all Python tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260820220000_secure_membership.sql tests/test_supabase_contract.py
git commit -m "feat: add protected membership data contracts"
```

### Task 6: Synchronize the complete Stripe subscription lifecycle

**Files:**
- Create: `supabase/functions/stripe-webhook/subscription.ts`
- Create: `supabase/functions/stripe-webhook/subscription.test.ts`
- Modify: `supabase/functions/stripe-webhook/index.ts`

- [ ] **Step 1: Write failing lifecycle mapping tests**

```typescript
import { assertEquals } from "https://deno.land/std@0.224.0/assert/mod.ts";
import { subscriptionPatch } from "./subscription.ts";

Deno.test("failed invoice removes active access", () => {
  assertEquals(subscriptionPatch("invoice.payment_failed", { customer: "cus_1" }).status, "past_due");
});

Deno.test("deleted subscription is cancelled", () => {
  assertEquals(subscriptionPatch("customer.subscription.deleted", { customer: "cus_1" }).status, "canceled");
});
```

- [ ] **Step 2: Run and verify import failure**

Run: `deno test supabase/functions/stripe-webhook/subscription.test.ts`

Expected: FAIL because `subscription.ts` is absent.

- [ ] **Step 3: Implement deterministic event mapping and idempotent upserts**

```typescript
export function subscriptionPatch(type: string, object: Record<string, unknown>) {
  const statusByType: Record<string, string> = {
    "invoice.paid": "active",
    "invoice.payment_failed": "past_due",
    "customer.subscription.deleted": "canceled",
  };
  return {
    provider: "stripe",
    provider_customer_id: String(object.customer ?? ""),
    provider_subscription_id: String(object.subscription ?? object.id ?? ""),
    status: statusByType[type] ?? String(object.status ?? "incomplete"),
  };
}
```

`index.ts` must keep signature verification, resolve the Supabase user via Checkout metadata/customer mapping, upsert by provider subscription ID, update period end, and never grant permanent access by writing a browser-controlled profile flag.

- [ ] **Step 4: Run Deno tests**

Run: `deno test supabase/functions/stripe-webhook/subscription.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/functions/stripe-webhook
git commit -m "feat: sync Stripe subscription lifecycle"
```

### Task 7: Verify secure core end to end

**Files:**
- Modify: `docs/operations/security-and-payments.md`

- [ ] **Step 1: Run all local tests**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 2: Run Deno webhook tests**

Run: `deno test supabase/functions/stripe-webhook/subscription.test.ts`

Expected: all tests PASS, or document Deno as an unavailable external tool without claiming webhook verification.

- [ ] **Step 3: Document external operations**

`docs/operations/security-and-payments.md` must list exact environment-variable names, provider-console token rotation, Supabase migration deployment, Stripe webhook events, and a rollback procedure that disables checkout without exposing VIP data.

- [ ] **Step 4: Commit**

```bash
git add docs/operations/security-and-payments.md
git commit -m "docs: add secure membership runbook"
```

