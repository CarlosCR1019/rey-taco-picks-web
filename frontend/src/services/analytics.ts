export type ConversionEvent =
  | 'free_pick_viewed'
  | 'history_viewed'
  | 'telegram_clicked'
  | 'vip_offer_viewed'
  | 'checkout_started'
  | 'subscription_confirmed';

const emitted = new Set<ConversionEvent>();

export function trackConversion(event: ConversionEvent): void {
  if (emitted.has(event)) return;
  emitted.add(event);
  const target = window as typeof window & { dataLayer?: Array<{ event: ConversionEvent }> };
  (target.dataLayer ??= []).push({ event });
}

export function trackWhenVisible(element: Element | null, event: ConversionEvent): void {
  if (!element || typeof IntersectionObserver === 'undefined') return;
  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) {
      trackConversion(event);
      observer.disconnect();
    }
  }, { threshold: 0.25 });
  observer.observe(element);
}
