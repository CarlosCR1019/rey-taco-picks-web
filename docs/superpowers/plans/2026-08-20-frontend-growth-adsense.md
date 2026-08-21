# Frontend, Growth, and AdSense Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved Mexico-first, picks-first responsive frontend with permanent Salmo, honest metrics, session-based VIP UX, SEO content, and policy-conscious AdSense placement.

**Architecture:** Split the current monolithic entry point into pure domain modules, Supabase data/auth services, and a DOM application shell. Public and premium data contracts are separate; rendering consumes typed safe objects and never grants access from browser storage.

**Tech Stack:** Vite 8, TypeScript 6, Supabase JS, Vitest, jsdom, CSS, PWA web manifest, Google AdSense.

---

### Task 1: Install the frontend test harness

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/domain/metrics.test.ts`

- [ ] **Step 1: Add test and typecheck scripts plus dev dependencies**

```json
{
  "scripts": {
    "dev": "vite",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit",
    "build": "npm run typecheck && vite build"
  },
  "devDependencies": {
    "jsdom": "^26.1.0",
    "vitest": "^3.2.4"
  }
}
```

- [ ] **Step 2: Write a failing metrics import test**

```typescript
import { describe, expect, it } from 'vitest';
import { calculatePerformance } from './metrics';

describe('calculatePerformance', () => {
  it('includes losses when calculating record and units', () => {
    expect(calculatePerformance([
      { estado: 'ganado', cuota: 2 },
      { estado: 'perdido', cuota: 1.8 },
      { estado: 'pendiente', cuota: 2.1 },
    ])).toEqual({ wins: 1, losses: 1, pending: 1, units: 0, roi: 0 });
  });
});
```

- [ ] **Step 3: Install and run the focused test**

Run: `npm install && npm test -- src/domain/metrics.test.ts`

Expected: FAIL because `metrics.ts` does not exist.

- [ ] **Step 4: Commit the red test harness**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/test/setup.ts frontend/src/domain/metrics.test.ts
git commit -m "test: add frontend behavior harness"
```

### Task 2: Implement typed picks and honest metrics

**Files:**
- Create: `frontend/src/domain/picks.ts`
- Create: `frontend/src/domain/metrics.ts`
- Create: `frontend/src/domain/picks.test.ts`
- Modify: `frontend/src/domain/metrics.test.ts`

- [ ] **Step 1: Add failing public-data and status tests**

```typescript
import { describe, expect, it } from 'vitest';
import { publicPick, statusLabel } from './picks';

describe('public picks', () => {
  it('drops premium selection and reasoning', () => {
    expect(publicPick({ visibility: 'premium', pick: 'VIP secret', razonamiento: 'secret' }))
      .toEqual({ visibility: 'premium' });
  });

  it('labels losses and review states', () => {
    expect(statusLabel('perdido')).toBe('Perdido');
    expect(statusLabel('revision_pendiente')).toBe('En revisión');
  });
});
```

- [ ] **Step 2: Run both tests and verify missing imports**

Run: `npm test -- src/domain`

Expected: FAIL for missing `picks.ts` and `metrics.ts`.

- [ ] **Step 3: Implement minimal pure modules**

```typescript
export type PickStatus = 'pendiente' | 'ganado' | 'perdido' | 'void' | 'revision_pendiente';
export type PickVisibility = 'public' | 'premium';

export function publicPick<T extends Record<string, unknown>>(pick: T) {
  if (pick.visibility !== 'premium') return { ...pick };
  const { pick: _selection, razonamiento: _reason, ...safe } = pick;
  return safe;
}

export function statusLabel(status: PickStatus) {
  return ({ pendiente: 'Pendiente', ganado: 'Ganado', perdido: 'Perdido', void: 'Nulo', revision_pendiente: 'En revisión' })[status];
}
```

