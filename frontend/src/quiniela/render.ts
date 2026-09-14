import { formatMexicoDateTime, type QuinielaMatch, type QuinielaSnapshot } from './domain';

export type QuinielaRenderContext = Readonly<{
  isAuthenticated: boolean;
  busy?: boolean;
  message?: string;
  messageKind?: 'status' | 'error' | 'success';
}>;

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function safeHttpsUrl(value: string | null): string {
  if (!value) return '';
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'https:' ? escapeHtml(parsed.toString()) : '';
  } catch {
    return '';
  }
}

function resultLabel(match: QuinielaMatch): string {
  if (match.homeScore === null || match.awayScore === null) return 'Pendiente';
  return `${match.homeScore} – ${match.awayScore}`;
}

function rules(): string {
  return `
    <section class="quiniela-rules" aria-labelledby="quiniela-rules-title">
      <h2 id="quiniela-rules-title">Cómo participar</h2>
      <ol>
        <li>Elige 1, X o 2 y un marcador estimado para cada partido.</li>
        <li>Gana quien tenga más aciertos; desempatan el menor error de marcador y el envío más temprano.</li>
        <li>Hay un ganador semanal y el premio no monetario es de 7 días VIP.</li>
      </ol>
      <p>Promoción gratuita y sin compra necesaria. Cada participante debe ser mayor de 18 años y estar ubicado en México.</p>
      <p class="quiniela-responsible">Participa por entretenimiento. Ningún pronóstico garantiza ganancias y no necesitas realizar apuestas.</p>
    </section>`;
}

function sourceLink(name: string, url: string): string {
  const safeUrl = safeHttpsUrl(url);
  return safeUrl
    ? `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${escapeHtml(name)}</a>`
    : `<span>${escapeHtml(name)}</span>`;
}

function publicMatch(match: QuinielaMatch): string {
  return `
    <article class="quiniela-match">
      <div class="quiniela-match-order">Partido ${match.displayOrder}</div>
      <h3>${escapeHtml(match.homeTeam)} <span>vs</span> ${escapeHtml(match.awayTeam)}</h3>
      <time datetime="${escapeHtml(match.startsAt)}">${escapeHtml(formatMexicoDateTime(match.startsAt))} · hora CDMX</time>
      ${match.resultState === 'pending' ? '' : `<strong class="quiniela-final">Final: ${escapeHtml(resultLabel(match))}</strong>`}
    </article>`;
}

function predictionFields(match: QuinielaMatch): string {
  const id = escapeHtml(match.id);
  return `
    <fieldset class="quiniela-match quiniela-prediction" data-match-id="${id}">
      <legend><span>Partido ${match.displayOrder}</span>${escapeHtml(match.homeTeam)} vs ${escapeHtml(match.awayTeam)}</legend>
      <time datetime="${escapeHtml(match.startsAt)}">${escapeHtml(formatMexicoDateTime(match.startsAt))} · hora CDMX</time>
      <div class="quiniela-prediction-grid">
        <label>Resultado
          <select name="outcome:${id}" required>
            <option value="">Elige</option><option value="1">1 · Local</option>
            <option value="X">X · Empate</option><option value="2">2 · Visitante</option>
          </select>
        </label>
        <label>${escapeHtml(match.homeTeam)}
          <input name="home:${id}" type="number" min="0" max="20" step="1" inputmode="numeric" required />
        </label>
        <label>${escapeHtml(match.awayTeam)}
          <input name="away:${id}" type="number" min="0" max="20" step="1" inputmode="numeric" required />
        </label>
      </div>
    </fieldset>`;
}

