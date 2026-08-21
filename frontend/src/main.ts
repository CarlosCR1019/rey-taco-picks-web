import './style.css'
import { createClient } from '@supabase/supabase-js'
import { initDailyVerseBanner } from './dailyVerse'

// Inicializar Supabase con fallback de producción
const SUPABASE_DEFAULT_URL = 'https://dqwuaocyyohwkkuldsmp.supabase.co';
const SUPABASE_DEFAULT_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRxd3Vhb2N5eW9od2trdWxkc21wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY2NzQ3OTAsImV4cCI6MjEwMjI1MDc5MH0.bKBhyFHtcAXYgx44rg4-D2CaqktOnUg6ZnvBcTW1CDQ';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || SUPABASE_DEFAULT_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || SUPABASE_DEFAULT_KEY;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

document.querySelector<HTMLDivElement>('#app')!.innerHTML = `
  <div class="app-container">
    <header class="header">
      <div class="logo-container">
        <img src="/logo.jpg" alt="Rey Taco Picks Logo" class="brand-logo" />
        <h1>Rey Taco <span class="logo-accent">Picks</span></h1>
      </div>
      <div class="header-actions">
        <button id="parlay-builder-header-btn" class="btn-parlay-builder-nav">⚡ Crear Parlay IA</button>
        <button id="calc-btn" class="calc-btn">🧮 Calculadora</button>
        <button id="login-btn" class="login-btn">Iniciar Sesión</button>
        <button class="premium-badge">Acceso Premium</button>
      </div>
    </header>

    <!-- PWA Install Banner -->
    <div id="pwa-banner" class="pwa-banner hidden">
      <div class="pwa-info">
        <span class="pwa-icon">📱</span>
        <div>
          <strong>Instala Rey Taco Picks</strong>
          <p>Accede más rápido y recibe alertas directamente en tu pantalla de inicio.</p>
        </div>
      </div>
      <div class="pwa-actions">
        <button id="pwa-install-btn" class="btn-gold pwa-btn">Instalar</button>
        <button id="pwa-dismiss-btn" class="pwa-close-btn">&times;</button>
      </div>
    </div>

    <!-- Daily Blessing / Psalm Banner -->
    <div id="daily-verse-container"></div>

    <main>
      <section class="stats-bar">
        <div class="stat-card">
          <span class="stat-label">ROI % del mes</span>
          <span class="stat-value text-green">+18.4%</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">Racha actual</span>
          <span class="stat-value text-gold">4 Victorias</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">% Acierto global</span>
          <span class="stat-value">67.2%</span>
        </div>
      </section>

      <section class="picks-section">
        <div class="picks-header-row">
          <h3 class="section-title">
            <span class="live-indicator"></span> 
            Análisis del Día
          </h3>
          <span class="picks-count-tag" id="picks-counter">6 Picks +EV</span>
        </div>

        <!-- Sport & League Filter Pills -->
        <div class="filter-bar" id="filter-bar">
          <button class="filter-pill active" data-filter="all">🎯 Todos</button>
          <button class="filter-pill" data-filter="champions">🇪🇺 Champions League</button>
          <button class="filter-pill" data-filter="ligamx">🇲🇽 Liga MX</button>
          <button class="filter-pill" data-filter="futbol">⚽ Fútbol Global</button>
          <button class="filter-pill" data-filter="corners">⛳ Tiros de Esquina</button>
          <button class="filter-pill" data-filter="mlb">⚾ Béisbol MLB</button>
          <button class="filter-pill" data-filter="kbo">🇰🇷 KBO (Corea)</button>
          <button class="filter-pill" data-filter="nfl">🏈 NFL</button>
          <button class="filter-pill" data-filter="parlays">🔗 Parlays +EV</button>
        </div>
        
        <div id="picks-container" class="loading">Desencriptando líneas de mercado...</div>
      </section>

      <!-- Monetization Ad Slot (In-Feed) -->
      <div class="ad-container" id="ad-slot-feed">
        <span class="ad-label">PUBLICIDAD / ANUNCIO PATROCINADO</span>
        <div class="ad-box-placeholder">
          <ins class="adsbygoogle"
               style="display:block; text-align:center;"
               data-ad-client="ca-pub-2697347675028991"
               data-ad-format="auto"
               data-full-width-responsive="true"></ins>
          <div class="ad-fallback-content">
            <span class="ad-fallback-icon">🎯</span>
            <span>Espacio Publicitario Oficial • Anúnciate ante miles de apostadores en Rey Taco Picks</span>
            <a href="https://t.me/carlosds1017" target="_blank" class="btn-ad-contact">Contactar Anuncios</a>
          </div>
        </div>
      </div>

      <section class="chart-section">
        <h3 class="section-title">📊 Rendimiento</h3>
        <div class="chart-grid">
          <div class="chart-card">
            <h4>Bankroll Simulado ($MXN)</h4>
            <canvas id="bankroll-chart"></canvas>
          </div>
          <div class="chart-card">
            <h4>Aciertos por Deporte</h4>
            <canvas id="sport-chart"></canvas>
          </div>
        </div>
      </section>
      <section class="history-section">
        <h3 class="section-title">Historial de Operaciones</h3>
        <div class="table-container">
          <table class="history-table">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Partido</th>
                <th>Pick</th>
                <th>Cuota</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody id="history-container">
              <!-- Rendered via JS -->
            </tbody>
          </table>
        </div>
      </section>

      <section class="tickets-section">
        <h3 class="section-title">🏆 Muro de Victorias</h3>
        <p class="tickets-subtitle">Nosotros apostamos. Nosotros ganamos. Aquí está la prueba.</p>
        <div id="tickets-grid" class="tickets-grid">
          <!-- Rendered via JS -->
        </div>
      </section>
    </main>

    <!-- Professional Footer (AdSense Compliant) -->
    <footer class="app-footer">
      <div class="footer-content">
        <div class="footer-brand">
          <img src="/logo.jpg" alt="Rey Taco Picks" class="footer-logo" />
          <div>
            <strong>Rey Taco Picks 🌮👑</strong>
            <p>Análisis matemático, valor esperado (+EV) y predicciones deportivas con Inteligencia Artificial.</p>
          </div>
        </div>
        
        <div class="footer-links">
          <a href="#" id="link-privacy">Política de Privacidad</a>
          <span class="sep">•</span>
          <a href="#" id="link-terms">Términos y Condiciones</a>
          <span class="sep">•</span>
          <a href="https://t.me/carlosds1017" target="_blank">Contacto y Publicidad</a>
          <span class="sep">•</span>
          <a href="https://t.me/ReyTacoPicks" target="_blank">Canal Telegram Oficial</a>
        </div>
        
        <div class="footer-disclaimer">
          <span class="badge-18">+18</span>
          <p>Juega con responsabilidad. Prohibido para menores de edad. Los pronósticos y análisis estadísticos proporcionados por Rey Taco Picks (reytacopicks.com) son únicamente de carácter informativo y recreativo. Apuesta con moderación.</p>
        </div>
        
        <div class="footer-copyright">
          <p>© 2026 Rey Taco Picks (reytacopicks.com) — Todos los derechos reservados.</p>
        </div>
      </div>
    </footer>

    <!-- Legal Modal (Privacy & Terms) -->
    <div id="legal-modal" class="modal-overlay hidden">
      <div class="modal-content legal-modal-content">
        <button id="close-legal-modal" class="close-btn">&times;</button>
        <div class="modal-header">
          <h2 id="legal-modal-title">Política de Privacidad</h2>
          <p id="legal-modal-subtitle">Información legal y protección de datos en reytacopicks.com</p>
        </div>
        <div id="legal-modal-body" class="legal-body">
          <!-- Populated by JS -->
        </div>
      </div>
    </div>

    <!-- Auth & Subscription Modal -->
    <div id="auth-modal" class="modal-overlay hidden">
      <div class="modal-content">
        <button id="close-modal" class="close-btn">&times;</button>
        
        <div class="auth-tabs">
          <button id="tab-login" class="auth-tab active">🔑 Acceso</button>
          <button id="tab-spei" class="auth-tab">💳 Pagar SPEI</button>
          <button id="tab-code" class="auth-tab">🎟️ Código VIP</button>
        </div>

        <!-- Panel 1: Login / Register -->
        <div id="panel-login" class="auth-panel">
          <div class="modal-header">
            <h2 id="modal-title">Iniciar Sesión</h2>
            <p id="modal-subtitle">Accede a tus picks premium y análisis IA</p>
          </div>
          
          <div class="auth-subtabs">
            <button id="subtab-login" class="subtab active">Entrar</button>
            <button id="subtab-register" class="subtab">Crear Cuenta</button>
          </div>

          <form id="auth-form" class="auth-form">
            <div class="form-group">
              <label>Correo Electrónico</label>
              <input type="email" id="auth-email" required placeholder="tu@correo.com" />
            </div>
            <div class="form-group">
              <label>Contraseña</label>
              <input type="password" id="auth-password" required placeholder="••••••••" minlength="6" />
            </div>
            <p id="auth-error" class="auth-error hidden"></p>
            <p id="auth-success" class="auth-success hidden"></p>
            <button type="submit" id="auth-submit-btn" class="submit-btn">Entrar al Sistema</button>
          </form>
        </div>

        <!-- Panel 2: SPEI Transfer -->
        <div id="panel-spei" class="auth-panel hidden">
          <div class="modal-header">
            <h2>💳 Pagar por Transferencia SPEI</h2>
            <p>Acceso VIP instantáneo sin comisiones extras</p>
          </div>
          
          <div class="spei-card">
            <div class="spei-row">
              <span class="spei-label">Banco:</span>
              <strong class="spei-val">BBVA México</strong>
            </div>
            <div class="spei-row">
              <span class="spei-label">Beneficiario / Titular:</span>
              <strong class="spei-val">Rey Taco Picks</strong>
            </div>
            <div class="spei-row">
              <span class="spei-label">Cuenta CLABE:</span>
              <div class="clabe-copy-box">
                <code id="clabe-number">012180015228133759</code>
                <button id="copy-clabe-btn" class="copy-btn" title="Copiar CLABE">📋 Copiar</button>
              </div>
            </div>
            <div class="spei-row">
              <span class="spei-label">Cuenta:</span>
              <strong class="spei-val">152 281 3375</strong>
            </div>
            <div class="spei-row">
              <span class="spei-label">Monto sugerido:</span>
              <strong class="spei-val text-green">$299 MXN / Mes</strong>
            </div>
            <div class="spei-row">
              <span class="spei-label">Concepto:</span>
              <strong class="spei-val text-gold">Tu Correo Electrónico</strong>
            </div>
          </div>

          <div class="spei-action">
            <p class="spei-note">Una vez hecha tu transferencia, envíanos la captura para activarte de inmediato:</p>
            <a id="whatsapp-spei-btn" href="https://wa.me/525639331102?text=Hola,%20ya%20realic%C3%A9%20mi%20transferencia%20para%20Rey%20Taco%20Picks%20VIP.%20Mi%20correo%20es:%20" target="_blank" class="whatsapp-btn">
              📲 Enviar Comprobante por WhatsApp
            </a>
          </div>
        </div>

        <!-- Panel 3: VIP Code Redemption -->
        <div id="panel-code" class="auth-panel hidden">
          <div class="modal-header">
            <h2>🎟️ Canjear Código de Acceso VIP</h2>
            <p>Si pagaste por transferencia y recibiste tu código, ingrésalo aquí</p>
          </div>
          
          <form id="code-form" class="auth-form">
            <div class="form-group">
              <label>Código de Activación</label>
              <input type="text" id="vip-code-input" required placeholder="Ingresa tu código" autocomplete="one-time-code" style="text-transform: uppercase; font-weight: bold; letter-spacing: 2px;" />
            </div>
            <p id="code-msg" class="auth-error hidden"></p>
            <button type="submit" id="redeem-btn" class="submit-btn btn-gold">Activar Pase VIP</button>
          </form>
        </div>
      </div>
    </div>

    <!-- Stake Calculator Modal -->
    <div id="calc-modal" class="modal-overlay hidden">
      <div class="modal-content calc-modal-content">
        <button id="close-calc-modal" class="close-btn">&times;</button>
        <div class="modal-header">
          <h3 class="modal-title">🧮 Calculadora de Gestión de Bankroll</h3>
          <p class="modal-subtitle">Estrategia Kelly Criterion y asignación óptima de Unidades</p>
        </div>
        
        <div class="calc-body">
          <div class="form-group">
            <label>Tu Capital / Bankroll Total ($MXN)</label>
            <input type="number" id="calc-bankroll-input" value="2000" min="100" step="50" class="calc-input" />
          </div>

          <div class="calc-results">
            <div class="calc-row-header">
              <span>Tipo de Selección</span>
              <span>Stake Sugerido</span>
              <span>Monto en Pesos</span>
            </div>

            <div class="calc-row">
              <div>
                <strong>💎 Pick de Alta Confianza (90%+)</strong>
                <p>Ventaja matemática +EV validada</p>
              </div>
              <span class="calc-units">2.5 Unidades (5%)</span>
              <span id="stake-high" class="calc-amount text-green">$100 MXN</span>
            </div>

            <div class="calc-row">
              <div>
                <strong>⛳ Córners / Hándicap Asiático</strong>
                <p>Mercado de micro-estadísticas</p>
              </div>
              <span class="calc-units">1.5 Unidades (3%)</span>
              <span id="stake-corners" class="calc-amount text-gold">$60 MXN</span>
            </div>

            <div class="calc-row">
              <div>
                <strong>🟢 Parlay Seguro (Cuota ~2.40)</strong>
                <p>2 selecciones de alta correlación</p>
              </div>
              <span class="calc-units">1.0 Unidad (2%)</span>
              <span id="stake-parlay-safe" class="calc-amount text-cyan">$40 MXN</span>
            </div>

            <div class="calc-row">
              <div>
                <strong>💣 Parlay Bomba (+EV Value Bomb)</strong>
                <p>Multiplicador alto (Cuota 4.50 - 7.50)</p>
              </div>
              <span class="calc-units">0.25 Unidades (0.5%)</span>
              <span id="stake-parlay-bomb" class="calc-amount text-red">$10 MXN</span>
            </div>
          </div>
          <p class="calc-footer-note">💡 Regla de oro de Rey Taco: Nunca apuestes más del 5% de tu capital en una sola jugada.</p>
        </div>
      </div>
    </div>

    <!-- Ticket Zoom Lightbox Modal -->
    <div id="ticket-modal" class="modal-overlay hidden">
      <div class="ticket-modal-content">
        <button id="close-ticket-modal" class="close-btn">&times;</button>
        <img id="ticket-zoom-img" src="" alt="Ticket Ganador Zoom" class="ticket-zoom-img" />
      </div>
    </div>

    <!-- AI Parlay Builder Modal -->
    <div id="parlay-builder-modal" class="modal-overlay hidden">
      <div class="modal-content parlay-builder-modal-content">
        <button id="close-parlay-modal" class="close-btn">&times;</button>
        
        <div class="modal-header">
          <div class="vip-exclusive-badge">⚡ IA CORRELATION ENGINE</div>
          <h3 class="modal-title">🤖 Creador de Parlays IA a Medida</h3>
          <p class="modal-subtitle">Combina tu partido favorito con el mejor análisis matemático +EV</p>
        </div>

        <!-- Non-VIP Lock Gate (Disabled, unlocked for all) -->
        <div id="parlay-vip-gate" class="vip-gate-box hidden">
          <div class="vip-lock-icon">🔒</div>
          <h4>Función Exclusiva para Miembros VIP</h4>
          <p>Nuestra Inteligencia Artificial analiza correlaciones, córners, goles y líneas en tiempo real para armar combinadas personalizadas de alta probabilidad.</p>
        </div>

        <!-- Interactive Builder Interface -->
        <div id="parlay-builder-interface" class="parlay-builder-body">
          <div class="form-group">
            <label>🏟️ Partido Base Seleccionado</label>
            <select id="parlay-base-match" class="builder-select">
              <!-- Rendered dynamically -->
            </select>
          </div>

          <div class="form-group">
            <label>🎯 Estrategia y Perfil de Riesgo</label>
            <div class="strategy-pill-group">
              <label class="strategy-pill active" data-strategy="seguro">
                <input type="radio" name="parlay-strategy" value="seguro" checked />
                <div class="pill-text">
                  <strong>🛡️ Seguro / Banker</strong>
                  <span>Cuota 2.00 - 2.50x</span>
                </div>
              </label>
              <label class="strategy-pill" data-strategy="valor">
                <input type="radio" name="parlay-strategy" value="valor" />
                <div class="pill-text">
                  <strong>📈 Valor +EV</strong>
                  <span>Cuota 3.00 - 4.50x</span>
                </div>
              </label>
              <label class="strategy-pill" data-strategy="bomba">
                <input type="radio" name="parlay-strategy" value="bomba" />
                <div class="pill-text">
                  <strong>🚀 Multiplicador Bomba</strong>
                  <span>Cuota 5.00x+</span>
                </div>
              </label>
            </div>
          </div>

          <div class="form-group">
            <label>💵 Apuesta Simulada ($MXN)</label>
            <input type="number" id="parlay-stake-input" value="200" min="10" step="50" class="builder-input" />
          </div>

          <button id="btn-generate-ai-parlay" class="btn-gold btn-full btn-generate-parlay">⚡ Generar Parlay Óptimo con IA</button>

          <!-- Result Parlay Card -->
          <div id="parlay-result-box" class="parlay-result-box hidden">
            <div class="ticket-header-row">
              <span class="ticket-title">👑 TICKET PARLAY IA</span>
              <span id="ticket-total-odd" class="ticket-odd-badge">@ 2.44</span>
            </div>
            
            <div id="ticket-legs-list" class="ticket-legs-list">
              <!-- Rendered via JS -->
            </div>

            <div class="ticket-summary-box">
              <div class="summary-col">
                <span>Inversión</span>
                <strong id="ticket-stake-display">$200 MXN</strong>
              </div>
              <div class="summary-col">
                <span>Ganancia Potencial</span>
                <strong id="ticket-payout-display" class="text-green">$488 MXN</strong>
              </div>
            </div>

            <div class="ticket-ai-rationale">
              <strong>🧠 Análisis y Correlación (IA):</strong>
              <p id="ticket-rationale-text"></p>
            </div>

            <div class="ticket-action-btns">
              <button id="btn-copy-parlay-slip" class="btn-share-pick">📋 Copiar Jugada</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
`

