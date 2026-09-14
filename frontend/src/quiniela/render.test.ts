import { beforeEach, describe, expect, it } from 'vitest';
import type { QuinielaSnapshot } from './domain';
import {
  renderAdminPanel,
  renderQuinielaShell,
  renderQuinielaState,
  renderQuinielaUnavailable,
} from './render';

const snapshot: QuinielaSnapshot = {
  week: {
    id: 'week-id', seasonKey: 'apertura-2026', weekKey: 'j7', title: 'Jornada 7',
    status: 'open', opensAt: '2026-09-10T00:00:00Z', closesAt: '2026-09-13T17:00:00Z',
    termsVersion: '2026-09-12', resultSourceName: 'Liga MX',
    resultSourceUrl: 'https://example.com/results', resultsCheckedAt: null,
  },
  matches: [{
    id: 'match-id', displayOrder: 1, homeTeam: 'América', awayTeam: 'Pumas',
    startsAt: '2026-09-13T18:00:00Z', homeScore: null, awayScore: null,
    resultState: 'pending', resultSourceUrl: null,
  }],
  receipt: null,
  standings: [],
  entryState: 'open',
  isAdmin: false,
};

describe('quiniela rendering', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="app"></div>';
    document.body.className = '';
  });

  it('mounts an isolated semantic shell', () => {
    const root = document.getElementById('app')!;
    renderQuinielaShell(root);
    expect(document.body.classList.contains('quiniela-route')).toBe(true);
    expect(root.querySelector('#quiniela-state')).not.toBeNull();
    expect(root.querySelector('a[href="/"]')?.textContent).toContain('Rey Taco');
  });

  it('renders an unavailable state without exposing technical detail', () => {
    const root = document.getElementById('app')!;
    renderQuinielaShell(root);
    renderQuinielaUnavailable(root);
    expect(root.textContent).toContain('temporalmente no disponible');
    expect(root.textContent).not.toContain('Supabase');
  });

  it('shows rules and sign-in guidance to a signed-out visitor', () => {
    const html = renderQuinielaState(snapshot, { isAuthenticated: false });
    document.getElementById('app')!.innerHTML = html;

    expect(document.body.textContent).toContain('Jornada 7');
    expect(document.body.textContent).toContain('7 días VIP');
    expect(document.body.textContent).toContain('mayor de 18 años');
    expect(document.body.textContent).toContain('sin compra necesaria');
    expect(document.querySelector('#quiniela-login')).not.toBeNull();
    expect(document.querySelector('#quiniela-entry-form')).toBeNull();
  });

  it('renders one complete accessible prediction form for a signed-in visitor', () => {
    document.getElementById('app')!.innerHTML = renderQuinielaState(snapshot, { isAuthenticated: true });

    expect(document.querySelector('#quiniela-entry-form')).not.toBeNull();
    expect(document.querySelector('[name="outcome:match-id"]')).not.toBeNull();
    expect(document.querySelector('[name="home:match-id"]')).not.toBeNull();
    expect(document.querySelector('[name="away:match-id"]')).not.toBeNull();
    expect(document.querySelector<HTMLInputElement>('#quiniela-attestation')?.required).toBe(true);
    expect(document.querySelector('a[href="/privacidad.html"]')).not.toBeNull();
  });

  it('renders an immutable receipt instead of the form', () => {
    const submitted: QuinielaSnapshot = {
      ...snapshot,
      receipt: {
        entryId: 'entry-id', publicAlias: 'Jugador-ABCDEF123456',
        submittedAt: '2026-09-12T12:00:00Z', termsVersion: '2026-09-12',
        predictions: [{ matchId: 'match-id', outcome: '1', predictedHomeScore: 2, predictedAwayScore: 1 }],
      },
    };
    const html = renderQuinielaState(submitted, { isAuthenticated: true });
    document.getElementById('app')!.innerHTML = html;

    expect(document.body.textContent).toContain('Participación registrada');
    expect(document.body.textContent).toContain('Jugador-ABCDEF123456');
    expect(document.body.textContent).toContain('2 – 1');
    expect(document.querySelector('#quiniela-entry-form')).toBeNull();
  });

  it('uses the server entry state to hide the form before opening and after closing', () => {
    const upcoming: QuinielaSnapshot = { ...snapshot, entryState: 'upcoming' };
    document.getElementById('app')!.innerHTML = renderQuinielaState(upcoming, { isAuthenticated: true });
    expect(document.body.textContent).toContain('Aún no abre');
    expect(document.querySelector('#quiniela-entry-form')).toBeNull();

    const closed: QuinielaSnapshot = { ...snapshot, entryState: 'closed' };
    document.getElementById('app')!.innerHTML = renderQuinielaState(closed, { isAuthenticated: true });
    expect(document.body.textContent).toContain('Participación cerrada');
    expect(document.querySelector('#quiniela-entry-form')).toBeNull();
  });

  it('shows a read-only leaderboard and winner after scoring', () => {
    const scored: QuinielaSnapshot = {
      ...snapshot,
      week: { ...snapshot.week!, status: 'scored', resultsCheckedAt: '2026-09-15T03:00:00Z' },
      standings: [{
        rank: 1, entryId: 'entry-id', publicAlias: 'Jugador-ABCDEF123456',
        correctOutcomes: 1, scoreError: 0, submittedAt: '2026-09-12T12:00:00Z', isWinner: true,
      }],
    };
    document.getElementById('app')!.innerHTML = renderQuinielaState(scored, { isAuthenticated: false });

    expect(document.body.textContent).toContain('Tabla de posiciones');
    expect(document.body.textContent).toContain('Ganador');
    expect(document.body.textContent).toContain('Liga MX');
    expect(document.querySelector('#quiniela-entry-form')).toBeNull();
  });

  it('escapes content and refuses unsafe source links', () => {
    const hostile: QuinielaSnapshot = {
      ...snapshot,
      week: {
        ...snapshot.week!, title: '<img src=x onerror=alert(1)>',
        resultSourceName: '<script>alert(1)</script>', resultSourceUrl: 'javascript:alert(1)',
      },
      matches: [{ ...snapshot.matches[0]!, homeTeam: '<img onerror=alert(1)>', awayTeam: '<b>Pumas</b>' }],
    };
    const html = renderQuinielaState(hostile, { isAuthenticated: false });

    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img onerror');
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain('&lt;img');
  });

  it('renders admin controls only for administrators and never renders account identifiers', () => {
    expect(renderAdminPanel(snapshot)).toBe('');
    const adminHtml = renderAdminPanel({ ...snapshot, isAdmin: true });

    expect(adminHtml).toContain('Administración');
    expect(adminHtml).toContain('quiniela-result-form');
    expect(adminHtml).not.toContain('private@example.com');
    expect(adminHtml).not.toContain('user_id');
  });

  it('lets an administrator create the next week after awarding the current one', () => {
    const awarded = renderAdminPanel({
      ...snapshot,
      isAdmin: true,
      week: { ...snapshot.week!, status: 'awarded' },
    });

    expect(awarded).toContain('quiniela-reverse-award-form');
    expect(awarded).toContain('quiniela-create-week-form');
  });

  it('lets an administrator correct results before awarding a rescored week', () => {
    const scored = renderAdminPanel({
      ...snapshot,
      isAdmin: true,
      week: { ...snapshot.week!, status: 'scored' },
    });

    expect(scored).toContain('quiniela-result-form');
    expect(scored).toContain('quiniela-award-week');
  });
});