```typescript
type ResultRow = { estado: string; cuota: number | string };
export function calculatePerformance(rows: ResultRow[]) {
  const wins = rows.filter(row => row.estado === 'ganado').length;
  const losses = rows.filter(row => row.estado === 'perdido').length;
  const pending = rows.filter(row => !['ganado', 'perdido', 'void'].includes(row.estado)).length;
  const units = rows.reduce((sum, row) => row.estado === 'ganado' ? sum + Number(row.cuota) - 1 : row.estado === 'perdido' ? sum - 1 : sum, 0);
  const settled = wins + losses;
  return { wins, losses, pending, units: Number(units.toFixed(2)), roi: settled ? Number((units / settled * 100).toFixed(1)) : 0 };
}
```

- [ ] **Step 4: Run tests and verify green**

Run: `npm test -- src/domain`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain
git commit -m "feat: derive transparent pick performance"
```

### Task 3: Create session-authorized data services

**Files:**
- Create: `frontend/src/lib/supabase.ts`
- Create: `frontend/src/services/membership.ts`
- Create: `frontend/src/services/picks.ts`
- Create: `frontend/src/services/membership.test.ts`
- Modify: `frontend/src/main.ts`

- [ ] **Step 1: Write a failing membership-state test**

```typescript
import { describe, expect, it } from 'vitest';
import { isMembershipActive } from './membership';

describe('membership', () => {
  it('requires an active status and a future period end', () => {
    expect(isMembershipActive({ status: 'active', current_period_end: '2099-01-01T00:00:00Z' })).toBe(true);
    expect(isMembershipActive({ status: 'canceled', current_period_end: '2099-01-01T00:00:00Z' })).toBe(false);
    expect(isMembershipActive({ status: 'active', current_period_end: '2020-01-01T00:00:00Z' })).toBe(false);
  });
});
```

- [ ] **Step 2: Run and verify missing-module failure**

Run: `npm test -- src/services/membership.test.ts`

Expected: FAIL because `membership.ts` is absent.

- [ ] **Step 3: Implement fail-closed configuration and services**

```typescript
import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
export const supabase = url && anonKey ? createClient(url, anonKey) : null;
```

```typescript
export type Membership = { status: string; current_period_end: string | null };
export function isMembershipActive(value: Membership | null): boolean {
  return Boolean(value && ['active', 'trialing'].includes(value.status) && value.current_period_end && Date.parse(value.current_period_end) > Date.now());
}
```

`services/picks.ts` queries `public_picks` anonymously. It queries the protected premium RPC only when `supabase.auth.getSession()` returns a signed session. Remove the hardcoded Supabase fallback key, admin email/password path, browser VIP codes, and localStorage membership restoration from `main.ts`.

- [ ] **Step 4: Run test, typecheck, and security scan**

Run: `npm test && npm run typecheck && python -m unittest tests.test_source_security -v`

Expected: PASS after all known browser bypass strings are removed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib frontend/src/services frontend/src/main.ts
git commit -m "security: authorize VIP from signed sessions"
```

### Task 4: Implement the approved picks-first application shell

**Files:**
- Create: `frontend/src/app/template.ts`
- Create: `frontend/src/app/render.ts`
- Create: `frontend/src/app/render.test.ts`
- Modify: `frontend/src/main.ts`
- Replace: `frontend/src/style.css`

- [ ] **Step 1: Write failing render-contract tests**

```typescript
import { beforeEach, describe, expect, it } from 'vitest';
import { renderShell } from './render';

describe('approved shell', () => {
  beforeEach(() => document.body.innerHTML = '<div id="app"></div>');

  it('puts salmo and picks before advertising', () => {
    renderShell();
    const html = document.getElementById('app')!.innerHTML;
    expect(html.indexOf('id="daily-verse-container"')).toBeLessThan(html.indexOf('id="picks-container"'));
    expect(html.indexOf('id="picks-container"')).toBeLessThan(html.indexOf('data-ad-unit'));
  });

  it('exposes four mobile navigation destinations', () => {
    renderShell();
    expect(document.querySelectorAll('.mobile-nav a')).toHaveLength(4);
  });
});
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/app/render.test.ts`

