export function applicationTemplate(): string {
  return `
    <a class="skip-link" href="#contenido">Saltar al contenido</a>
    <div class="site-shell">
      <header class="site-header">
        <a class="brand" href="#inicio" aria-label="Rey Taco Picks, inicio">
          <img src="/logo.jpg" alt="" width="54" height="54" />
          <span><strong>Rey Taco Picks</strong><small>Predicciones deportivas</small></span>
        </a>
        <nav class="desktop-nav" aria-label="Navegación principal">
          <a href="#picks">Picks del día</a>
          <a href="#resultados">Resultados</a>
          <a href="#salmo">Salmo del día</a>
          <a href="#metodo">Cómo funciona</a>
        </nav>
        <div class="header-actions">
          <button class="text-button" id="login-button" type="button">Iniciar sesión</button>
          <button class="vip-button" id="vip-button" type="button">VIP $299</button>
        </div>
      </header>

      <section class="salmo-wrap" id="salmo" aria-label="Salmo del día">
        <div id="daily-verse-container"></div>
      </section>

      <main id="contenido">
        <section class="hero" id="inicio">
          <div class="hero-copy">
            <span class="eyebrow">Picks para México · Hora CDMX</span>
            <h1>Los picks van <em>primero.</em><br />El historial también.</h1>
            <p>Análisis directo, cuotas claras y resultados públicos. Sin promesas de dinero fácil ni resultados garantizados.</p>
            <div class="hero-actions">
              <a class="primary-button" href="#picks">Ver pick gratis</a>
              <a class="secondary-button" id="telegram-cta" href="https://t.me/ReyTacoPicksFree" target="_blank" rel="noopener noreferrer">Unirme a Telegram</a>
            </div>
            <div class="trust-line"><span>+18</span><span>Juego responsable</span><span>Registro completo</span></div>
          </div>
          <aside class="proof-card" aria-labelledby="proof-title">
            <div class="proof-title-row"><h2 id="proof-title">Resultados reales</h2><span class="verified-badge">✓ Calculados</span></div>
            <div class="metric-grid">
              <div><strong id="metric-record">—</strong><span>Récord</span></div>
              <div><strong id="metric-units">—</strong><span>Unidades</span></div>
              <div><strong id="metric-roi">—</strong><span>ROI</span></div>
            </div>
            <p>Las métricas se obtienen del historial. También mostramos pérdidas, nulos y pendientes.</p>
          </aside>
        </section>

        <section class="content-section" id="picks" aria-labelledby="picks-title">
          <div class="section-heading">
            <div><span class="section-kicker">Selección pública</span><h2 id="picks-title">La mesa está servida</h2></div>
            <span id="picks-updated" class="updated-label">Consultando datos…</span>
          </div>
          <div class="filter-row" id="filter-row" aria-label="Filtrar picks">
            <button class="filter-chip active" type="button" data-filter="all">🎯 Todos</button>
            <button class="filter-chip" type="button" data-filter="ligamx">⚽ Liga MX</button>
            <button class="filter-chip" type="button" data-filter="futbol">🌎 Fútbol</button>
            <button class="filter-chip" type="button" data-filter="mlb">⚾ MLB</button>
          </div>
          <div id="picks-container" class="pick-grid" aria-live="polite">
            <div class="state-card">Cargando la selección gratuita…</div>
          </div>
        </section>

        <section class="content-section history-section" id="resultados" aria-labelledby="history-title">
          <div class="section-heading">
            <div><span class="section-kicker">Transparencia · Resultados verificados</span><h2 id="history-title">Los picks que recibió VIP</h2></div>
            <div class="history-filters" id="history-filters">
              <button class="mini-filter active" type="button" data-status="all">Todos</button>
              <button class="mini-filter" type="button" data-status="ganado">Ganados</button>
              <button class="mini-filter" type="button" data-status="perdido">Perdidos</button>
            </div>
          </div>
          <div class="history-table-wrap">
            <table>
              <thead><tr><th>Fecha</th><th>Partido</th><th>Pick</th><th>Cuota</th><th>Estado</th></tr></thead>
              <tbody id="history-container"><tr><td colspan="5">Cargando historial…</td></tr></tbody>
            </table>
          </div>
          <section class="victory-wall-section" aria-labelledby="victory-title">
            <div class="victory-heading">
              <div><span class="section-kicker">Evidencia original</span><h3 id="victory-title">Muro de victorias</h3></div>
              <span>Fotografías recibidas por el bot, sin recrear el boleto.</span>
            </div>
            <div id="victory-wall" aria-live="polite"><div class="victory-empty">Cargando evidencias…</div></div>
          </section>
        </section>

        <section class="education-grid" id="metodo" aria-label="Contenido educativo">
          <article class="featured-article">
            <span class="section-kicker">Aprende antes de apostar</span>
            <h2>Cómo leer una cuota sin perseguir pérdidas</h2>
            <p>Una cuota no es una promesa: representa una probabilidad implícita. Define una unidad fija, evita aumentar apuestas para recuperar y registra cada selección.</p>
            <ul><li>Usa una banca separada.</li><li>No arriesgues dinero necesario.</li><li>Detente si apostar deja de ser entretenimiento.</li></ul>
          </article>
          <aside class="calculator-card">
            <span class="section-kicker">Herramienta gratuita</span>
            <h2>Calculadora de unidad</h2>
            <label for="bankroll">Banca disponible (MXN)</label>
            <input id="bankroll" type="number" min="0" step="100" value="1000" />
            <label for="risk-percent">Riesgo por pick</label>
            <select id="risk-percent"><option value="1">1% conservador</option><option value="2">2% moderado</option><option value="3">3% alto</option></select>
            <output id="stake-result">Unidad sugerida: $10 MXN</output>
          </aside>
        </section>

        <aside class="ad-container hidden" id="ad-slot-feed" data-ad-unit aria-label="Publicidad"></aside>

        <section class="vip-section" id="vip" aria-labelledby="vip-title">
          <div><span class="eyebrow">Membresía mensual</span><h2 id="vip-title">La cartera completa, protegida de verdad</h2><p>Acceso a picks premium, alertas y canal privado. Cancela cuando quieras. No garantizamos ganancias.</p></div>
          <div class="vip-price"><strong>$299</strong><span>MXN / mes</span><button class="primary-button" id="vip-checkout-button" type="button">Quiero ser VIP</button></div>
        </section>

        <section class="legal-grid" aria-label="Información y juego responsable">
          <article><h2>Método y límites</h2><p>Analizamos datos y cuotas disponibles. Un modelo puede fallar y las líneas cambian. Publicamos el resultado de cada pick para evitar sesgos.</p></article>
          <article><h2>Juego responsable</h2><p>Solo para mayores de 18 años. Establece límites y nunca apuestes para cubrir deudas. Si pierdes el control, busca ayuda profesional.</p></article>
          <article><h2>Privacidad</h2><p>Usamos tu correo para la cuenta y membresía. No vendemos datos personales. Puedes solicitar acceso o eliminación escribiendo a soporte.</p></article>
        </section>
      </main>

      <footer class="site-footer">
        <div class="brand footer-brand"><img src="/logo.jpg" alt="" width="44" height="44" /><span><strong>Rey Taco Picks</strong><small>México</small></span></div>
        <p>Contenido informativo y recreativo. +18. No garantizamos ganancias.</p>
        <p>© 2026 Rey Taco Picks · <a href="/privacidad.html">Privacidad</a> · <a href="/terminos.html">Términos</a> · <a href="mailto:soporte@reytacopicks.com">Soporte</a></p>
      </footer>

      <nav class="mobile-nav" aria-label="Navegación móvil">
        <a href="#picks"><span>🎯</span>Picks</a>
        <a href="#resultados"><span>✓</span>Resultados</a>
        <a href="#salmo"><span>✦</span>Salmo</a>
        <a href="#vip"><span>♛</span>VIP</a>
      </nav>
    </div>

    <dialog id="auth-dialog" class="auth-dialog">
      <form method="dialog" class="dialog-close"><button aria-label="Cerrar" value="cancel">×</button></form>
      <div class="dialog-brand"><span>♛</span><div><strong>Cuenta Rey Taco</strong><small>Acceso seguro con Supabase</small></div></div>
      <div class="auth-tabs"><button type="button" class="active" data-auth-mode="login">Entrar</button><button type="button" data-auth-mode="register">Crear cuenta</button></div>
      <form id="auth-form">
        <label for="auth-email">Correo electrónico</label><input id="auth-email" type="email" autocomplete="email" required />
        <label for="auth-password">Contraseña</label><input id="auth-password" type="password" autocomplete="current-password" minlength="6" required />
        <button class="primary-button" id="auth-submit" type="submit">Iniciar sesión</button>
      </form>
      <div class="account-tools hidden" id="account-tools">
        <strong>Tu cuenta</strong>
        <span>Vincula Telegram para que el bot reconozca tu membresía.</span>
        <button class="secondary-button" id="telegram-link-button" type="button">Vincular Telegram</button>
        <form id="promo-form">
          <label for="promo-code">Código promocional</label>
          <div><input id="promo-code" type="text" autocomplete="off" maxlength="64" placeholder="Tu código" /><button type="submit">Canjear</button></div>
        </form>
        <button class="text-button" id="signout-button" type="button">Cerrar sesión</button>
      </div>
      <p id="auth-message" class="form-message" aria-live="polite"></p>
      <div class="spei-note"><strong>¿Prefieres SPEI?</strong><span>Escríbenos por WhatsApp. Todo comprobante se revisa manualmente.</span><a href="https://wa.me/525639331102" target="_blank" rel="noopener noreferrer">Abrir WhatsApp</a></div>
    </dialog>

    <dialog id="victory-dialog" class="victory-dialog" aria-labelledby="victory-dialog-title">
      <div class="dialog-close"><button id="victory-dialog-close" type="button" aria-label="Cerrar evidencia">×</button></div>
      <h2 id="victory-dialog-title">Evidencia original</h2>
      <img id="victory-dialog-image" alt="Boleto ganador verificado en tamaño completo" />
    </dialog>

    <div class="cookie-notice hidden" id="cookie-notice" role="region" aria-label="Aviso de privacidad"><p>Usamos almacenamiento esencial para tu sesión y medición anónima de uso.</p><button id="cookie-accept" type="button">Entendido</button></div>
  `;
}
