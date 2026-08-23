(function(){let e=document.createElement(`link`).relList;if(e&&e.supports&&e.supports(`modulepreload`))return;for(let e of document.querySelectorAll(`link[rel="modulepreload"]`))n(e);new MutationObserver(e=>{for(let t of e)if(t.type===`childList`)for(let e of t.addedNodes)e.tagName===`LINK`&&e.rel===`modulepreload`&&n(e)}).observe(document,{childList:!0,subtree:!0});function t(e){let t={};return e.integrity&&(t.integrity=e.integrity),e.referrerPolicy&&(t.referrerPolicy=e.referrerPolicy),t.credentials=e.crossOrigin===`use-credentials`?`include`:e.crossOrigin===`anonymous`?`omit`:`same-origin`,t}function n(e){if(e.ep)return;e.ep=!0;let n=t(e);fetch(e.href,n)}})();function e(){return`
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
            <div><span class="section-kicker">Selección pública</span><h2 id="picks-title">Cartera del día</h2></div>
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
            <div><span class="section-kicker">Transparencia</span><h2 id="history-title">Historial completo</h2></div>
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

    <div class="cookie-notice hidden" id="cookie-notice" role="region" aria-label="Aviso de privacidad"><p>Usamos almacenamiento esencial para tu sesión y medición anónima de uso.</p><button id="cookie-accept" type="button">Entendido</button></div>
  `}function t(){let t=document.getElementById(`app`);if(!t)throw Error(`Missing #app root`);t.innerHTML=e()}function n(e){let t=new Set([`ganado`,`perdido`,`pendiente`,`void`,`revision_pendiente`]);return e.filter(e=>t.has(e.estado))}var r=[{text:`Será como árbol plantado junto a corrientes de aguas, que da su fruto en su tiempo y su hoja no cae; y todo lo que hace, prosperará.`,reference:`Salmo 1:3`,focus:`Prosperidad y Fruto`},{text:`Sea la gracia del Señor nuestro Dios sobre nosotros, y confirma sobre nosotros la obra de nuestras manos; sí, la obra de nuestras manos confirma.`,reference:`Salmo 90:17`,focus:`Bendición del Trabajo`},{text:`Encomienda a Jehová tu camino, confía en él; y él hará.`,reference:`Salmo 37:5`,focus:`Dirección y Confianza`},{text:`Jehová guardará tu salida y tu entrada desde ahora y para siempre.`,reference:`Salmo 121:8`,focus:`Protección Total`},{text:`Pon en manos del Señor todas tus obras, y tus proyectos se cumplirán.`,reference:`Proverbios 16:3`,focus:`Éxito en Proyectos`},{text:`Jehová es mi pastor; nada me faltará.`,reference:`Salmo 23:1`,focus:`Paz y Provisión`},{text:`Mira que te mando que te esfuerces y seas valiente; no temas ni desmayes, porque Jehová tu Dios estará contigo dondequiera que vayas.`,reference:`Josué 1:9`,focus:`Fuerza y Victoria`}];function i(e=`daily-verse-container`){let t=document.getElementById(e);if(!t)return;let n=new Date,i=Math.floor((n.getTime()-new Date(n.getFullYear(),0,0).getTime())/864e5)%r.length;function a(e){let n=r[e];t.innerHTML=`
      <div class="verse-banner" id="verse-banner-box" role="region" aria-label="Salmo del día">
        <div class="verse-glow-bar"></div>
        <div class="verse-main-content">
          <div class="verse-header-tag">
            <span class="verse-sparkle">✨</span>
            <span class="verse-focus-pill">${n.focus}</span>
            <span class="verse-ref-tag">${n.reference}</span>
          </div>
          <p class="verse-quote">«${n.text}»</p>
        </div>
        <div class="verse-toolbar">
          <button id="btn-copy-verse" class="verse-icon-btn" title="Copiar versículo" aria-label="Copiar versículo">
            📋
          </button>
          <button id="btn-next-verse" class="verse-icon-btn" title="Ver otro salmo" aria-label="Ver otro salmo">
            🔄
          </button>
        </div>
      </div>
    `,document.getElementById(`btn-next-verse`)?.addEventListener(`click`,()=>{i=(i+1)%r.length;let e=document.getElementById(`verse-banner-box`);e?(e.classList.add(`verse-fade-out`),setTimeout(()=>{a(i)},150)):a(i)}),document.getElementById(`btn-copy-verse`)?.addEventListener(`click`,e=>{let t=`«${n.text}» — ${n.reference}`;navigator.clipboard.writeText(t).then(()=>{let t=e.currentTarget;t&&(t.innerHTML=`✅`,setTimeout(()=>{t.innerHTML=`📋`},1800))})})}a(i)}var a=/^respaldo\s+de\s+datos\s*:\s*/i,o=/\s+respaldo\s+de\s+datos\s*$/i;function s(e){return`Respaldo de datos: ${(e==null||e===``?`No disponible`:String(e).trim()).replace(a,``).replace(o,``).trim()||`No disponible`}`}function c(e){let t=e.filter(e=>e.estado===`ganado`).length,n=e.filter(e=>e.estado===`perdido`).length,r=e.filter(e=>![`ganado`,`perdido`,`void`].includes(e.estado)).length,i=e.reduce((e,t)=>t.estado===`ganado`?e+Number(t.cuota)-1:t.estado===`perdido`?e-1:e,0),a=t+n;return{wins:t,losses:n,pending:r,units:Number(i.toFixed(2)),roi:a?Number((i/a*100).toFixed(1)):0}}function l(e){return{pendiente:`Pendiente`,ganado:`Ganado`,perdido:`Perdido`,void:`Nulo`,revision_pendiente:`En revisión`}[e]}function u(e,t){let n=e?.trim(),r=t?.trim();return n&&r?{slot:n,client:r}:null}function d(e,t){if(!t)return;if(!document.querySelector(`script[data-rey-taco-adsense]`)){let e=document.createElement(`script`);e.async=!0,e.crossOrigin=`anonymous`,e.dataset.reyTacoAdsense=`true`,e.src=`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(t.client)}`,document.head.append(e)}e.classList.remove(`hidden`),e.innerHTML=`<span class="ad-label">PUBLICIDAD</span>`;let n=document.createElement(`ins`);n.className=`adsbygoogle`,n.style.display=`block`,n.dataset.adClient=t.client,n.dataset.adSlot=t.slot,n.dataset.adFormat=`auto`,n.dataset.fullWidthResponsive=`true`,e.append(n);try{let e=window;(e.adsbygoogle??=[]).push({})}catch{e.classList.add(`hidden`)}}var f=new Set;function p(e){if(f.has(e))return;f.add(e);let t=window;(t.dataLayer??=[]).push({event:e})}function m(e,t){if(!e||typeof IntersectionObserver>`u`)return;let n=new IntersectionObserver(e=>{e.some(e=>e.isIntersecting)&&(p(t),n.disconnect())},{threshold:.25});n.observe(e)}function h(e){let t=document.createElement(`div`);return t.textContent=String(e??``),t.innerHTML}function g(e){let t=[`pendiente`,`ganado`,`perdido`,`void`,`revision_pendiente`],n=String(e.estado??`pendiente`);return{id:e.id??crypto.randomUUID(),categoria:String(e.categoria??`Deportes`),partido:String(e.partido??`Evento por confirmar`),pick:String(e.pick??`Selección por confirmar`),cuota:e.cuota??`—`,confianza:e.confianza??`—`,razonamiento:String(e.razonamiento??`Consulta los datos y apuesta con responsabilidad.`),fecha_generacion:String(e.fecha_generacion??``),fecha_evento:String(e.fecha_evento??``),horario:String(e.horario??``),estado:t.includes(n)?n:`revision_pendiente`,es_parlay:!!e.es_parlay,visibility:e.visibility===`premium`?`premium`:`public`}}function _(e){let t=e.find(e=>e.estado===`pendiente`&&!e.es_parlay);return t?[{...g(t),visibility:`public`}]:[]}async function v(){let e=await fetch(`/picks.json`,{cache:`no-store`});return e.ok?_(await e.json()):[]}var y={picks:[],history:[],pickFilter:`all`,historyFilter:`all`,user:null,isVip:!1};t(),i();var b=e=>document.getElementById(e);function x(e){let t=e.toLowerCase();return t.includes(`liga mx`)?`ligamx`:t.includes(`mlb`)?`mlb`:`futbol`}function S(e){if(!e)return`—`;let t=new Date(`${e}T12:00:00-06:00`);return Number.isNaN(t.getTime())?h(e):new Intl.DateTimeFormat(`es-MX`,{day:`2-digit`,month:`short`,timeZone:`America/Mexico_City`}).format(t)}function C(e){let t=e.visibility===`premium`&&!y.isVip;return`
    <article class="pick-card ${t?`locked`:``}">
      <div class="pick-meta"><span>${h(e.categoria)}</span><span>${S(e.fecha_evento||e.fecha_generacion)} · CDMX</span></div>
      <h3>${h(e.partido)}</h3>
      ${t?`<div class="locked-pick"><strong>♛ Selección VIP</strong><span>Inicia sesión con una membresía activa para verla.</span></div>`:`
        <div class="selection-row"><span>Selección</span><strong>${h(e.pick)}</strong><b>@ ${h(e.cuota)}</b></div>
        <p>${h(e.razonamiento)}</p>
      `}
      <div class="pick-footer"><span>${h(s(e.confianza))}</span><span class="status status-${e.estado}">${l(e.estado)}</span></div>
    </article>`}function w(){let e=b(`picks-container`);if(!e)return;let t=y.picks.filter(e=>y.pickFilter===`all`||x(e.categoria)===y.pickFilter);e.innerHTML=t.length?t.map(C).join(``):`
    <div class="state-card"><strong>No hay picks disponibles en este filtro.</strong><span>Vuelve más tarde; no publicamos selecciones solo para llenar espacio.</span></div>`;let n=b(`picks-updated`);n&&(n.textContent=y.isVip?`Cartera VIP activa`:t.length?`1 selección pública`:`Sin selección disponible`)}function T(){let e=b(`history-container`);if(!e)return;let t=n(y.history).filter(e=>y.historyFilter===`all`||e.estado===y.historyFilter);e.innerHTML=t.length?t.map(e=>`
    <tr><td>${S(e.fecha_evento||e.fecha_generacion)}</td><td>${h(e.partido)}</td><td>${h(e.pick)}</td><td>@ ${h(e.cuota)}</td><td><span class="status status-${e.estado}">${l(e.estado)}</span></td></tr>
  `).join(``):`<tr><td colspan="5">Todavía no hay resultados en este filtro.</td></tr>`;let r=c(y.history),i=b(`metric-record`),a=b(`metric-units`),o=b(`metric-roi`);i&&(i.textContent=`${r.wins}-${r.losses}`),a&&(a.textContent=`${r.units>=0?`+`:``}${r.units} u`),o&&(o.textContent=`${r.roi>=0?`+`:``}${r.roi}%`)}async function E(){y.picks=await v(),y.history=[],w(),T()}var D=b(`auth-dialog`),O=()=>D?.showModal();document.querySelectorAll(`[data-auth-mode]`).forEach(e=>{e.addEventListener(`click`,()=>{document.querySelectorAll(`[data-auth-mode]`).forEach(t=>t.classList.toggle(`active`,t===e));let t=e.dataset.authMode===`register`,n=b(`auth-submit`),r=b(`auth-password`);n&&(n.textContent=t?`Crear cuenta`:`Iniciar sesión`),r&&(r.autocomplete=t?`new-password`:`current-password`)})}),b(`login-button`)?.addEventListener(`click`,async()=>{O()}),b(`signout-button`)?.addEventListener(`click`,async()=>{D?.close()}),b(`telegram-link-button`)?.addEventListener(`click`,async()=>{b(`auth-message`)}),b(`promo-form`)?.addEventListener(`submit`,async e=>{e.preventDefault(),b(`auth-message`),b(`promo-code`)?.value.trim()}),b(`auth-form`)?.addEventListener(`submit`,async e=>{e.preventDefault(),b(`auth-email`)?.value.trim(),b(`auth-password`)?.value,document.querySelector(`[data-auth-mode].active`)?.dataset.authMode;let t=b(`auth-message`);t&&(t.textContent=`La cuenta requiere configurar Supabase en este despliegue.`)});async function k(){if(y.isVip,!y.user){O();let e=b(`auth-message`);e&&(e.textContent=`Crea una cuenta o inicia sesión antes de pagar.`);return}}b(`vip-button`)?.addEventListener(`click`,k),b(`vip-checkout-button`)?.addEventListener(`click`,k),b(`filter-row`)?.addEventListener(`click`,e=>{let t=e.target.closest(`[data-filter]`);t&&(y.pickFilter=t.dataset.filter??`all`,document.querySelectorAll(`[data-filter]`).forEach(e=>e.classList.toggle(`active`,e===t)),w())}),b(`history-filters`)?.addEventListener(`click`,e=>{let t=e.target.closest(`[data-status]`);t&&(y.historyFilter=t.dataset.status??`all`,document.querySelectorAll(`[data-status]`).forEach(e=>e.classList.toggle(`active`,e===t)),T())});function A(){let e=Math.max(0,Number(b(`bankroll`)?.value||0)),t=Number(b(`risk-percent`)?.value||1),n=b(`stake-result`);n&&(n.textContent=`Unidad sugerida: $${Math.round(e*t/100).toLocaleString(`es-MX`)} MXN`)}b(`bankroll`)?.addEventListener(`input`,A),b(`risk-percent`)?.addEventListener(`change`,A),b(`telegram-cta`)?.addEventListener(`click`,()=>p(`telegram_clicked`)),m(document.querySelector(`.vip-section`),`vip_offer_viewed`);var j=b(`cookie-notice`),M=u(void 0,void 0),N=()=>d(b(`ad-slot-feed`),M);localStorage.getItem(`rey-taco-cookie-notice`)?N():j?.classList.remove(`hidden`),b(`cookie-accept`)?.addEventListener(`click`,()=>{localStorage.setItem(`rey-taco-cookie-notice`,`accepted`),j?.classList.add(`hidden`),N()}),(async()=>{await E()})();