Expected: FAIL because render modules are absent.

- [ ] **Step 3: Implement the approved DOM order and visual tokens**

`template.ts` returns semantic header/nav/main/footer markup in this order: brand header; permanent Salmo; hero and calls to action; verified performance; daily free/public picks; history; educational article; optional ad; VIP offer; legal footer; mobile navigation. `render.ts` mounts it and wires navigation without inline handlers.

Define these CSS tokens and use them consistently:

```css
:root {
  --wine: #7f0f22;
  --red: #c51c32;
  --gold: #f2a91e;
  --light-gold: #ffd56a;
  --cream: #fff4de;
  --espresso: #24120c;
  --green: #769b36;
}
```

Add `overflow-x: clip` only as a final containment rule; all grid/flex children must use `min-width: 0`, mobile filters scroll inside their own container, and media rules cover 900, 600, 390, 360, and 320 pixels.

- [ ] **Step 4: Run render tests and build**

Run: `npm test -- src/app && npm run build`

Expected: PASS and a successful Vite build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app frontend/src/main.ts frontend/src/style.css
git commit -m "feat: build approved picks-first experience"
```

### Task 5: Make Salmo permanent and accessible

**Files:**
- Modify: `frontend/src/dailyVerse.ts`
- Create: `frontend/src/dailyVerse.test.ts`

- [ ] **Step 1: Write failing permanence tests**

```typescript
import { beforeEach, describe, expect, it } from 'vitest';
import { initDailyVerseBanner } from './dailyVerse';