function entryForm(snapshot: QuinielaSnapshot, busy: boolean): string {
  const week = snapshot.week!;
  return `
    <form id="quiniela-entry-form" class="quiniela-entry-form">
      <h2>Tu pronóstico</h2>
      ${snapshot.matches.map(predictionFields).join('')}
      <label class="quiniela-attestation">
        <input id="quiniela-attestation" name="attestation" type="checkbox" required />
        Confirmo que soy mayor de 18 años, estoy ubicado en México y acepto los términos ${escapeHtml(week.termsVersion)}.
      </label>
      <p>Consulta el <a href="/terminos.html">reglamento</a> y nuestro <a href="/privacidad.html">aviso de privacidad</a>.</p>
      <button class="quiniela-primary" type="submit" ${busy ? 'disabled' : ''}>${busy ? 'Enviando…' : 'Enviar participación'}</button>
    </form>`;
}

function receipt(snapshot: QuinielaSnapshot): string {
  const receiptValue = snapshot.receipt!;
  const predictions = new Map(receiptValue.predictions.map(value => [value.matchId, value]));
  return `
    <section class="quiniela-receipt" aria-labelledby="quiniela-receipt-title">
      <span class="quiniela-success-mark" aria-hidden="true">✓</span>
      <h2 id="quiniela-receipt-title">Participación registrada</h2>
      <p>Alias público: <strong>${escapeHtml(receiptValue.publicAlias)}</strong></p>
      <p>Enviada: <time datetime="${escapeHtml(receiptValue.submittedAt)}">${escapeHtml(formatMexicoDateTime(receiptValue.submittedAt))} · hora CDMX</time></p>
      <p>Esta participación es definitiva y no puede editarse.</p>
      <div class="quiniela-receipt-list">${snapshot.matches.map(match => {
        const prediction = predictions.get(match.id);
        return `<div><span>${escapeHtml(match.homeTeam)} vs ${escapeHtml(match.awayTeam)}</span><strong>${prediction ? `${prediction.outcome} · ${prediction.predictedHomeScore} – ${prediction.predictedAwayScore}` : '—'}</strong></div>`;
      }).join('')}</div>
    </section>`;
}

function leaderboard(snapshot: QuinielaSnapshot): string {
  if (!snapshot.standings.length) {
    return '<section class="quiniela-leaderboard"><h2>Tabla de posiciones</h2><p>No hubo participaciones válidas esta semana.</p></section>';
  }
  return `
    <section class="quiniela-leaderboard" aria-labelledby="quiniela-leaderboard-title">
      <h2 id="quiniela-leaderboard-title">Tabla de posiciones</h2>
      <div class="quiniela-table-wrap"><table>
        <thead><tr><th>Posición</th><th>Participante</th><th>Aciertos</th><th>Error</th><th>Envío</th></tr></thead>
        <tbody>${snapshot.standings.map(standing => `
          <tr${standing.isWinner ? ' class="quiniela-winner"' : ''}>
            <td>${standing.rank}${standing.isWinner ? ' · Ganador' : ''}</td>
            <td>${escapeHtml(standing.publicAlias)}</td>
            <td>${standing.correctOutcomes}</td><td>${standing.scoreError}</td>
            <td>${escapeHtml(formatMexicoDateTime(standing.submittedAt))}</td>
          </tr>`).join('')}</tbody>
      </table></div>
    </section>`;
}

function createWeekForm(): string {
  return `
    <form id="quiniela-create-week-form" class="quiniela-admin-form">
      <h3>Crear semana</h3>
      <label>Temporada <input name="seasonKey" required maxlength="32" /></label>
      <label>Clave pública <input name="weekKey" required maxlength="32" /></label>
      <label>Título <input name="title" required maxlength="120" /></label>
      <label>Apertura <input name="opensAt" type="datetime-local" required /></label>
      <label>Cierre <input name="closesAt" type="datetime-local" required /></label>
      <label>Versión de términos <input name="termsVersion" required maxlength="64" /></label>
      <label>Fuente <input name="resultSourceName" required maxlength="120" /></label>
      <label>URL fuente <input name="resultSourceUrl" type="url" required pattern="https://.*" /></label>
      <button type="submit">Crear borrador</button>
    </form>`;
}

