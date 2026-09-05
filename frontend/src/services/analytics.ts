export type ConversionEvent =
  | 'free_pick_viewed'
  | 'history_viewed'
  | 'telegram_clicked'
  | 'vip_offer_viewed'
  | 'checkout_started'
  | 'subscription_confirmed'
  | 'miniapp_opened';

export type AnalyticsProperties = Partial<Readonly<{
  surface: 'web' | 'telegram_miniapp';
  window_slot: '12am' | '6am' | '12pm' | '6pm';
}>> & Readonly<Record<string, unknown>>;

type AnalyticsWindow = Window & {
  dataLayer?: Array<{ event: ConversionEvent }>;
  plausible?: (event: string, options?: { props?: Record<string, string> }) => void;
};

const emitted = new Set<string>();

function plausibleDomain(): string {
  const value = String(import.meta.env.VITE_PLAUSIBLE_DOMAIN ?? '').trim();
  return /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::\d{1,5})?$/i.test(value) ? value : '';
}

function allowedProperties(properties?: AnalyticsProperties): Record<string, string> {
  const result: Record<string, string> = {};
  if (properties?.surface === 'web' || properties?.surface === 'telegram_miniapp') result.surface = properties.surface;
  if (properties?.window_slot === '12am' || properties?.window_slot === '6am' || properties?.window_slot === '12pm' || properties?.window_slot === '6pm') {
    result.window_slot = properties.window_slot;
  }
  return result;
}

function sendToPlausible(event: ConversionEvent, properties: Record<string, string>): void {
  if (!plausibleDomain()) return;
  const target = window as AnalyticsWindow;
  if (typeof target.plausible === 'function') {
    target.plausible(event, { props: properties });
    return;
  }
  void target.fetch('/api/event', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name: event, domain: plausibleDomain(), props: properties }),
  }).catch(() => undefined);
}

export function initPlausible(): void {
  const domain = plausibleDomain();
  if (!domain || typeof document === 'undefined' || document.getElementById('plausible-script')) return;
  const script = document.createElement('script');
  script.id = 'plausible-script';
  script.defer = true;
  script.dataset.domain = domain;
  script.src = 'https://plausible.io/js/script.js';
  script.onerror = () => undefined;
  document.head.appendChild(script);
}

export function trackConversion(event: ConversionEvent, properties?: AnalyticsProperties): void {
  const safeProperties = allowedProperties(properties);
  const key = `${event}|${safeProperties.surface ?? ''}|${safeProperties.window_slot ?? ''}`;
  if (emitted.has(key)) return;
  emitted.add(key);
  const target = window as AnalyticsWindow;
  (target.dataLayer ??= []).push({ event });
  sendToPlausible(event, safeProperties);
}

export function resetAnalyticsForTests(): void {
  emitted.clear();
}

export function trackWhenVisible(element: Element | null, event: ConversionEvent, properties?: AnalyticsProperties): void {
  if (!element || typeof IntersectionObserver === 'undefined') return;
  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) {
      trackConversion(event, properties);
      observer.disconnect();
    }
  }, { threshold: 0.25 });
  observer.observe(element);
}