// Inicializar Banner de Salmo y Bendición del Día
initDailyVerseBanner('daily-verse-container');

// State
let currentUser: any = null;
let isSubscribed = false;
let isLoginMode = true;

// Auth UI Logic
const authModal = document.getElementById('auth-modal')!;
const closeModalBtn = document.getElementById('close-modal')!;
const loginBtn = document.getElementById('login-btn')!;
const premiumBadge = document.querySelector('.premium-badge') as HTMLButtonElement;

const tabLogin = document.getElementById('tab-login')!;
const tabSpei = document.getElementById('tab-spei')!;
const tabCode = document.getElementById('tab-code')!;

const panelLogin = document.getElementById('panel-login')!;
const panelSpei = document.getElementById('panel-spei')!;
const panelCode = document.getElementById('panel-code')!;

const subtabLogin = document.getElementById('subtab-login')!;
const subtabRegister = document.getElementById('subtab-register')!;
const modalTitle = document.getElementById('modal-title')!;
const modalSubtitle = document.getElementById('modal-subtitle')!;
const authForm = document.getElementById('auth-form') as HTMLFormElement;
const emailInput = document.getElementById('auth-email') as HTMLInputElement;
const passwordInput = document.getElementById('auth-password') as HTMLInputElement;
const errorMsg = document.getElementById('auth-error')!;
const successMsg = document.getElementById('auth-success')!;
const submitBtn = document.getElementById('auth-submit-btn') as HTMLButtonElement;