export function renderAdminPanel(snapshot: QuinielaSnapshot): string {
  if (!snapshot.isAdmin) return '';
  const week = snapshot.week;
  let controls = createWeekForm();
  if (week?.status === 'draft') {
    controls = `
      <form id="quiniela-add-match-form" class="quiniela-admin-form">
        <h3>Agregar partido</h3>
        <label>Orden <input name="displayOrder" type="number" min="1" max="32" required /></label>
        <label>Local <input name="homeTeam" required maxlength="80" /></label>
        <label>Visitante <input name="awayTeam" required maxlength="80" /></label>
        <label>Inicio <input name="startsAt" type="datetime-local" required /></label>
        <button type="submit">Agregar</button>
      </form>
      <button id="quiniela-open-week" type="button">Abrir semana y congelar partidos</button>`;
  } else if (week && (week.status === 'open' || week.status === 'locked' || week.status === 'scored')) {
    controls = snapshot.matches.map(match => `
      <form class="quiniela-admin-form quiniela-result-form" data-match-id="${escapeHtml(match.id)}">
        <h3>${escapeHtml(match.homeTeam)} vs ${escapeHtml(match.awayTeam)}</h3>
        <label>Local <input name="homeScore" type="number" min="0" max="20" required value="${match.homeScore ?? ''}" /></label>
        <label>Visitante <input name="awayScore" type="number" min="0" max="20" required value="${match.awayScore ?? ''}" /></label>
        <label>URL fuente <input name="sourceUrl" type="url" required pattern="https://.*" value="${safeHttpsUrl(match.resultSourceUrl)}" /></label>
        <button type="submit">Confirmar resultado</button>
      </form>`).join('') + (week.status === 'scored'
      ? '<button id="quiniela-award-week" type="button">Otorgar 7 días VIP al ganador</button>'
      : '<button id="quiniela-score-week" type="button">Calificar semana</button>');
  } else if (week?.status === 'awarded') {
    controls = `
      <form id="quiniela-reverse-award-form" class="quiniela-admin-form">
        <label>Motivo auditado <textarea name="reason" minlength="8" maxlength="500" required></textarea></label>
        <button type="submit">Revertir premio</button>
      </form>
      ${createWeekForm()}`;
  }
  return `
    <details class="quiniela-admin">
      <summary>Administración</summary>
      <p>Las acciones son definitivas y quedan atribuidas a tu cuenta administradora.</p>
      ${controls}
    </details>`;
}

export function renderQuinielaState(
  snapshot: QuinielaSnapshot,
  context: QuinielaRenderContext,
): string {
  const message = context.message
    ? `<p class="quiniela-message quiniela-message-${context.messageKind ?? 'status'}" role="status">${escapeHtml(context.message)}</p>`
    : '<p class="quiniela-message" role="status"></p>';
  if (!snapshot.week) {
    return `${message}<section class="quiniela-empty"><h1>La próxima quiniela está en preparación</h1><p>Vuelve pronto para consultar la jornada de Liga MX.</p></section>${renderAdminPanel(snapshot)}`;
  }
  const week = snapshot.week;
  const statusCopy = snapshot.entryState === 'upcoming'
    ? `Abre ${formatMexicoDateTime(week.opensAt)} · hora CDMX`
    : snapshot.entryState === 'open'
      ? `Cierra ${formatMexicoDateTime(week.closesAt)} · hora CDMX`
    : week.status === 'draft' ? 'Borrador administrativo'
      : week.status === 'locked' ? 'Participación cerrada · resultados en revisión'
        : week.status === 'scored' ? 'Resultados calificados'
          : week.status === 'awarded' ? 'Premio otorgado' : 'Participación cerrada';
  const source = sourceLink(week.resultSourceName, week.resultSourceUrl);
  let participation = `<section class="quiniela-closed"><h2>Participación cerrada</h2><p>Los pronósticos ya no pueden modificarse ni enviarse.</p></section>`;
  if (snapshot.receipt) participation = receipt(snapshot);
  else if (snapshot.entryState === 'upcoming') {
    participation = `<section class="quiniela-closed"><h2>Aún no abre</h2><p>Podrás enviar tu participación desde ${escapeHtml(formatMexicoDateTime(week.opensAt))} · hora CDMX.</p></section>`;
  } else if (snapshot.entryState === 'open' && !context.isAuthenticated) {
    participation = '<section class="quiniela-signin"><h2>Participa con tu cuenta</h2><p>Inicia sesión o crea una cuenta gratuita para registrar una sola participación.</p><button id="quiniela-login" class="quiniela-primary" type="button">Iniciar sesión</button></section>';
  } else if (snapshot.entryState === 'open' && context.isAuthenticated && snapshot.matches.length) {
    participation = entryForm(snapshot, Boolean(context.busy));
  } else if (week.status === 'draft') {
    participation = '<section class="quiniela-closed"><h2>Borrador</h2><p>Esta semana todavía no es pública.</p></section>';
  }
  return `
    ${message}
    <header class="quiniela-hero">
      <span>Quiniela semanal · Liga MX</span>
      <h1>${escapeHtml(week.title)}</h1>
      <p>${escapeHtml(statusCopy)}</p>
      <div class="quiniela-meta"><span>Abre: ${escapeHtml(formatMexicoDateTime(week.opensAt))}</span><span>Términos: ${escapeHtml(week.termsVersion)}</span></div>
    </header>
    ${rules()}
    <section class="quiniela-slate" aria-labelledby="quiniela-slate-title">
      <div class="quiniela-section-heading"><h2 id="quiniela-slate-title">Partidos participantes</h2><span>Fuente: ${source}</span></div>
      <div class="quiniela-match-list">${snapshot.matches.length ? snapshot.matches.map(publicMatch).join('') : '<p>No hay partidos cargados.</p>'}</div>
    </section>
    ${participation}
    ${week.status === 'scored' || week.status === 'awarded' ? leaderboard(snapshot) : ''}
    ${renderAdminPanel(snapshot)}`;
}