describe('daily Salmo', () => {
  beforeEach(() => document.body.innerHTML = '<div id="daily-verse-container"></div>');

  it('has no dismiss action and remains in navigation', () => {
    initDailyVerseBanner();
    expect(document.querySelector('#btn-dismiss-verse')).toBeNull();
    expect(document.querySelector('.verse-banner')).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run and verify expected failure**

Run: `npm test -- src/dailyVerse.test.ts`

Expected: FAIL because the dismiss button exists.

- [ ] **Step 3: Remove dismissal state and improve controls**

Remove the sessionStorage early return, close button, and close handler. Retain deterministic daily selection, next, and copy. Add visible text/`aria-label` attributes and a `role="region" aria-label="Salmo del día"` wrapper.

- [ ] **Step 4: Run tests**

Run: `npm test -- src/dailyVerse.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/dailyVerse.ts frontend/src/dailyVerse.test.ts
git commit -m "feat: keep Salmo del dia permanently visible"
```

### Task 6: Render complete history and derived statistics

**Files:**
- Create: `frontend/src/app/history.ts`
- Create: `frontend/src/app/history.test.ts`
- Modify: `frontend/src/main.ts`

- [ ] **Step 1: Write a failing history test**

```typescript
import { describe, expect, it } from 'vitest';
import { visibleHistory } from './history';

describe('history', () => {
  it('keeps wins, losses, pending, and review rows', () => {
    const rows = ['ganado', 'perdido', 'pendiente', 'revision_pendiente'].map((estado, id) => ({ id, estado }));
    expect(visibleHistory(rows).map(row => row.estado)).toEqual(['ganado', 'perdido', 'pendiente', 'revision_pendiente']);
  });
});
```

- [ ] **Step 2: Run and verify missing-module failure**

Run: `npm test -- src/app/history.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement history without invented fallback wins**

```typescript
export function visibleHistory<T extends { estado: string }>(rows: T[]): T[] {
  return rows.filter(row => ['ganado', 'perdido', 'pendiente', 'void', 'revision_pendiente'].includes(row.estado));
}
```

Query all supported states, render accessible status badges, calculate the summary through `calculatePerformance`, and show an honest empty/error state when Supabase is unavailable. Delete hardcoded winning history.

- [ ] **Step 4: Run tests and typecheck**

Run: `npm test && npm run typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/history.ts frontend/src/app/history.test.ts frontend/src/main.ts
git commit -m "fix: publish the complete pick record"
```

### Task 7: Add SEO, policy content, analytics, and guarded AdSense

**Files:**
- Create: `frontend/src/services/ads.ts`
- Create: `frontend/src/services/ads.test.ts`
- Create: `frontend/src/services/analytics.ts`
- Modify: `frontend/index.html`
- Create: `frontend/public/robots.txt`
- Create: `frontend/public/sitemap.xml`
- Modify: `frontend/public/ads.txt`

- [ ] **Step 1: Write failing AdSense guards**

```typescript
import { describe, expect, it } from 'vitest';
import { adConfig } from './ads';

describe('AdSense', () => {
  it('does not render an incomplete unit', () => {
    expect(adConfig('')).toBeNull();
    expect(adConfig('1234567890')).toEqual({ client: 'ca-pub-2697347675028991', slot: '1234567890' });
  });
});
```

- [ ] **Step 2: Run and verify missing-module failure**

Run: `npm test -- src/services/ads.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement guarded ads and Mexico metadata**

```typescript
export function adConfig(slot: string | undefined) {
  const value = slot?.trim();
  return value ? { client: 'ca-pub-2697347675028991', slot: value } : null;
}
```

Set `lang="es-MX"`, brand colors, Mexico-focused title/description, canonical/OG metadata, and JSON-LD in `index.html`. Render/push an ad only when `VITE_ADSENSE_SLOT` is configured, after substantial educational content, and outside Salmo/VIP/checkout. `analytics.ts` emits the six approved conversion event names to `dataLayer` without email or user IDs.

- [ ] **Step 4: Run tests and build**

Run: `npm test && npm run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services frontend/index.html frontend/public/robots.txt frontend/public/sitemap.xml frontend/public/ads.txt
git commit -m "feat: add policy-conscious acquisition surfaces"
```

### Task 8: Replace generic icons and verify responsive delivery

**Files:**
- Modify: `frontend/public/favicon.svg`
- Modify: `frontend/public/manifest.json`
- Create: `docs/operations/frontend-release.md`
- Modify: `dist/**`

- [ ] **Step 1: Create brand-native icon assets**

Use the existing logo as the source and generate optimized header/Open Graph/PWA sizes. The SVG favicon must use the approved wine/gold crown-and-taco mark, not Vite artwork. Update manifest name, description, theme/background colors, and icon paths.

- [ ] **Step 2: Run the full frontend gate**

Run: `npm test && npm run typecheck && npm run build`

Expected: all tests PASS and build succeeds.

- [ ] **Step 3: Rebuild root distribution**

Run from repository root: `npm run build`

Expected: `dist/index.html` references only the latest hashed JS/CSS plus branded icons.

- [ ] **Step 4: Perform browser viewport checks**

At desktop, 390, 360, and 320 CSS pixels, verify:

```javascript
({
  viewport: window.innerWidth,
  documentWidth: document.documentElement.scrollWidth,
  overflow: document.documentElement.scrollWidth > window.innerWidth,
  salmoDismiss: Boolean(document.querySelector('#btn-dismiss-verse')),
  mobileNavItems: document.querySelectorAll('.mobile-nav a').length
})
```

Expected at every viewport: `overflow: false`, `salmoDismiss: false`, `mobileNavItems: 4`.

- [ ] **Step 5: Document release and commit**

`docs/operations/frontend-release.md` records required build variables, Supabase migration dependency, AdSense external approval, smoke-test URLs, and rollback steps.

```bash
git add frontend dist docs/operations/frontend-release.md
git commit -m "release: deliver Mexico-first Rey Taco experience"
```