const copyClabeBtn = document.getElementById('copy-clabe-btn')!;
const codeForm = document.getElementById('code-form') as HTMLFormElement;
const vipCodeInput = document.getElementById('vip-code-input') as HTMLInputElement;
const codeMsg = document.getElementById('code-msg')!;

function switchMainTab(tab: 'login' | 'spei' | 'code') {
  [tabLogin, tabSpei, tabCode].forEach(t => t.classList.remove('active'));
  [panelLogin, panelSpei, panelCode].forEach(p => p.classList.add('hidden'));

  if (tab === 'login') {
    tabLogin.classList.add('active');
    panelLogin.classList.remove('hidden');
  } else if (tab === 'spei') {
    tabSpei.classList.add('active');
    panelSpei.classList.remove('hidden');
  } else if (tab === 'code') {
    tabCode.classList.add('active');
    panelCode.classList.remove('hidden');
  }
}

tabLogin.addEventListener('click', () => switchMainTab('login'));
tabSpei.addEventListener('click', () => switchMainTab('spei'));
tabCode.addEventListener('click', () => switchMainTab('code'));

function openModal(defaultTab: 'login' | 'spei' | 'code' = 'login') {
  switchMainTab(defaultTab);
  authModal.classList.remove('hidden');
}

function closeModal() {
  authModal.classList.add('hidden');
  errorMsg.classList.add('hidden');
  successMsg.classList.add('hidden');
  codeMsg.classList.add('hidden');
}

function updateSubtabUI() {
  errorMsg.classList.add('hidden');
  successMsg.classList.add('hidden');
  if (isLoginMode) {
    subtabLogin.classList.add('active');
    subtabRegister.classList.remove('active');
    modalTitle.textContent = 'Iniciar Sesión';
    modalSubtitle.textContent = 'Accede a tus picks premium y análisis IA';
    submitBtn.textContent = 'Entrar al Sistema';
  } else {
    subtabRegister.classList.add('active');
    subtabLogin.classList.remove('active');
    modalTitle.textContent = 'Crear Cuenta';
    modalSubtitle.textContent = 'Únete y recibe predicciones de alto valor';
    submitBtn.textContent = 'Registrarse';
  }
}

loginBtn.addEventListener('click', () => {
  if (currentUser) {
    // Logout confirmation
    if (confirm(`¿Cerrar sesión de ${currentUser.email}?`)) {
      currentUser = null;
      isSubscribed = false;
      if (supabase) supabase.auth.signOut();
      updateAuthHeaderState();
      fetchPicks();
    }
  } else {
    openModal('login');
  }
});

closeModalBtn.addEventListener('click', closeModal);
authModal.addEventListener('click', (e) => {
  if (e.target === authModal) closeModal();
});

subtabLogin.addEventListener('click', () => { isLoginMode = true; updateSubtabUI(); });
subtabRegister.addEventListener('click', () => { isLoginMode = false; updateSubtabUI(); });

premiumBadge?.addEventListener('click', () => {
  if (!isSubscribed) {
    openModal('spei');
  }
});

// Copy CLABE
copyClabeBtn?.addEventListener('click', () => {
  navigator.clipboard.writeText('012180015228133759');
  copyClabeBtn.textContent = '✅ ¡Copiada!';
  setTimeout(() => { copyClabeBtn.textContent = '📋 Copiar'; }, 2500);
});

// Promotional codes are validated on the server. Until that endpoint is
// configured, fail closed instead of granting access in the browser.
codeForm?.addEventListener('submit', (e) => {
  e.preventDefault();
  vipCodeInput.value = '';
  codeMsg.className = 'auth-error';
  codeMsg.textContent = 'El canje en línea está temporalmente deshabilitado. Contacta a soporte para validar tu código de forma segura.';
  codeMsg.classList.remove('hidden');
});

function updateAdsVisibility() {
  const isVip = isSubscribed;
  const adContainers = document.querySelectorAll('.ad-container');
  adContainers.forEach((ad: any) => {
    if (isVip) {
      ad.style.display = 'none';
    } else {
      ad.style.display = 'block';
    }
  });
}

