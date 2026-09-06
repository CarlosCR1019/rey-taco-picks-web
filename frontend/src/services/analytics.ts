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

type UmamiCall = [event: string, options?: { data?: Record<string, string> }];
type UmamiTracker = { track?: (event: string, data?: Record<string, string>) => void; q?: UmamiCall[] };

type AnalyticsWindow = Window & {
  dataLayer?: Array<{ event: ConversionEvent }>;
  umami?: UmamiTracker;
};

const emitted = new Set<string>();

function umamiWebsiteId(): string {
  const value = String(import.meta.env.VITE_UMAMI_WEBSITE_ID ?? 'a100caee-dd0f-4380-b361-103eecbaed0e').trim();
  return /^[a-z0-9-]{8,80}$/i.test(value) ? value : '';
}

function allowedProperties(properties?: AnalyticsProperties): Record<string, string> {
  const result: Record<string, string> = {};
  if (properties?.surface === 'web' || properties?.surface === 'telegram_miniapp') result.surface = properties.surface;
  if (properties?.window_slot === '12am' || properties?.window_slot === '6am' || properties?.window_slot === '12pm' || properties?.window_slot === '6pm') {
    result.window_slot = properties.window_slot;
  }
  return result;
}

function sendToUmami(event: ConversionEvent, properties: Record<string, string>): void {
  if (!umamiWebsiteId()) return;
  const target = window as AnalyticsWindow;
  target.umami?.track?.(event, properties);
}

function ensureUmamiQueue(target: AnalyticsWindow): void {
  target.umami ??= {};
  target.umami.q ??= [];
}

export function initUmami(): void {
  const websiteId = umamiWebsiteId();
  if (!websiteId || typeof document === 'undefined' || document.getElementById('umami-script')) return;
  ensureUmamiQueue(window as AnalyticsWindow);
  const script = document.createElement('script');
  script.id = 'umami-script';
  script.defer = true;
  script.dataset.websiteId = websiteId;
  script.src = 'https://cloud.umami.is/script.js';
  script.onload = () => {
    const target = window as AnalyticsWindow;
    const queued = target.umami?.q ?? [];
    const track = target.umami?.track;
    if (!track) return;
    target.umami!.q = [];
    queued.forEach(([event, options]) => track(event, options?.data));
  };
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
  if (target.umami?.track) sendToUmami(event, safeProperties);
  else if (umamiWebsiteId()) {
    ensureUmamiQueue(target);
    target.umami!.q!.push([event, { data: safeProperties }]);
  }
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
