import { beforeEach, describe, expect, it, vi } from 'vitest';
import { initQuiniela, type QuinielaAppClient } from './controller';

const wireSnapshot = {
  week: {
    id: 'week-id', season_key: 'apertura-2026', week_key: 'j7', title: 'Jornada 7',
    status: 'open', opens_at: '2026-09-10T00:00:00Z', closes_at: '2026-09-13T17:00:00Z',
    terms_version: '2026-09-12', result_source_name: 'Liga MX',
    result_source_url: 'https://example.com/results', results_checked_at: null,
  },
  matches: [{
    id: '11111111-1111-4111-8111-111111111111', display_order: 1,
    home_team: 'América', away_team: 'Pumas', starts_at: '2026-09-13T18:00:00Z',
    home_score: null, away_score: null, result_state: 'pending', result_source_url: null,
  }],
  receipt: null,
  standings: [],
  entry_state: 'open',
  is_admin: false,
};

function fakeClient(options: { authenticated?: boolean; submitError?: string } = {}) {
  const rpc = vi.fn(async (name: string) => {
    if (name === 'get_current_quiniela') return { data: wireSnapshot, error: null };
    if (name === 'submit_quiniela_entry' && options.submitError) {
      return { data: null, error: { message: options.submitError } };
    }
    if (name === 'submit_quiniela_entry') return {
      data: {
        entry_id: 'entry-id', public_alias: 'Jugador-ABCDEF123456',
        submitted_at: '2026-09-12T12:00:00Z',
      },
      error: null,
    };
    return { data: true, error: null };
  });
  const unsubscribe = vi.fn();
  const client: QuinielaAppClient = {
    rpc,
    auth: {
      getSession: vi.fn(async () => ({
        data: { session: options.authenticated ? { user: { id: 'account-id' } } : null },
      })),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe } } })),
      signInWithPassword: vi.fn(async () => ({ error: null })),
      signUp: vi.fn(async () => ({ error: null })),
    },
  };
  return { client, rpc, unsubscribe };
}

async function submitFilledForm(): Promise<void> {
  const outcome = document.querySelector<HTMLSelectElement>('[name^="outcome:"]')!;
  const home = document.querySelector<HTMLInputElement>('[name^="home:"]')!;
  const away = document.querySelector<HTMLInputElement>('[name^="away:"]')!;
  const attestation = document.querySelector<HTMLInputElement>('#quiniela-attestation')!;
  outcome.value = '1';
  home.value = '2';
  away.value = '1';
  attestation.checked = true;
  document.querySelector<HTMLFormElement>('#quiniela-entry-form')!
    .dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
}

describe('quiniela controller', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="app"></div>';
    document.body.className = '';
  });

  it('loads the route and emits a private viewed event once', async () => {
    const { client } = fakeClient();
    const analytics = vi.fn();

    const cleanup = await initQuiniela(document.getElementById('app')!, client, analytics);

    expect(document.body.textContent).toContain('Jornada 7');
    expect(analytics).toHaveBeenCalledWith('quiniela_viewed', { surface: 'web', week_key: 'j7' });
    cleanup();
  });

  it('emits started only on the first prediction interaction', async () => {
    const { client } = fakeClient({ authenticated: true });
    const analytics = vi.fn();
    await initQuiniela(document.getElementById('app')!, client, analytics);
    const outcome = document.querySelector<HTMLSelectElement>('[name^="outcome:"]')!;

    outcome.dispatchEvent(new Event('change', { bubbles: true }));
    outcome.dispatchEvent(new Event('change', { bubbles: true }));

    expect(analytics.mock.calls.filter(call => call[0] === 'quiniela_started')).toEqual([
      ['quiniela_started', { surface: 'web', week_key: 'j7' }],
    ]);
  });

  it('submits a complete entry and emits submitted only after success', async () => {
    const { client, rpc } = fakeClient({ authenticated: true });
    const analytics = vi.fn();
    await initQuiniela(document.getElementById('app')!, client, analytics);

    await submitFilledForm();

    await vi.waitFor(() => expect(document.body.textContent).toContain('Participación registrada'));
    expect(rpc).toHaveBeenCalledWith('submit_quiniela_entry', expect.objectContaining({
      p_week_id: 'week-id', p_terms_version: '2026-09-12', p_adult_in_mexico: true,
    }));
    expect(analytics).toHaveBeenCalledWith('quiniela_submitted', { surface: 'web', week_key: 'j7' });
  });

  it('preserves the filled form and sanitizes a failed submission', async () => {
    const { client } = fakeClient({ authenticated: true, submitError: 'quiniela_closed password=secret' });
    const analytics = vi.fn();
    await initQuiniela(document.getElementById('app')!, client, analytics);

    await submitFilledForm();

    await vi.waitFor(() => expect(document.body.textContent).toContain('ya cerró'));
    expect(document.querySelector<HTMLInputElement>('[name^="home:"]')?.value).toBe('2');
    expect(document.body.textContent).not.toContain('password=secret');
    expect(analytics.mock.calls.some(call => call[0] === 'quiniela_submitted')).toBe(false);
  });

  it('opens the existing account dialog for signed-out participation', async () => {
    const { client } = fakeClient();
    await initQuiniela(document.getElementById('app')!, client, vi.fn());
    const dialog = document.querySelector<HTMLDialogElement>('#quiniela-auth-dialog')!;
    dialog.showModal = vi.fn();

    document.querySelector<HTMLButtonElement>('#quiniela-login')!.click();

    expect(dialog.showModal).toHaveBeenCalledTimes(1);
  });
});