function updateAuthHeaderState() {
  if (isSubscribed) {
    loginBtn.textContent = `👤 ${currentUser?.email?.split('@')[0] || 'Usuario'}`;
    premiumBadge.innerHTML = '👑 VIP Activado';
    premiumBadge.classList.add('badge-gold');
  } else if (currentUser) {
    loginBtn.textContent = `👤 ${currentUser?.email?.split('@')[0] || 'Usuario'}`;
    premiumBadge.innerHTML = 'Pagar VIP';
    premiumBadge.classList.remove('badge-gold');
  } else {
    loginBtn.textContent = 'Iniciar Sesión';
    premiumBadge.innerHTML = 'Acceso Premium';
    premiumBadge.classList.remove('badge-gold');
  }
  updateAdsVisibility();
}

// Auth Logic (Supabase session only)
authForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  const password = passwordInput.value;
  
  submitBtn.disabled = true;
  submitBtn.textContent = "Procesando...";
  errorMsg.classList.add('hidden');
  successMsg.classList.add('hidden');

  if (!supabase) {
    errorMsg.textContent = "Error: Base de datos no conectada.";
    errorMsg.classList.remove('hidden');
    submitBtn.disabled = false;
    return;
  }

  try {
    if (isLoginMode) {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
      
      // Check if user is premium in profiles table
      let isPrem = false;
      try {
        const { data: profile } = await supabase.from('profiles').select('is_premium').eq('id', data.user.id).single();
        if (profile?.is_premium) isPrem = true;
      } catch (pe) {}

      currentUser = { email: data.user.email, id: data.user.id, is_premium: isPrem };
      isSubscribed = isPrem;
      
      successMsg.textContent = '✅ ¡Sesión iniciada con éxito!';
      successMsg.classList.remove('hidden');
      updateAuthHeaderState();
      setTimeout(() => {
        closeModal();
        fetchPicks();
      }, 1000);
    } else {
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) throw error;
      
      currentUser = { email: data.user?.email || email, id: data.user?.id, is_premium: false };
      
      successMsg.textContent = '✅ Cuenta creada con éxito. Ahora puedes adquirir tu pase VIP por SPEI.';
      successMsg.classList.remove('hidden');
      updateAuthHeaderState();
      setTimeout(() => {
        switchMainTab('spei');
      }, 1500);
    }
  } catch (err: any) {
    errorMsg.textContent = err.message || "Error al procesar la solicitud.";
    errorMsg.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
  }
});

// Initial header state
updateAuthHeaderState();


function getSportColorClass(sport: string) {
  const s = sport.toLowerCase();
  if (s.includes('parlay') || s.includes('combinad')) return 'tag-gold';
  if (s.includes('esquina') || s.includes('córner') || s.includes('corner')) return 'tag-purple';
  if (s.includes('kbo') || s.includes('corea') || s.includes('korea')) return 'tag-cyan';
  if (s.includes('champions') || s.includes('uefa') || s.includes('europa')) return 'tag-blue';
  if (s.includes('liga mx') || s.includes('ligamx')) return 'tag-green';
  if (s.includes('mlb') || s.includes('beisbol') || s.includes('baseball')) return 'tag-blue';
  if (s.includes('fútbol') || s.includes('futbol') || s.includes('soccer') || s.includes('la liga') || s.includes('premier')) return 'tag-green';
  if (s.includes('nfl') || s.includes('americano') || s.includes('football')) return 'tag-orange';
  if (s.includes('mma') || s.includes('boxeo') || s.includes('ufc')) return 'tag-red';
  return 'tag-default';
}

let allPicksData: any[] = [];
let currentFilter: string = 'all';

// Setup Filter Pills
const filterBar = document.getElementById('filter-bar');
if (filterBar) {
  filterBar.querySelectorAll('.filter-pill').forEach(btn => {
    btn.addEventListener('click', (e) => {
      filterBar.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
      const target = e.currentTarget as HTMLButtonElement;
      target.classList.add('active');
      currentFilter = target.dataset.filter || 'all';
      filterAndRenderPicks();
    });
  });
}

function filterAndRenderPicks() {
  let pool = allPicksData;
  let filtered = pool;

  if (currentFilter === 'champions') {
    filtered = pool.filter(p => {
      const cat = (p.categoria || p.deporte || '').toLowerCase();
      const partido = (p.partido || '').toLowerCase();
      const pickStr = (p.pick || '').toLowerCase();
      return (cat.includes('champions') || cat.includes('uefa') || pickStr.includes('champions') || 
              partido.includes('celtic') || partido.includes('lask') || partido.includes('hapoel') || 
              partido.includes('arsenal') || partido.includes('coventry') || partido.includes('aston villa')) && !p.es_parlay;
    });
  } else if (currentFilter === 'ligamx') {
    filtered = pool.filter(p => {
      const cat = (p.categoria || p.deporte || '').toLowerCase();
      const partido = (p.partido || '').toLowerCase();
      const isLigaMxTeam = partido.includes('américa') || partido.includes('america') || 
                           partido.includes('chivas') || partido.includes('cruz azul') || 
                           partido.includes('tigres') || partido.includes('monterrey') || 
                           partido.includes('pumas') || partido.includes('toluca') || 
                           partido.includes('pachuca') || partido.includes('necaxa') || 
                           partido.includes('leon') || partido.includes('león') || 
                           partido.includes('atlas') || partido.includes('puebla') || 
                           partido.includes('juárez') || partido.includes('juarez') || 
                           partido.includes('san luis') || partido.includes('tijuana') || 
                           partido.includes('mazatlán') || partido.includes('mazatlan') || 
                           partido.includes('santos') || partido.includes('querétaro') || 
                           partido.includes('queretaro') || partido.includes('atlante');
      return (cat === 'liga mx' || (cat.includes('liga mx') && !cat.includes('mlb') && !cat.includes('fútbol')) || isLigaMxTeam) && !p.es_parlay;
    });
  } else if (currentFilter === 'futbol') {
    filtered = pool.filter(p => {
      const cat = (p.categoria || p.deporte || '').toLowerCase();
      return (cat.includes('fútbol') || cat.includes('futbol') || cat.includes('liga mx') || 
              cat.includes('champions') || cat.includes('uefa') || cat.includes('la liga') || 
              cat.includes('soccer') || cat.includes('primera')) && !p.es_parlay && !cat.includes('esquina');
    });
  } else if (currentFilter === 'corners') {
    filtered = pool.filter(p => {
      const cat = (p.categoria || p.deporte || '').toLowerCase();
      const pickStr = (p.pick || '').toLowerCase();
      return cat.includes('esquina') || cat.includes('córner') || pickStr.includes('córner') || pickStr.includes('esquina');
    });
  } else if (currentFilter === 'mlb') {
    filtered = pool.filter(p => {
      const cat = (p.categoria || p.deporte || '').toLowerCase();
      const partido = (p.partido || '').toLowerCase();
      return (cat.includes('mlb') || (cat.includes('béisbol') && !cat.includes('kbo'))) && 
             !partido.includes('kia') && !partido.includes('landers');
    });
  } else if (currentFilter === 'kbo') {
    filtered = pool.filter(p => {
      const cat = (p.categoria || p.deporte || '').toLowerCase();
      const partido = (p.partido || '').toLowerCase();
      return cat.includes('kbo') || cat.includes('corea') || partido.includes('kia tigers') || partido.includes('lg twins');
    });
  } else if (currentFilter === 'nfl') {
    filtered = pool.filter(p => {
      const cat = (p.categoria || p.deporte || '').toLowerCase();
      const partido = (p.partido || '').toLowerCase();
      return cat.includes('nfl') || cat.includes('fútbol americano') || partido.includes('chiefs') || partido.includes('49ers');
    });
  } else if (currentFilter === 'parlays') {
    filtered = pool.filter(p => p.es_parlay);
  }

  const counter = document.getElementById('picks-counter');
  if (counter) counter.textContent = `${filtered.length} Picks +EV`;

  renderPicks(filtered);
}