export function renderQuinielaShell(root: HTMLElement): void {
  document.body.classList.add('quiniela-route');
  root.innerHTML = `
    <a class="skip-link" href="#quiniela-state">Saltar al contenido</a>
    <div class="quiniela-page">
      <nav class="quiniela-nav" aria-label="Navegación de quiniela">
        <a class="quiniela-brand" href="/"><img src="/logo.jpg" alt="" width="48" height="48" /><span><strong>Rey Taco Picks</strong><small>Quiniela Liga MX</small></span></a>
        <a href="/">Volver a los picks</a>
      </nav>
      <main id="quiniela-state" class="quiniela-main" aria-live="polite"><section class="quiniela-loading"><h1>Cargando quiniela…</h1></section></main>
      <footer class="quiniela-footer"><p>Promoción gratuita +18 para México. Premio sin valor en efectivo.</p><p><a href="/terminos.html">Términos</a> · <a href="/privacidad.html">Privacidad</a> · <a href="mailto:soporte@reytacopicks.com">Soporte</a></p></footer>
    </div>
    <dialog id="quiniela-auth-dialog" class="auth-dialog">
      <form method="dialog" class="dialog-close"><button aria-label="Cerrar" value="cancel">×</button></form>
      <h2>Cuenta Rey Taco</h2>
      <div class="auth-tabs"><button type="button" class="active" data-quiniela-auth-mode="login">Entrar</button><button type="button" data-quiniela-auth-mode="register">Crear cuenta</button></div>
      <form id="quiniela-auth-form">
        <label>Correo electrónico <input name="email" type="email" autocomplete="email" required /></label>
        <label>Contraseña <input name="password" type="password" autocomplete="current-password" minlength="6" required /></label>
        <button class="quiniela-primary" type="submit">Iniciar sesión</button>
      </form>
      <p id="quiniela-auth-message" role="status"></p>
    </dialog>`;
}

export function renderQuinielaUnavailable(root: HTMLElement): void {
  const state = root.querySelector<HTMLElement>('#quiniela-state') ?? root;
  state.innerHTML = '<section class="quiniela-empty"><h1>La quiniela está temporalmente no disponible</h1><p>Intenta de nuevo en unos minutos.</p><a href="/">Volver al inicio</a></section>';
}
