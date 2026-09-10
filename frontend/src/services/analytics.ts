export type ConversionEvent =
  | 'free_pick_viewed'
  | 'history_viewed'
  | 'telegram_clicked'
  | 'vip_offer_viewed'
  | 'vip_primary_clicked'
  | 'vip_auth_required'
  | 'checkout_started'
  | 'checkout_cancelled'
  | 'subscription_confirmed'
  | 'miniapp_opened';

export type AnalyticsProperties = Partial<Readonly<{
  surface: 'web' | 'telegram_miniapp';
  window_slot: '12am' | '6am' | '12pm' | '6pm';
  public_pick_count: number;
  premium_pick_count: number;
}>> & Readonly<Record<string, unknown>>;

type AnalyticsPropertiesSource = AnalyticsProperties | (() => AnalyticsProperties);

type PlausibleCall = [event: string, options?: { props?: Record<string, string> }];
type PlausibleFunction = ((event: string, options?: { props?: Record<string, string> }) => void) & {
  q?: PlausibleCall[];
};

type AnalyticsWindow = Window & {
  dataLayer?: Array<{ event: ConversionEvent }>;
  plausible?: PlausibleFunction;
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
  for (const key of ['public_pick_count', 'premium_pick_count'] as const) {
    const value = properties?.[key];
    if (Number.isInteger(value) && Number(value) >= 0 && Number(value) <= 6) result[key] = String(value);
  }
  return result;
}

function sendToPlausible(event: ConversionEvent, properties: Record<string, string>): void {
  if (!plausibleDomain()) return;
  const target = window as AnalyticsWindow;
  target.plausible?.(event, { props: properties });
}

function ensurePlausibleQueue(target: AnalyticsWindow): void {
  if (typeof target.plausible === 'function') return;
  const queued = ((event: string, options?: { props?: Record<string, string> }) => {
    (queued.q ??= []).push([event, options]);
  }) as PlausibleFunction;
  target.plausible = queued;
}

export function initPlausible(): void {
  const domain = plausibleDomain();
  if (!domain || typeof document === 'undefined' || document.getElementById('plausible-script')) return;
  ensurePlausibleQueue(window as AnalyticsWindow);
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