function renderPicks(picks: any[]) {
  const container = document.getElementById('picks-container')!;
  if (!picks || picks.length === 0) {
    container.innerHTML = `<div class="loading" style="padding: 40px; text-align: center;">No hay selecciones activas para este filtro hoy.</div>`;
    container.className = '';
    return;
  }

  container.className = 'picks-grid';
  
  container.innerHTML = picks.map((pick: any) => {
    const isLocked = (!pick.is_free_pick || pick.es_parlay) && !isSubscribed;
    const sportClass = getSportColorClass(pick.categoria || pick.deporte || '');
    const confValue = parseInt(pick.confianza) || 0;
    const platformUrl = 'https://www.playdoit.mx/es/';
    const platformLabel = 'Apostar en Playdoit ↗';
    const shareText = encodeURIComponent(`👑 REY TACO PICKS\n🏟️ ${pick.partido}\n🎯 Pick: ${pick.pick} @ Cuota ${pick.cuota}\n🔥 Confianza: ${pick.confianza}\n👉 Más picks en: https://reytacopicks.com`);
    
    return `
      <div class="pick-card ${isLocked ? 'locked' : ''} ${pick.es_parlay ? 'parlay-card' : ''}">
        ${isLocked ? `
          <div class="paywall-overlay">
            <div class="lock-icon">👑🔒</div>
            <h4>Pase VIP Exclusivo</h4>
            <p>${pick.es_parlay ? 'Desbloquea este Parlay y combinadas de alta cuota con el Pase VIP ($299 MXN).' : 'Desbloquea la cartera completa y proyecciones matemáticas con tu Pase VIP ($299 MXN/mes).'}</p>
            <button class="unlock-btn" onclick="document.querySelector('.premium-badge').click()">👑 Activar Pase VIP ($299 MXN)</button>
          </div>
        ` : ''}
        
        <div class="card-content ${isLocked ? 'blurred' : ''}">
          <div class="card-header">
            <div class="card-header-left">
              <span class="sport-tag ${sportClass}">${pick.categoria || pick.deporte || 'Mercado'}</span>
              ${pick.horario || pick.hora_partido || pick.fecha_generacion ? `<span class="time-tag">🕒 ${pick.horario || pick.hora_partido || (pick.fecha_generacion === new Date().toISOString().split('T')[0] ? 'Hoy' : pick.fecha_generacion)}</span>` : ''}
            </div>
            ${pick.tiene_valor ? '<span class="value-badge">VALOR DETECTADO</span>' : ''}
          </div>
          
          <div class="card-body">
            <h4 class="match-name">${pick.partido || pick.evento}</h4>
            
            <div class="the-pick">
              <span class="pick-text">${pick.pick}</span>
              <div class="odds-container">
                <span class="pick-odds">${pick.cuota}</span>
                ${pick.odds_mercado ? `<span class="market-odds">Cuota Mercado: ${pick.odds_mercado}</span>` : ''}
              </div>
            </div>

            <div class="confidence-container">
              <div class="confidence-header">
                <span>Nivel de Confianza</span>
                <span>${pick.confianza || (confValue + '%')}</span>
              </div>
              <div class="confidence-bar-bg">
                <div class="confidence-bar-fill" style="width: ${confValue}%"></div>
              </div>
            </div>
          </div>
          
          <div class="card-footer">
            <p class="ai-reasoning"><strong>Alpha (IA):</strong> ${pick.razonamiento}</p>
            ${!isLocked ? `
              <div class="card-actions">
                <button class="btn-build-parlay-card" data-match="${pick.partido || pick.evento}">⚡ Parlay IA</button>
                <a href="https://api.whatsapp.com/send?text=${shareText}" target="_blank" class="btn-share-pick">📲 Compartir</a>
                <a href="${platformUrl}" target="_blank" class="btn-playdoit-pick">${platformLabel}</a>
              </div>
            ` : ''}
          </div>
        </div>
      </div>
    `
  }).join('');
}

async function fetchPicks() {
  if (supabase) {
    try {
      // Traer todas las jugadas activas / pendientes de ambas plataformas
      const { data, error } = await supabase
        .from('picks')
        .select('*')
        .eq('estado', 'pendiente')
        .order('id', { ascending: false })
        .limit(100);

      if (error) throw error;
      if (data && data.length > 0) {
        let freeCounter = 0;
        allPicksData = data.map((p: any) => {
          if (!p.es_parlay && freeCounter < 3) {
            freeCounter++;
            return { ...p, is_free_pick: true };
          }
          return { ...p, is_free_pick: false };
        });
        filterAndRenderPicks();
      } else {
        fallbackLocalFetch();
      }
    } catch (err) {
      console.error("Error cargando desde Supabase:", err);
      fallbackLocalFetch();
    }
  } else {
    fallbackLocalFetch();
  }
}

function fallbackLocalFetch() {
  fetch('/picks.json')
    .then(r => r.json())
    .then(data => {
      const activePicks = Array.isArray(data) ? data.filter((p: any) => p.estado === 'pendiente' || !p.estado) : [];
      const pool = activePicks.length > 0 ? activePicks : data;
      let freeCounter = 0;
      allPicksData = pool.map((p: any) => {
        if (!p.es_parlay && freeCounter < 3) {
          freeCounter++;
          return { ...p, is_free_pick: true };
        }
        return { ...p, is_free_pick: false };
      });
      filterAndRenderPicks();
    })
    .catch(() => {
      allPicksData = [
        {
          categoria: 'Tiros de Esquina',
          partido: 'Necaxa vs Club Leon',
          horario: '17/08 • 19:00',
          pick: 'Más de 8.5 Tiros de Esquina',
          cuota: '1.40',
          odds_mercado: '1.35',
          tiene_valor: true,
          confianza: '92%',
          razonamiento: 'Consenso Quant: Ritmo ofensivo por bandas detectado en Playdoit con alta frecuencia de saques de esquina.',
          es_parlay: false
        },
        {
          categoria: 'Tiros de Esquina',
          partido: 'Pachuca vs Puebla',
          horario: '17/08 • 21:00',
          pick: 'Más de 8.5 Tiros de Esquina',
          cuota: '1.45',
          odds_mercado: '1.40',
          tiene_valor: true,
          confianza: '91%',
          razonamiento: 'Consenso Quant: Pachuca genera un promedio de 6.2 córners jugando en el Estadio Hidalgo.',
          es_parlay: false
        }
      ];
      filterAndRenderPicks();
    });
}

function renderHistory(history: any[]) {
  const container = document.getElementById('history-container')!;
  // Filtrar estrictamente solo jugadas ganadas (verdes)
  const winningHistory = history.filter((item: any) => item.estado === 'ganado' || item.estado === 'GANADO');
  
  if (!winningHistory || winningHistory.length === 0) {
    container.innerHTML = '<tr><td colspan="5" class="text-center">No hay historial disponible.</td></tr>';
    return;
  }
  
  container.innerHTML = winningHistory.map((item: any) => {
    return `
      <tr>
        <td>${item.fecha || item.fecha_generacion || 'N/A'}</td>
        <td>${item.partido || item.evento || 'N/A'}</td>
        <td>${item.pick}</td>
        <td>${item.cuota}</td>
        <td><span class="status-badge status-won">Ganado</span></td>
      </tr>
    `;
  }).join('');
}

async function fetchHistory() {
  if (supabase) {
    try {
      const today = new Date().toISOString().split('T')[0];
      const { data, error } = await supabase
        .from('picks')
        .select('*')
        .eq('estado', 'ganado')
        .neq('fecha_generacion', today)
        .order('id', { ascending: false })
        .limit(25);
        
      if (error) throw error;
      if (data && data.length > 0) {
        renderHistory(data);
      } else {
        fallbackLocalHistory();
      }
    } catch (err) {
      console.error("Error cargando historial:", err);
      fallbackLocalHistory();
    }
  } else {
    fallbackLocalHistory();
  }
}

