import type { ConversionEvent } from '../services/analytics';
import { trackConversion } from '../services/analytics';
import {
  publicErrorMessage,
  validatePredictions,
  type QuinielaPrediction,
  type QuinielaReceipt,
  type QuinielaSnapshot,
} from './domain';
import {
  QuinielaServiceError,
  addMatch,
  awardWeek,
  confirmResult,
  createWeek,
  loadQuiniela,
  openWeek,
  reverseAward,
  scoreWeek,
  submitEntry,
  type QuinielaClient,
} from './service';
import { renderQuinielaShell, renderQuinielaState, renderQuinielaUnavailable } from './render';

type AuthSession = Readonly<{ user: Readonly<{ id: string }> }>;
type AuthResponse = Promise<Readonly<{ error: unknown | null }>>;

export type QuinielaAppClient = QuinielaClient & Readonly<{
  auth: Readonly<{
    getSession: () => Promise<Readonly<{ data: Readonly<{ session: AuthSession | null }> }>>;
    onAuthStateChange: (
      callback: (event: string, session: AuthSession | null) => void,
    ) => Readonly<{ data: Readonly<{ subscription: Readonly<{ unsubscribe: () => void }> }> }>;
    signInWithPassword: (credentials: { email: string; password: string }) => AuthResponse;
    signUp: (credentials: { email: string; password: string }) => AuthResponse;
  }>;
}>;

type Analytics = (
  event: ConversionEvent,
  properties?: { surface: 'web'; week_key: string },
) => void;

function formValue(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === 'string' ? value.trim() : '';
}
function mexicoLocalToIso(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return value;
  return new Date(`${value}:00-06:00`).toISOString();
}

function serviceMessage(error: unknown): string {
  return publicErrorMessage(error instanceof QuinielaServiceError ? error.code : 'quiniela_unavailable');
}

