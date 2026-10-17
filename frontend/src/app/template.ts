export function applicationTemplate(): string {
  return `
    <a class="skip-link" href="#contenido">Saltar al contenido</a>
    <div id="telegram-mini-app" class="telegram-app-host hidden"></div>
    <div class="site-shell">
      <header class="site-header">
        <a class="brand" href="#inicio" aria-label="Rey Taco Picks, inicio">
          <img src="/logo-flow.webp" onerror="this.onerror=null;this.src='/logo.jpg';" alt="Rey Taco Picks" width="54" height="54" />
          <span><strong>Rey Taco Picks</strong><small>Inteligencia Artificial · Datos &amp; +EV</small></span>
        </a>
        <nav class="desktop-nav" aria-label="Navegación principal">
          <a href="#picks">Picks del día</a>
          <a href="#escalera">Reto Escalera</a>
          <a href="#resultados">Resultados</a>
          <a href="/analisis/">Análisis</a>
          <a href="/aprende/">Guías</a>
          <a href="/metodologia.html">Metodología</a>
          <a href="/acerca-de.html">Quiénes Somos</a>
        </nav>
        <div class="header-actions">
          <button class="text-button" id="login-button" type="button">Iniciar sesión</button>
          <button class="vip-button" id="vip-button" data-plan="monthly" type="button">VIP $349/mes</button>
        </div>
      </header>

      <section class="salmo-wrap" id="salmo" aria-label="Salmo del día">
        <div id="daily-verse-container"></div>
      </section>

      <main id="contenido">
        <section class="hero" id="inicio">
          <div class="hero-copy">
            <span class="eyebrow">🌮👑 Para aficionados recreativos en México · Hora CDMX · Motor IA Multi-Deporte</span>
            <h1>Picks deportivos claros.<br /><em>Resultados públicos.</em></h1>
            <p>Recibe selecciones analizadas con modelos matemáticos (+EV, xG, EPA y Net Rating) sin promesas de dinero fácil: puedes perder y ningún resultado está garantizado.</p>
            <ul class="hero-benefits">
              <li>Hasta 6 picks por ventana, solo cuando cumplen los filtros de valor esperado (+EV)</li>
              <li>Cobertura multi-deporte: Fútbol, Liga MX, NBA, NFL, Tenis y MLB</li>
              <li>Alertas en tiempo real por Telegram e historial público auditado con SHA-256</li>
              <li>Cancela tu membresía cuando quieras desde tu panel</li>
            </ul>
            <div class="hero-actions">
              <button class="primary-button" id="vip-primary-button" type="button">Suscribirme a VIP — $349 MXN/mes</button>
              <a class="secondary-button" href="#picks">Ver picks gratis</a>
            </div>
            <div class="trust-line"><span>+18</span><span>Juego responsable</span><span>Registro completo SHA-256</span><span>Esmeralda &amp; Oro IA</span></div>
          </div>
          <aside class="proof-card" aria-labelledby="proof-title">
            <div class="proof-title-row"><h2 id="proof-title">Resultados reales</h2><span class="verified-badge">✓ Calculados</span></div>
            <div class="metric-grid">
              <div><strong id="metric-record">—</strong><span>Récord</span></div>
              <div><strong id="metric-units">—</strong><span>Unidades</span></div>
              <div><strong id="metric-roi">—</strong><span>ROI</span></div>
            </div>
            <div class="streak-badge-container">
              <span class="streak-pill" id="metric-streak">🔥 Racha: Calculando...</span>
            </div>
            <p>Las métricas se obtienen automáticamente del historial verificado. También mostramos pérdidas, nulos y pendientes con total transparencia.</p>
          </aside>
        </section>

        <section class="content-section" id="picks" aria-labelledby="picks-title">
          <div class="section-heading">
            <div><span class="section-kicker">Selección pública · Algoritmo Multi-Deporte</span><h2 id="picks-title">La mesa está servida</h2></div>
            <span id="picks-updated" class="updated-label">Consultando datos…</span>
          </div>
          <div class="filter-row" id="filter-row" aria-label="Filtrar picks">
            <button class="filter-chip active" type="button" data-filter="all">🎯 Todos</button>
            <button class="filter-chip" type="button" data-filter="ligamx">⚽ Liga MX</button>
            <button class="filter-chip" type="button" data-filter="futbol">🌎 Fútbol</button>
            <button class="filter-chip" type="button" data-filter="nba">🏀 NBA</button>
            <button class="filter-chip" type="button" data-filter="nfl">🏈 NFL</button>
            <button class="filter-chip" type="button" data-filter="tenis">🎾 Tenis</button>
            <button class="filter-chip" type="button" data-filter="mlb">⚾ MLB</button>
          </div>
          <div id="picks-container" class="pick-grid" aria-live="polite">
            <div class="state-card">
              <strong>Sincronizando cartelera analítica del día…</strong>
              <span>Nuestro motor cuantitativo evalúa distribuciones de Poisson bivariado (Fútbol), Net Rating ajustado por ritmo (NBA), EPA por jugada (NFL), eficiencia de saque/quiebre (Tenis) y FIP/xFIP de abridores (MLB) en las ventanas oficiales de las 06:00, 12:00 y 18:00 hrs CDMX.</span>
            </div>
          </div>
        </section>

        <section class="content-section ladder-section" id="escalera" aria-labelledby="ladder-title">
          <div class="section-heading">
            <div>
              <span class="section-kicker">🔥 Especial de Fin de Semana · Viernes a Domingo</span>
              <h2 id="ladder-title">Reto Escalera de Fin de Semana</h2>
            </div>
            <span class="updated-label ladder-schedule-badge">Viernes a Domingo · 12:00 PM – 9:00 PM CDMX</span>
          </div>
          <p class="ladder-intro">
            Cada fin de semana (viernes, sábado y domingo) nuestro motor de Inteligencia Artificial selecciona una progresión matemática de baja varianza diseñada paso a paso. El <strong>Paso 1 es siempre 100% gratuito y público</strong> para toda la comunidad; los <strong>Pasos 2 y 3 son exclusivos del Canal VIP</strong>.
          </p>
          <div class="ladder-grid">
            <article class="ladder-card ladder-step-free">
              <div class="ladder-card-head">
                <span class="ladder-step-tag">PASO 1 · ABIERTO</span>
                <span class="ladder-status-open">🔓 100% GRATIS</span>
              </div>
              <h3>Base de Alta Probabilidad</h3>
              <div class="ladder-progression">$100 MXN → <strong>$190 MXN</strong></div>
              <p>Selección principal del día con respaldo estadístico (+EV) publicada de forma abierta en la web, Reels oficiales y canal gratuito de Telegram.</p>
              <a class="secondary-button ladder-cta" href="#picks">Ver Paso 1 en cartelera</a>
            </article>

            <article class="ladder-card ladder-step-vip">
              <div class="ladder-card-head">
                <span class="ladder-step-tag">PASO 2 · INTERMEDIO</span>
                <span class="ladder-status-locked">🔒 EXCLUSIVO VIP</span>
              </div>
              <h3>Aceleración Controlada</h3>
              <div class="ladder-progression">$190 MXN → <strong>$360 MXN</strong></div>
              <p>Segunda selección con filtro de correlación positiva y validación de alineaciones confirmadas. Disponible únicamente dentro de la cartera privada VIP.</p>
              <a class="primary-button ladder-cta" href="#vip">Desbloquear Paso 2 en VIP</a>
            </article>

            <article class="ladder-card ladder-step-vip">
              <div class="ladder-card-head">
                <span class="ladder-step-tag">PASO 3 · META FINAL</span>
                <span class="ladder-status-locked">🔒 EXCLUSIVO VIP</span>
              </div>
              <h3>Cierre de Campeonato</h3>
              <div class="ladder-progression">$360 MXN → <strong>$700+ MXN</strong></div>
              <p>Tercer escalón de alta eficiencia cuantitativa auditado en tiempo real. Reservado exclusivamente para miembros con pase semanal ($129) o mensual ($349).</p>
              <a class="primary-button ladder-cta" href="#vip">Desbloquear Paso 3 en VIP</a>
            </article>
          </div>
        </section>

        <section class="content-section" id="investigacion" aria-labelledby="research-title">
          <div class="section-heading">
            <div>
              <span class="section-kicker">Periodismo de Datos y Ciencia Deportiva</span>
              <h2 id="research-title">Investigación Cuantitativa y Modelos Estadísticos</h2>
            </div>
            <a href="/analisis/" class="updated-label" style="text-decoration: underline;">Ver archivo completo →</a>
          </div>
          <p class="research-lead">
            En <strong>Rey Taco Picks</strong> fundamentamos cada proyección en literatura econométrica, distribuciones de probabilidad y auditoría criptográfica SHA-256. Explora nuestros estudios técnicos sobre microestructura de mercados, modelos de goles esperados (xG) y gestión de capital:
          </p>
          <div class="pick-grid" style="margin-top: 16px;">
            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>MODELADO TÁCTICO</span><span>LIGA MX</span></div>
              <h3><a href="/analisis/analisis-tactico-tiros-de-esquina-liga-mx.html" style="color: inherit; text-decoration: none;">Análisis Táctico de Tiros de Esquina en la Liga MX y su Predictibilidad Cuantitativa</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Estudio empírico sobre cómo el ancho ofensivo, los centros laterales por partido y el ritmo de transición superan a la posesión del balón como predictores del mercado de córners (Over/Under 9.5) en el fútbol mexicano.</p>
              <div class="pick-footer"><a href="/analisis/analisis-tactico-tiros-de-esquina-liga-mx.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 8 min</span></div>
            </article>

            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>MÉTRICAS AVANZADAS</span><span>FÚTBOL</span></div>
              <h3><a href="/analisis/modelos-goles-esperados-xg-futbol-mexicano.html" style="color: inherit; text-decoration: none;">Modelos de Goles Esperados (xG) en el Fútbol Mexicano: Metodología y Aplicación</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Cómo evaluamos la calidad real de las oportunidades de gol mediante coordenadas espaciales, ángulo de disparo y el factor de altitud en estadios de la Liga MX para detectar regresiones a la media antes que el mercado.</p>
              <div class="pick-footer"><a href="/analisis/modelos-goles-esperados-xg-futbol-mexicano.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 9 min</span></div>
            </article>

            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>MATEMÁTICA FINANCIERA</span><span>GESTIÓN DE RIESGO</span></div>
              <h3><a href="/analisis/gestion-bankroll-criterio-kelly-adaptativo.html" style="color: inherit; text-decoration: none;">Gestión de Bankroll con el Criterio de Kelly Adaptativo: Protección de Capital</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Desarrollo matemático de la fórmula de John L. Kelly Jr. adaptada a fracciones conservadoras (1/4 de Kelly) para minimizar el riesgo de ruina ante rachas de varianza negativa en pronósticos deportivos.</p>
              <div class="pick-footer"><a href="/analisis/gestion-bankroll-criterio-kelly-adaptativo.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 7 min</span></div>
            </article>

            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>PROBABILIDAD COMPUESTA</span><span>ESTRATEGIA</span></div>
              <h3><a href="/analisis/correlacion-estadistica-parlays-valor-esperado.html" style="color: inherit; text-decoration: none;">Correlación Estadística en Parlays: Cómo Construir Combinados con Valor (+EV)</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Por qué las combinaciones tradicionales multiplican el margen de la casa (Overround) en contra del usuario, y cómo las selecciones de baja varianza con correlación positiva preservan la ventaja matemática.</p>
              <div class="pick-footer"><a href="/analisis/correlacion-estadistica-parlays-valor-esperado.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 8 min</span></div>
            </article>

            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>MICROESTRUCTURA</span><span>MERCADOS</span></div>
              <h3><a href="/analisis/cuotas-sharp-vs-casas-recreativas-mexico.html" style="color: inherit; text-decoration: none;">Cuotas Sharp vs. Operadores Recreativos en México: Detección de Desfases y CLV</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Análisis comparativo entre formadores de mercado internacionales (Pinnacle) y plataformas recreativas en México, explicando cómo se originan las ineficiencias de precio y cómo se mide el Closing Line Value (CLV).</p>
              <div class="pick-footer"><a href="/analisis/cuotas-sharp-vs-casas-recreativas-mexico.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 10 min</span></div>
            </article>

            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>PROPS DE JUGADOR</span><span>ESTADÍSTICA</span></div>
              <h3><a href="/analisis/remates-a-puerta-volumen-ofensivo-delanteros.html" style="color: inherit; text-decoration: none;">Mercado de Remates a Puerta en la Liga MX: Análisis de Volumen por Delantero</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Metodología para modelar proposiciones individuales de futbolistas (Shots on Target) utilizando distribuciones de Poisson truncadas, minutos efectivos en cancha y emparejamientos defensivos.</p>
              <div class="pick-footer"><a href="/analisis/remates-a-puerta-volumen-ofensivo-delanteros.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 8 min</span></div>
            </article>

            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>TRANSPARENCIA</span><span>CRIPTOGRAFÍA</span></div>
              <h3><a href="/analisis/auditoria-criptografica-sha256-pronosticos.html" style="color: inherit; text-decoration: none;">Auditoría Criptográfica SHA-256 en Pronósticos Deportivos: Inmutabilidad Total</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Implementación técnica de funciones hash criptográficas y sellos de tiempo previos al partido para garantizar que ningún registro histórico pueda ser alterado, editado o eliminado retroactivamente.</p>
              <div class="pick-footer"><a href="/analisis/auditoria-criptografica-sha256-pronosticos.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 6 min</span></div>
            </article>

            <article class="pick-card public-pick-card">
              <div class="pick-meta"><span>PSICOLOGÍA COGNITIVA</span><span>ESTADÍSTICA</span></div>
              <h3><a href="/analisis/falacia-del-apostador-varianza-muestras-cortas.html" style="color: inherit; text-decoration: none;">La Falacia del Apostador y la Varianza en Muestras Cortas: Análisis de Rachas</a></h3>
              <p style="font-size: 0.9rem; line-height: 1.5; opacity: 0.9;">Demostración mediante simulaciones de Monte Carlo de por qué los sistemas con ventaja real experimentan rachas adversas temporales y cómo distinguir el ruido estadístico del sesgo de modelo.</p>
              <div class="pick-footer"><a href="/analisis/falacia-del-apostador-varianza-muestras-cortas.html" style="font-weight: 700;">Leer artículo completo →</a><span>Lectura: 7 min</span></div>
            </article>
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
              <tbody id="history-container"><tr><td colspan="5">Consultando bitácora histórica auditada con SHA-256…</td></tr></tbody>
            </table>
          </div>
          <section class="victory-wall-section" aria-labelledby="victory-title">
            <div class="victory-heading">
              <div><span class="section-kicker">Evidencia original</span><h3 id="victory-title">Muro de victorias</h3></div>
              <span>Fotografías recibidas por el bot, sin recrear el boleto.</span>
            </div>
            <div id="victory-wall" aria-live="polite"><div class="victory-empty">Cargando galería de evidencias verificadas…</div></div>
          </section>
        </section>

        <section class="education-grid" id="metodo" aria-label="Contenido educativo">
          <article class="featured-article">
            <span class="section-kicker">Educación Estadística y Gestión de Riesgo</span>
            <h2>Cómo interpretar una probabilidad implícita sin perseguir pérdidas</h2>
            <p>Una cuota deportiva no es una promesa: representa una probabilidad implícita ajustada por el margen operativo del mercado (Overround). Define una unidad fija de capital, evita aumentar el tamaño de asignación tras una racha adversa y consulta siempre nuestras <a href="/aprende/" style="color: inherit; text-decoration: underline;">Guías de Probabilidad</a>.</p>
            <ul>
              <li>Usa un presupuesto recreativo estrictamente separado de tus finanzas personales.</li>
              <li>Aplica el Criterio de Kelly Fraccional (1.0% a 2.0% por selección).</li>
              <li>Detente de inmediato si el análisis deportivo deja de ser entretenimiento recreativo.</li>
            </ul>
          </article>
          <aside class="calculator-card" id="calculadora" aria-labelledby="calc-title">
            <span class="section-kicker">Gestión de capital</span>
            <h2 id="calc-title">Calculadora de Banca</h2>
            <p class="calculator-desc">Calcula el tamaño de unidad matemáticamente seguro según tu capital recreativo disponible.</p>
            <label for="bankroll">Banca disponible ($ MXN)</label>
            <input id="bankroll" type="number" min="0" step="100" value="2000" />
            <label for="risk-percent">Riesgo por pick (Tamaño de Unidad)</label>
            <select id="risk-percent">
              <option value="1">🛡️ 1.0% Conservador</option>
              <option value="1.5" selected>⚖️ 1.5% Oficial Rey Taco</option>
              <option value="2">🚀 2.0% Dinámico</option>
            </select>
            <div class="calc-results-grid">
              <div class="calc-box"><span>1 Unidad (1 U)</span><strong id="unit-val-display">$30 MXN</strong></div>
              <div class="calc-box"><span>Tope por Pick</span><strong id="max-stake-display">$60 MXN</strong></div>
            </div>
            <output id="stake-result">Unidad sugerida: $30 MXN</output>
          </aside>
        </section>

        <aside class="ad-container hidden" id="ad-slot-feed" data-ad-unit aria-label="Publicidad"></aside>

        <section class="vip-section" id="vip" aria-labelledby="vip-title">
          <div><span class="eyebrow">Acceso VIP · Esmeralda &amp; Oro</span><h2 id="vip-title">Elige cómo entrar a la cartera completa</h2><p>Acceso a picks premium multi-deporte, Pasos 2 y 3 del Reto Escalera, alertas en vivo y canal privado. Cancela cuando quieras. Ningún resultado está garantizado.</p></div>
          <div class="pricing-grid">
            <article class="pricing-card"><span class="pricing-label">Pase flexible</span><h3>7 días VIP</h3><strong>$129 MXN</strong><p>Una semana de acceso a la cartera completa y Reto Escalera de fin de semana.</p><button class="secondary-button" id="vip-weekly-button" data-plan="weekly" type="button">Entrar por 7 días</button></article>
            <article class="pricing-card pricing-card-featured"><span class="pricing-label">Más elegido</span><h3>VIP mensual</h3><strong>$349 MXN/mes</strong><p>Acceso continuo, todos los deportes y alertas privadas cada ventana.</p><button class="primary-button" id="vip-checkout-button" data-plan="monthly" type="button">Suscribirme al VIP</button></article>
          </div>
        </section>

        <section id="vip-access-panel" class="access-panel hidden" aria-labelledby="vip-access-title">
          <div><span class="section-kicker">Acceso confirmado</span><h2 id="vip-access-title">Tu membresía VIP está activa</h2><p>Solicita el acceso al canal privado desde el bot oficial. Nunca mostramos ni almacenamos una invitación permanente.</p></div>
          <div class="access-destinations"><a id="miniapp-access-link" class="secondary-button" href="/?view=telegram">Abrir Mini App</a><a id="telegram-access-link" class="primary-button hidden">Solicitar acceso por Telegram</a></div>
        </section>

        <p id="checkout-status" class="checkout-status" aria-live="polite"></p>

        <section class="legal-grid" aria-label="Información y juego responsable">
          <article><h2>Método y límites</h2><p>Analizamos datos estadísticos y precios de mercado disponibles. Un modelo cuantitativo puede fallar y las líneas cambian constantemente. Publicamos el resultado de cada pick para evitar sesgos de supervivencia.</p></article>
          <article><h2>Juego responsable</h2><p>Solo para mayores de 18 años. Establece límites estrictos y nunca arriesgues recursos necesarios. Si sientes pérdida de control, solicita orientación gratuita en la Línea de la Vida (800 911 2000).</p></article>
          <article><h2>Privacidad y Google AdSense</h2><p>Usamos tu correo para la cuenta y membresía. No vendemos datos personales. Este portal utiliza Google AdSense para mostrar publicidad contextual conforme a nuestro <a href="/privacidad.html">Aviso de Privacidad</a>.</p></article>
        </section>
      </main>

      <footer class="site-footer">
        <div class="brand footer-brand"><img src="/logo-flow.webp" onerror="this.onerror=null;this.src='/logo.jpg';" alt="" width="44" height="44" /><span><strong>Rey Taco Picks</strong><small>Periodismo de Datos · México</small></span></div>
        <p>Contenido informativo, estadístico y recreativo. +18. No garantizamos ganancias.</p>
        <p>© 2026 Rey Taco Picks · <a href="/analisis/">Análisis</a> · <a href="/aprende/">Guías</a> · <a href="/metodologia.html">Metodología</a> · <a href="/acerca-de.html">Quiénes Somos</a> · <a href="/privacidad.html">Privacidad</a> · <a href="/terminos.html">Términos</a> · <a href="mailto:soporte@reytacopicks.com">Soporte</a></p>
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
      <div class="stripe-trust-note">
        <strong>Pagos 100% seguros con Stripe</strong>
        <span>Activación instantánea tras confirmar tu suscripción o pase semanal. Acceso directo e inmediato a la cartera VIP.</span>
      </div>
    </dialog>

    <dialog id="victory-dialog" class="victory-dialog" aria-labelledby="victory-dialog-title">
      <div class="dialog-close"><button id="victory-dialog-close" type="button" aria-label="Cerrar evidencia">×</button></div>
      <h2 id="victory-dialog-title">Evidencia original</h2>
      <img id="victory-dialog-image" alt="Boleto ganador verificado en tamaño completo" />
    </dialog>

    <div class="cookie-notice hidden" id="cookie-notice" role="region" aria-label="Aviso de privacidad"><p>Usamos almacenamiento esencial para tu sesión, medición anónima y anuncios contextuales de Google AdSense.</p><button id="cookie-accept" type="button">Entendido</button></div>
  `;
}