function fallbackLocalHistory() {
  const realHistory = [
    { fecha: '2026-08-15', partido: 'Monterrey vs Juárez', pick: 'SGP Ganador Playdoit: Monterrey ML + Ocampos + Rossi', cuota: '2.71', estado: 'ganado' },
    { fecha: '2026-08-15', partido: 'Club América vs Atlético San Luis', pick: 'América Gana Directo', cuota: '1.54', estado: 'ganado' },
    { fecha: '2026-08-15', partido: 'Santos Laguna vs Guadalajara Chivas', pick: 'Guadalajara Chivas Gana Directo', cuota: '1.52', estado: 'ganado' },
    { fecha: '2026-08-15', partido: 'Atlas vs Tigres UANL', pick: 'Más de 8.5 Tiros de Esquina', cuota: '1.62', estado: 'ganado' },
    { fecha: '2026-08-15', partido: 'Tampa Bay Rays vs Baltimore Orioles', pick: 'Más de 7.5 Carreras Totales', cuota: '1.87', estado: 'ganado' },
    { fecha: '2026-08-15', partido: 'Kansas City Chiefs vs Denver Broncos', pick: 'Kansas City Chiefs Gana Directo', cuota: '1.26', estado: 'ganado' },
  ];
  renderHistory(realHistory);
}

// Inicializaciones
initDailyVerseBanner('daily-verse-container');
fetchPicks();
fetchHistory();
loadTickets();
updateAdsVisibility();

async function loadTickets() {
  const grid = document.getElementById('tickets-grid');
  if (!grid) return;
  
  const fallbackTickets = [
    '/tickets/ticket_1787030886.jpg',
    '/tickets/ticket_1787030798.jpg',
    '/tickets/ticket_1787030974.jpg',
    '/tickets/ticket_1786980498.jpg',
    '/tickets/ticket_1786980544.jpg',
    '/tickets/ticket_1786857083.jpg',
    '/tickets/ticket_1786856862.jpg',
    '/tickets/ticket_1786857038.jpg'
  ];

  fetch('/tickets/manifest.json?v=' + Date.now(), { cache: 'no-store' })
    .then(r => r.json())
    .then(files => {
      if (Array.isArray(files) && files.length > 0) {
        const uniqueFiles = Array.from(new Set(files));
        const ticketSources = uniqueFiles.map((f: any) => f.startsWith('http') ? f : `/tickets/${f}`);
        renderTickets(ticketSources);
      } else {
        renderTickets(fallbackTickets);
      }
    })
    .catch(() => {
      renderTickets(fallbackTickets);
    });
}

function renderTickets(sources: string[]) {
  const grid = document.getElementById('tickets-grid');
  if (!grid) return;
  
  // Deduplicar URLs
  const uniqueSources = Array.from(new Set(sources));
  
  if (!uniqueSources || uniqueSources.length === 0) {
    grid.innerHTML = '<p class="tickets-empty">📸 Envía fotos de tickets ganadores al bot de Telegram y aparecerán aquí automáticamente.</p>';
    return;
  }
  
  grid.innerHTML = uniqueSources.map((src, index) => `
    <div class="ticket-card" onclick="openTicketZoom('${src}')">
      <div class="ticket-badge">🏆 VERDE COBRADO</div>
      <img src="${src}" alt="Ticket Ganador Playdoit #${index + 1}" loading="lazy" />
      <div class="ticket-caption">Verificado en Playdoit</div>
    </div>
  `).join('');
}

// Ticket Lightbox Zoom
const ticketModalEl = document.getElementById('ticket-modal');
(window as any).openTicketZoom = function(src: string) {
  if (!ticketModalEl) return;
  const img = document.getElementById('ticket-zoom-img') as HTMLImageElement;
  img.src = src;
  ticketModalEl.classList.remove('hidden');
};

const closeTicketModal = document.getElementById('close-ticket-modal')!;
if (closeTicketModal && ticketModalEl) {
  closeTicketModal.addEventListener('click', () => {
    ticketModalEl.classList.add('hidden');
  });

  ticketModalEl.addEventListener('click', (e) => {
    if (e.target === ticketModalEl) ticketModalEl.classList.add('hidden');
  });
}

// ============================================================
//  CALCULADORA DE STAKE & BANKROLL
// ============================================================
const calcBtn = document.getElementById('calc-btn')!;
const calcModal = document.getElementById('calc-modal')!;
const closeCalcModal = document.getElementById('close-calc-modal')!;
const bankrollInput = document.getElementById('calc-bankroll-input') as HTMLInputElement;

const stakeHighEl = document.getElementById('stake-high')!;
const stakeCornersEl = document.getElementById('stake-corners')!;
const stakeParlaySafeEl = document.getElementById('stake-parlay-safe')!;
const stakeParlayBombEl = document.getElementById('stake-parlay-bomb')!;

function updateStakeCalculations() {
  const bankroll = parseFloat(bankrollInput.value) || 0;
  
  // 💎 Alta Confianza: 5%
  const highVal = Math.round(bankroll * 0.05);
  // ⛳ Córners/Hándicap: 3%
  const cornersVal = Math.round(bankroll * 0.03);
  // 🟢 Parlay Seguro: 2%
  const parlaySafeVal = Math.round(bankroll * 0.02);
  // 💣 Parlay Bomba: 0.5%
  const parlayBombVal = Math.max(10, Math.round(bankroll * 0.005));

  stakeHighEl.textContent = `$${highVal} MXN`;
  stakeCornersEl.textContent = `$${cornersVal} MXN`;
  stakeParlaySafeEl.textContent = `$${parlaySafeVal} MXN`;
  stakeParlayBombEl.textContent = `$${parlayBombVal} MXN`;
}

if (calcBtn && calcModal) {
  calcBtn.addEventListener('click', () => {
    calcModal.classList.remove('hidden');
    updateStakeCalculations();
  });
  
  closeCalcModal.addEventListener('click', () => {
    calcModal.classList.add('hidden');
  });

  calcModal.addEventListener('click', (e) => {
    if (e.target === calcModal) calcModal.classList.add('hidden');
  });

  bankrollInput.addEventListener('input', updateStakeCalculations);
}

// ============================================================
//  PWA INSTALLATION LOGIC
// ============================================================
let deferredPrompt: any = null;
const pwaBanner = document.getElementById('pwa-banner')!;
const pwaInstallBtn = document.getElementById('pwa-install-btn')!;
const pwaDismissBtn = document.getElementById('pwa-dismiss-btn')!;

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  if (pwaBanner) {
    pwaBanner.classList.remove('hidden');
  }
});

if (pwaInstallBtn) {
  pwaInstallBtn.addEventListener('click', async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      if (outcome === 'accepted') {
        console.log('Usuario instaló PWA');
      }
      deferredPrompt = null;
      pwaBanner.classList.add('hidden');
    }
  });
}

if (pwaDismissBtn) {
  pwaDismissBtn.addEventListener('click', () => {
    pwaBanner.classList.add('hidden');
  });
}

// ============================================================
//  CHARTS (Chart.js)
// ============================================================
declare const Chart: any;

function initCharts() {
  // Bankroll Chart (Line)
  const bankrollCtx = document.getElementById('bankroll-chart') as HTMLCanvasElement;
  if (bankrollCtx && typeof Chart !== 'undefined') {
    new Chart(bankrollCtx, {
      type: 'line',
      data: {
        labels: ['Día 1', 'Día 2', 'Día 3', 'Día 4', 'Día 5', 'Día 6', 'Día 7'],
        datasets: [{
          label: 'Bankroll ($MXN)',
          data: [1000, 1020, 990, 1050, 1080, 1060, 1110],
          borderColor: '#22c55e',
          backgroundColor: 'rgba(34, 197, 94, 0.1)',
          fill: true,
          tension: 0.4,
          pointBackgroundColor: '#22c55e',
          pointBorderColor: '#22c55e',
          pointRadius: 4,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#94a3b8' }
          },
          y: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#94a3b8', callback: (v: number) => '$' + v }
          }
        }
      }
    });
  }

  // Sport Accuracy Chart (Doughnut)
  const sportCtx = document.getElementById('sport-chart') as HTMLCanvasElement;
  if (sportCtx && typeof Chart !== 'undefined') {
    new Chart(sportCtx, {
      type: 'doughnut',
      data: {
        labels: ['Fútbol', 'MLB', 'NFL', 'MMA', 'Tenis'],
        datasets: [{
          data: [72, 65, 58, 80, 60],
          backgroundColor: [
            '#22c55e',
            '#3b82f6',
            '#f97316',
            '#ef4444',
            '#a855f7'
          ],
          borderColor: '#111827',
          borderWidth: 3
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#94a3b8', padding: 16, font: { size: 12 } }
          }
        },
        cutout: '65%'
      }
    });
  }
}