export async function initQuiniela(
  root: HTMLElement,
  client: QuinielaAppClient,
  analytics: Analytics = trackConversion,
): Promise<() => void> {
  renderQuinielaShell(root);
  let snapshot: QuinielaSnapshot | null = null;
  let session: AuthSession | null = null;
  let started = false;
  let disposed = false;

  const analyticsProperties = () => snapshot?.week
    ? { surface: 'web' as const, week_key: snapshot.week.weekKey }
    : null;

  const render = (message?: string, kind?: 'status' | 'error' | 'success'): void => {
    if (!snapshot || disposed) return;
    const stateRoot = root.querySelector<HTMLElement>('#quiniela-state');
    if (!stateRoot) return;
    stateRoot.innerHTML = renderQuinielaState(snapshot, {
      isAuthenticated: Boolean(session), message, messageKind: kind,
    });
  };

  const showMessage = (message: string, kind: 'status' | 'error' | 'success' = 'status'): void => {
    const target = root.querySelector<HTMLElement>('.quiniela-message');
    if (!target) return;
    target.textContent = message;
    target.className = `quiniela-message quiniela-message-${kind}`;
  };

  const refresh = async (): Promise<void> => {
    try {
      snapshot = await loadQuiniela(client);
      render();
      const properties = analyticsProperties();
      if (properties) analytics('quiniela_viewed', properties);
    } catch {
      if (!disposed) renderQuinielaUnavailable(root);
    }
  };

  try {
    const response = await client.auth.getSession();
    session = response.data.session;
  } catch {
    session = null;
  }
  await refresh();

  const authSubscription = client.auth.onAuthStateChange((_event, nextSession) => {
    session = nextSession;
    void refresh();
  });

  const onChange = (event: Event): void => {
    const target = event.target as HTMLElement;
    if (started || !target.closest('#quiniela-entry-form')) return;
    if (!target.matches('select[name^="outcome:"], input[name^="home:"], input[name^="away:"]')) return;
    const properties = analyticsProperties();
    if (!properties) return;
    started = true;
    analytics('quiniela_started', properties);
  };

  const onClick = (event: Event): void => {
    const target = event.target as HTMLElement;
    if (target.closest('#quiniela-login')) {
      root.querySelector<HTMLDialogElement>('#quiniela-auth-dialog')?.showModal();
      return;
    }
    const authMode = target.closest<HTMLButtonElement>('[data-quiniela-auth-mode]');
    if (authMode) {
      root.querySelectorAll('[data-quiniela-auth-mode]').forEach(item => item.classList.toggle('active', item === authMode));
      const register = authMode.dataset.quinielaAuthMode === 'register';
      const button = root.querySelector<HTMLButtonElement>('#quiniela-auth-form button[type="submit"]');
      const password = root.querySelector<HTMLInputElement>('#quiniela-auth-form input[name="password"]');
      if (button) button.textContent = register ? 'Crear cuenta' : 'Iniciar sesión';
      if (password) password.autocomplete = register ? 'new-password' : 'current-password';
      return;
    }
    if (!snapshot?.week || !snapshot.isAdmin) return;
    const weekId = snapshot.week.id;
    const action = target.closest<HTMLButtonElement>('#quiniela-open-week, #quiniela-score-week, #quiniela-award-week');
    if (!action) return;
    action.disabled = true;
    const request = action.id === 'quiniela-open-week' ? openWeek(client, weekId)
      : action.id === 'quiniela-score-week' ? scoreWeek(client, weekId)
        : awardWeek(client, weekId);
    void request.then(refresh).catch(error => {
      action.disabled = false;
      showMessage(serviceMessage(error), 'error');
    });
  };

  const submitParticipantEntry = async (formElement: HTMLFormElement): Promise<void> => {
    if (!snapshot?.week || !session) return;
    const values = new FormData(formElement);
    const predictions: QuinielaPrediction[] = snapshot.matches.map(match => ({
      matchId: match.id,
      outcome: formValue(values, `outcome:${match.id}`) as QuinielaPrediction['outcome'],
      predictedHomeScore: Number(formValue(values, `home:${match.id}`)),
      predictedAwayScore: Number(formValue(values, `away:${match.id}`)),
    }));
    const validation = validatePredictions(snapshot.matches, predictions);
    if (!validation.ok) {
      showMessage(publicErrorMessage(validation.code), 'error');
      return;
    }
    const attestation = values.get('attestation') === 'on';
    if (!attestation) {
      showMessage(publicErrorMessage('quiniela_attestation_required'), 'error');
      return;
    }
    const button = formElement.querySelector<HTMLButtonElement>('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.textContent = 'Enviando…';
    }
    try {
      const submitted: QuinielaReceipt = await submitEntry(
        client, snapshot.week.id, snapshot.week.termsVersion, attestation, predictions,
      );
      snapshot = { ...snapshot, receipt: submitted };
      render('Tu participación quedó registrada.', 'success');
      const properties = analyticsProperties();
      if (properties) analytics('quiniela_submitted', properties);
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.textContent = 'Enviar participación';
      }
      showMessage(serviceMessage(error), 'error');
    }
  };

  const submitAdminForm = async (formElement: HTMLFormElement): Promise<boolean> => {
    if (!snapshot?.isAdmin) return false;
    const values = new FormData(formElement);
    if (formElement.id === 'quiniela-create-week-form') {
      await createWeek(client, {
        seasonKey: formValue(values, 'seasonKey'), weekKey: formValue(values, 'weekKey'),
        title: formValue(values, 'title'), opensAt: mexicoLocalToIso(formValue(values, 'opensAt')),
        closesAt: mexicoLocalToIso(formValue(values, 'closesAt')),
        termsVersion: formValue(values, 'termsVersion'),
        resultSourceName: formValue(values, 'resultSourceName'),
        resultSourceUrl: formValue(values, 'resultSourceUrl'),
      });
      return true;
    }
    if (!snapshot.week) return false;
    if (formElement.id === 'quiniela-add-match-form') {
      await addMatch(client, {
        weekId: snapshot.week.id,
        displayOrder: Number(formValue(values, 'displayOrder')),
        homeTeam: formValue(values, 'homeTeam'), awayTeam: formValue(values, 'awayTeam'),
        startsAt: mexicoLocalToIso(formValue(values, 'startsAt')),
      });
      return true;
    }
    if (formElement.classList.contains('quiniela-result-form')) {
      await confirmResult(client, {
        matchId: formElement.dataset.matchId ?? '',
        homeScore: Number(formValue(values, 'homeScore')),
        awayScore: Number(formValue(values, 'awayScore')),
        sourceUrl: formValue(values, 'sourceUrl'),
      });
      return true;
    }
    if (formElement.id === 'quiniela-reverse-award-form') {
      await reverseAward(client, snapshot.week.id, formValue(values, 'reason'));
      return true;
    }
    return false;
  };

  const onSubmit = (event: SubmitEvent): void => {
    const formElement = event.target as HTMLFormElement;
    if (!formElement.matches('form')) return;
    if (formElement.id === 'quiniela-entry-form') {
      event.preventDefault();
      void submitParticipantEntry(formElement);
      return;
    }
    if (formElement.id === 'quiniela-auth-form') {
      event.preventDefault();
      const values = new FormData(formElement);
      const credentials = { email: formValue(values, 'email'), password: formValue(values, 'password') };
      const register = root.querySelector('[data-quiniela-auth-mode="register"].active') !== null;
      void (register ? client.auth.signUp(credentials) : client.auth.signInWithPassword(credentials)).then(response => {
        const target = root.querySelector<HTMLElement>('#quiniela-auth-message');
        if (target) target.textContent = response.error
          ? 'No pudimos completar el acceso. Revisa tus datos.'
          : register ? 'Revisa tu correo para confirmar la cuenta.' : 'Sesión iniciada.';
        if (!response.error && !register) root.querySelector<HTMLDialogElement>('#quiniela-auth-dialog')?.close();
      });
      return;
    }
    if (formElement.closest('.quiniela-admin')) {
      event.preventDefault();
      void submitAdminForm(formElement).then(handled => {
        if (handled) return refresh();
      }).catch(error => showMessage(serviceMessage(error), 'error'));
    }
  };

  root.addEventListener('change', onChange);
  root.addEventListener('click', onClick);
  root.addEventListener('submit', onSubmit as EventListener);

  return () => {
    disposed = true;
    root.removeEventListener('change', onChange);
    root.removeEventListener('click', onClick);
    root.removeEventListener('submit', onSubmit as EventListener);
    authSubscription.data.subscription.unsubscribe();
  };
}
