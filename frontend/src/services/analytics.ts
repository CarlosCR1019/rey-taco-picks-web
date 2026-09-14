export type ConversionEvent =
  | 'free_pick_viewed'
  | 'history_viewed'
  | 'telegram_clicked'
  | 'vip_offer_viewed'
  | 'vip_primary_clicked'
  | 'vip_auth_required'
  | 'checkout_started'
  | 'vip_plan_selected'
  | 'checkout_cancelled'
  | 'subscription_confirmed'
  | 'miniapp_opened'
  | 'quiniela_viewed'
  | 'quiniela_started'
  | 'quiniela_submitted'
  | 'spei_whatsapp_clicked';

export type AnalyticsProperties = Partial<Readonly<{
  surface: 'web' | 'telegram_miniapp';
  window_slot: '12am' | '6am' | '12pm' | '6pm';
  public_pick_count: number;
  premium_pick_count: number;
  week_key: string;
  plan: 'weekly' | 'monthly';
  billing_mode: 'payment' | 'subscription';
}>> & Readonly<Record<string, unknown>>;

type AnalyticsPropertiesSource = AnalyticsProperties | (() => AnalyticsProperties);

type AnalyticsWindow = Window & {
  dataLayer?: Array<{ event: ConversionEvent }>;
  umami?: {
    track: (event: string, properties?: Record<string, string>) => void;
  };
};

const emitted = new Set<string>();
const pendingUmamiEvents: Array<{ event: ConversionEvent; properties: Record<string, string> }> = [];
const MAX_PENDING_UMAMI_EVENTS = 32;

function umamiWebsiteId(): string {
  const value = String(import.meta.env.VITE_UMAMI_WEBSITE_ID ?? '').trim().toLowerCase();
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value) ? value : '';
}

function allowedProperties(properties?: AnalyticsProperties): Record<string, string> {
  const result: Record<string, string> = {};
  if (properties?.surface === 'web' || properties?.surface === 'telegram_miniapp') result.surface = properties.surface;
  if (properties?.window_slot === '12am' || properties?.window_slot === '6am' || properties?.window_slot === '12pm' || properties?.window_slot === '6pm') {
    result.window_slot = properties.window_slot;
  }
  for (const key of ['public_pick_count', 'premium_pick_count'] as const) {
    const value = properties?.[key];
    if (Number.isInteger(value) && Number(value) >= 0 && Number(value) <= 6) result[key] = String(value);
  }
  const weekKey = properties?.week_key;
  if (typeof weekKey === 'string' && /^[a-z0-9][a-z0-9_-]{0,31}$/.test(weekKey)) {
    result.week_key = weekKey;
  }
  if (properties?.plan === 'weekly' || properties?.plan === 'monthly') result.plan = properties.plan;
  if (properties?.billing_mode === 'payment' || properties?.billing_mode === 'subscription') {
    result.billing_mode = properties.billing_mode;
  }
  return result;
}

function sendToUmami(event: ConversionEvent, properties: Record<string, string>): void {
  if (!umamiWebsiteId()) return;
  try {
    const target = window as AnalyticsWindow;
    if (target.umami) {
      target.umami.track(event, properties);
    } else if (pendingUmamiEvents.length < MAX_PENDING_UMAMI_EVENTS) {
      pendingUmamiEvents.push({ event, properties });
    }
  } catch {
    // Analytics must never block the application.
  }
}

function flushPendingUmamiEvents(): void {
  const target = window as AnalyticsWindow;
  if (!umamiWebsiteId() || !target.umami) return;
  const pending = pendingUmamiEvents.splice(0);
  for (const item of pending) sendToUmami(item.event, item.properties);
}

export function initUmami(): void {
  const websiteId = umamiWebsiteId();
  if (!websiteId || typeof document === 'undefined' || document.getElementById('umami-script')) return;
  const script = document.createElement('script');
  script.id = 'umami-script';
  script.defer = true;
  script.dataset.websiteId = websiteId;
  script.dataset.excludeSearch = 'true';
  script.dataset.excludeHash = 'true';
  script.src = 'https://cloud.umami.is/script.js';
  script.onload = flushPendingUmamiEvents;
  script.onerror = () => undefined;
  document.head.appendChild(script);
}

export function trackConversion(event: ConversionEvent, properties?: AnalyticsProperties): void {
  const safeProperties = allowedProperties(properties);
  const key = `${event}|${safeProperties.surface ?? ''}|${safeProperties.window_slot ?? ''}|${safeProperties.week_key ?? ''}|${safeProperties.plan ?? ''}|${safeProperties.billing_mode ?? ''}`;
  if (emitted.has(key)) return;
  emitted.add(key);
  const target = window as AnalyticsWindow;
  (target.dataLayer ??= []).push({ event });
  sendToUmami(event, safeProperties);
}

export function resetAnalyticsForTests(): void {
  emitted.clear();
  pendingUmamiEvents.splice(0);
}

export function trackWhenVisible(
  element: Element | null,
  event: ConversionEvent,
  properties?: AnalyticsPropertiesSource,
): void {
  if (!element || typeof IntersectionObserver === 'undefined') return;
  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) {
      trackConversion(event, typeof properties === 'function' ? properties() : properties);
      observer.disconnect();
    }
  }, { threshold: 0.25 });
  observer.observe(element);
}