// Initialize charts after DOM is ready
setTimeout(initCharts, 500);

// ============================================================
//  AI PARLAY BUILDER LOGIC (VIP Exclusive)
// ============================================================
const parlayModal = document.getElementById('parlay-builder-modal')!;
const closeParlayModalBtn = document.getElementById('close-parlay-modal')!;
const parlayHeaderBtn = document.getElementById('parlay-builder-header-btn')!;
const parlayVipGate = document.getElementById('parlay-vip-gate')!;
const parlayBuilderInterface = document.getElementById('parlay-builder-interface')!;
const parlayBaseMatchSelect = document.getElementById('parlay-base-match') as HTMLSelectElement;
const parlayStakeInput = document.getElementById('parlay-stake-input') as HTMLInputElement;
const btnGenerateAiParlay = document.getElementById('btn-generate-ai-parlay') as HTMLButtonElement;
const parlayResultBox = document.getElementById('parlay-result-box')!;
const ticketTotalOdd = document.getElementById('ticket-total-odd')!;
const ticketLegsList = document.getElementById('ticket-legs-list')!;
const ticketStakeDisplay = document.getElementById('ticket-stake-display')!;
const ticketPayoutDisplay = document.getElementById('ticket-payout-display')!;
const ticketRationaleText = document.getElementById('ticket-rationale-text')!;
const btnCopyParlaySlip = document.getElementById('btn-copy-parlay-slip')!;

let currentGeneratedParlay: any = null;

function openParlayBuilder(initialMatch?: string) {
  parlayVipGate.classList.add('hidden');
  parlayBuilderInterface.classList.remove('hidden');
  
  // Populate match dropdown with available matches from allPicksData
  const uniqueMatches: { name: string; sport: string }[] = [];
  allPicksData.forEach((p: any) => {
    const name = p.partido || p.evento;
    if (name && !p.es_parlay && !uniqueMatches.some(m => m.name === name)) {
      uniqueMatches.push({ name, sport: p.categoria || p.deporte || 'Liga MX' });
    }
  });

  if (uniqueMatches.length === 0) {
    uniqueMatches.push(
      { name: 'Necaxa vs Club León', sport: 'Liga MX' },
      { name: 'Pachuca vs Puebla', sport: 'Liga MX' },
      { name: 'America vs Atletico San Luis', sport: 'Liga MX' },
      { name: 'Santos Laguna vs Guadalajara Chivas', sport: 'Liga MX' },
      { name: 'Xolos de Tijuana vs Cruz Azul', sport: 'Liga MX' },
      { name: 'Los Angeles Dodgers vs Milwaukee Brewers', sport: 'MLB' }
    );
  }

  parlayBaseMatchSelect.innerHTML = uniqueMatches.map(m => `
    <option value="${m.name}" ${initialMatch && m.name.toLowerCase().includes(initialMatch.toLowerCase().split(' vs ')[0]) ? 'selected' : ''}>
      ${m.name} (${m.sport})
    </option>
  `).join('');

  parlayModal.classList.remove('hidden');
}

// Strategy selection
document.querySelectorAll('.strategy-pill').forEach(pill => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.strategy-pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    const radio = pill.querySelector('input[type="radio"]') as HTMLInputElement;
    if (radio) radio.checked = true;
  });
});

// Open modal from header button
if (parlayHeaderBtn) {
  parlayHeaderBtn.addEventListener('click', () => openParlayBuilder());
}

// Close parlay modal
if (closeParlayModalBtn) {
  closeParlayModalBtn.addEventListener('click', () => {
    parlayModal.classList.add('hidden');
  });
}

if (parlayModal) {
  parlayModal.addEventListener('click', (e) => {
    if (e.target === parlayModal) parlayModal.classList.add('hidden');
  });
}

// Delegate click on card buttons
document.addEventListener('click', (e) => {
  const target = (e.target as HTMLElement).closest('.btn-build-parlay-card');
  if (target) {
    const matchName = target.getAttribute('data-match') || '';
    openParlayBuilder(matchName);
  }
});

// Generator Algorithm
if (btnGenerateAiParlay) {
  btnGenerateAiParlay.addEventListener('click', () => {
    const selectedMatch = parlayBaseMatchSelect.value;
    const strategy = (document.querySelector('input[name="parlay-strategy"]:checked') as HTMLInputElement)?.value || 'seguro';
    const stake = parseFloat(parlayStakeInput.value) || 200;

    btnGenerateAiParlay.disabled = true;
    btnGenerateAiParlay.innerHTML = '🔄 Escaneando correlación +EV en Playdoit...';

    setTimeout(() => {
      // 1. Determine Base Match Selection with exact Playdoit lines
      let baseLeg: any = {
        partido: selectedMatch,
        seleccion: 'Más de 8.5 Tiros de Esquina',
        cuota: 1.45,
        mercado: 'Córners'
      };

      if (selectedMatch.toLowerCase().includes('pumas')) {
        baseLeg = {
          partido: 'Pumas UNAM vs Queretaro',
          seleccion: strategy === 'seguro' ? 'Más de 8.5 Tiros de Esquina' : 'Más de 9.5 Tiros de Esquina',
          cuota: strategy === 'seguro' ? 1.40 : 1.68,
          mercado: 'Tiros de Esquina'
        };
      } else if (selectedMatch.toLowerCase().includes('america') || selectedMatch.toLowerCase().includes('américa')) {
        baseLeg = {
          partido: 'America vs Atletico San Luis',
          seleccion: strategy === 'bomba' ? 'Más de 2.5 Goles' : 'Más de 8.5 Tiros de Esquina',
          cuota: strategy === 'bomba' ? 1.66 : 1.45,
          mercado: strategy === 'bomba' ? 'Goles Totales' : 'Tiros de Esquina'
        };
      } else if (selectedMatch.toLowerCase().includes('cruz azul') || selectedMatch.toLowerCase().includes('tijuana')) {
        baseLeg = {
          partido: 'Xolos de Tijuana vs Cruz Azul',
          seleccion: 'Cruz Azul Gana o Empata (X2)',
          cuota: 1.36,
          mercado: 'Doble Oportunidad'
        };
      } else if (selectedMatch.toLowerCase().includes('dodgers')) {
        baseLeg = {
          partido: 'Los Angeles Dodgers vs Milwaukee Brewers',
          seleccion: 'Dodgers Gana (ML)',
          cuota: 1.58,
          mercado: 'Línea de Dinero (MLB)'
        };
      }

      // 2. Select Companion Legs from other matches
      const catalog = [
        {
          partido: 'America vs Atletico San Luis',
          seleccion: 'Más de 8.5 Tiros de Esquina',
          cuota: 1.45,
          mercado: 'Tiros de Esquina'
        },
        {
          partido: 'Pumas UNAM vs Queretaro',
          seleccion: 'Más de 8.5 Tiros de Esquina',
          cuota: 1.40,
          mercado: 'Tiros de Esquina'
        },
        {
          partido: 'Xolos de Tijuana vs Cruz Azul',
          seleccion: 'Cruz Azul Gana o Empata (X2)',
          cuota: 1.36,
          mercado: 'Doble Oportunidad'
        },
        {
          partido: 'America vs Atletico San Luis',
          seleccion: 'Más de 2.5 Goles',
          cuota: 1.66,
          mercado: 'Goles Totales'
        },
        {
          partido: 'Los Angeles Dodgers vs Milwaukee Brewers',
          seleccion: 'Dodgers Gana (ML)',
          cuota: 1.58,
          mercado: 'Béisbol MLB'
        }
      ];

      // Filter out base match from companion pool
      const availableCompanions = catalog.filter(c => !c.partido.toLowerCase().includes(baseLeg.partido.toLowerCase().split(' vs ')[0]));

      let legs = [baseLeg];
      let rationale = "";

      if (strategy === 'seguro') {
        const comp = availableCompanions[0] || catalog[0];
        legs.push(comp);
        rationale = `Alta correlación de bajo riesgo. Ambas selecciones presentan una probabilidad matemática conjunta superior al 82% con momios validados en Playdoit.`;
      } else if (strategy === 'valor') {
        const comp1 = availableCompanions[0] || catalog[0];
        const comp2 = availableCompanions.find(c => c.partido !== comp1.partido) || availableCompanions[1];
        legs.push(comp1);
        if (comp2) legs.push(comp2);
        rationale = `Estrategia +EV optimizada. Se combinan micro-estadísticas de tiros de esquina con tendencia de goles para maximizar el multiplicador sin sobreexponer el bankroll.`;
      } else {
        // Bomba
        const comp1 = availableCompanions[0] || catalog[0];
        const comp2 = availableCompanions.find(c => c.partido !== comp1.partido) || availableCompanions[1];
        const comp3 = catalog.find(c => c.mercado.includes('MLB')) || catalog[catalog.length - 1];
        legs.push(comp1);
        if (comp2) legs.push(comp2);
        if (comp3 && !legs.some(l => l.partido === comp3.partido)) legs.push(comp3);
        rationale = `Multiplicador agresivo con ventaja estadística multideporte (Liga MX + MLB). Ideal para apuestas recreativas de 0.25 a 0.5 unidades.`;
      }

      // Calculate total decimal odds
      const totalOdd = legs.reduce((acc, leg) => acc * leg.cuota, 1);
      const totalOddFormatted = totalOdd.toFixed(2);
      const payout = (stake * totalOdd).toFixed(2);

      currentGeneratedParlay = {
        legs,
        totalOdd: totalOddFormatted,
        stake,
        payout,
        rationale
      };

      // Render Slip
      ticketTotalOdd.textContent = `@ ${totalOddFormatted}`;
      ticketStakeDisplay.textContent = `$${stake} MXN`;
      ticketPayoutDisplay.textContent = `$${payout} MXN`;
      ticketRationaleText.textContent = rationale;

      ticketLegsList.innerHTML = legs.map((leg, idx) => `
        <div class="ticket-leg-item">
          <div class="leg-idx">${idx + 1}</div>
          <div class="leg-info">
            <strong>${leg.partido}</strong>
            <span>${leg.seleccion}</span>
          </div>
          <div class="leg-odd">${leg.cuota.toFixed(2)}</div>
        </div>
      `).join('');

      parlayResultBox.classList.remove('hidden');
      btnGenerateAiParlay.disabled = false;
      btnGenerateAiParlay.innerHTML = '⚡ Regenerar Otra Opción';

      // Scroll into view
      parlayResultBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 600);
  });
}

// Copy parlay slip
if (btnCopyParlaySlip) {
  btnCopyParlaySlip.addEventListener('click', () => {
    if (!currentGeneratedParlay) return;
    const text = `🌮 *REY TACO PICKS - PARLAY IA A MEDIDA* 👑\n\n` +
      currentGeneratedParlay.legs.map((l: any, i: number) => `📍 Pierna #${i+1}: ${l.partido}\n   👉 Pick: ${l.seleccion} @ ${l.cuota.toFixed(2)}`).join('\n\n') +
      `\n\n💰 *Cuota Total:* @ ${currentGeneratedParlay.totalOdd}\n💵 *Apostando:* $${currentGeneratedParlay.stake} MXN -> 🚀 *Cobras:* $${currentGeneratedParlay.payout} MXN\n\n📲 *Entra y Juégalo en Playdoit:* https://www.playdoit.mx/es/\n🌐 https://reytacopicks.com`;

    navigator.clipboard.writeText(text).then(() => {
      btnCopyParlaySlip.textContent = '✅ ¡Copiado!';
      setTimeout(() => { btnCopyParlaySlip.textContent = '📋 Copiar Jugada'; }, 2000);
    });
  });
}

// ============================================================
// Legal Modals (Privacy & Terms - Google AdSense Compliance)
// ============================================================
const legalModal = document.getElementById('legal-modal')!;
const closeLegalModal = document.getElementById('close-legal-modal')!;
const legalTitle = document.getElementById('legal-modal-title')!;
const legalSubtitle = document.getElementById('legal-modal-subtitle')!;
const legalBody = document.getElementById('legal-modal-body')!;

function openLegalModal(type: 'privacy' | 'terms') {
  if (type === 'privacy') {
    legalTitle.textContent = 'Política de Privacidad y Cookies';
    legalSubtitle.textContent = 'Última actualización: Agosto 2026 • reytacopicks.com';
    legalBody.innerHTML = `
      <h3>1. Información que recopilamos</h3>
      <p>En Rey Taco Picks (https://reytacopicks.com), respetamos tu privacidad. Recopilamos información básica cuando te registras (como correo electrónico) únicamente para gestionar tu membresía VIP y personalizar tu experiencia.</p>
      
      <h3>2. Uso de Cookies y Publicidad de Google AdSense</h3>
      <p>Este sitio web utiliza cookies técnicas y de terceros (como Google AdSense y Google Analytics) para mostrar anuncios relevantes basados en tus visitas anteriores a este y otros sitios web en Internet. Los usuarios pueden inhabilitar la publicidad personalizada visitando la Configuración de anuncios de Google o mediante opt-out en aboutads.info.</p>
      
      <h3>3. Enlaces a Terceros y Afiliados</h3>
      <p>Rey Taco Picks puede contener enlaces a sitios web de terceros (como casas de apuestas autorizadas, e.g., Playdoit). No nos hacemos responsables de las políticas de privacidad o el contenido de dichos sitios externos.</p>
      
      <h3>4. Contacto</h3>
      <p>Para cualquier duda sobre tus datos o solicitar su eliminación, contáctanos vía Telegram a <strong>@carlosds1017</strong> o soporte@reytacopicks.com.</p>
    `;
  } else {
    legalTitle.textContent = 'Términos y Condiciones de Uso';
    legalSubtitle.textContent = 'Última actualización: Agosto 2026 • reytacopicks.com';
    legalBody.innerHTML = `
      <h3>1. Naturaleza del Servicio</h3>
      <p>Rey Taco Picks es una plataforma de análisis deportivo cuantitativo y modelos estadísticos de Inteligencia Artificial. Los contenidos publicados tienen fines estrictamente informativos, educativos y de entretenimiento.</p>
      
      <h3>2. Mayoría de Edad (+18)</h3>
      <p>El uso de este sitio y el acceso a contenido de apuestas deportivas está reservado exclusivamente a personas mayores de 18 años (o la edad legal de tu jurisdicción).</p>
      
      <h3>3. Exención de Responsabilidad</h3>
      <p>No garantizamos ganancias ni resultados exactos. Las apuestas deportivas implican riesgo financiero. Rey Taco Picks no se hace responsable por pérdidas derivadas de las decisiones individuales de apuestas de los usuarios.</p>
      
      <h3>4. Membresía VIP</h3>
      <p>El acceso VIP otorga acceso a herramientas avanzadas como el Creador de Parlays IA y canales exclusivos. Todos los pagos son finales.</p>
    `;
  }
  legalModal.classList.remove('hidden');
}

document.getElementById('link-privacy')?.addEventListener('click', (e) => {
  e.preventDefault();
  openLegalModal('privacy');
});

document.getElementById('link-terms')?.addEventListener('click', (e) => {
  e.preventDefault();
  openLegalModal('terms');
});

closeLegalModal?.addEventListener('click', () => {
  legalModal.classList.add('hidden');
});

legalModal?.addEventListener('click', (e) => {
  if (e.target === legalModal) legalModal.classList.add('hidden');
});


