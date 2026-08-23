export type AdConfig = { slot: string; client: string };

export function getAdConfig(slot: string | undefined, client: string | undefined): AdConfig | null {
  const safeSlot = slot?.trim();
  const safeClient = client?.trim();
  return safeSlot && safeClient ? { slot: safeSlot, client: safeClient } : null;
}

export function mountAd(container: HTMLElement, config: AdConfig | null): void {
  if (!config) return;
  if (!document.querySelector('script[data-rey-taco-adsense]')) {
    const script = document.createElement('script');
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.dataset.reyTacoAdsense = 'true';
    script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(config.client)}`;
    document.head.append(script);
  }
  container.classList.remove('hidden');
  container.innerHTML = '<span class="ad-label">PUBLICIDAD</span>';
  const ad = document.createElement('ins');
  ad.className = 'adsbygoogle';
  ad.style.display = 'block';
  ad.dataset.adClient = config.client;
  ad.dataset.adSlot = config.slot;
  ad.dataset.adFormat = 'auto';
  ad.dataset.fullWidthResponsive = 'true';
  container.append(ad);
  try {
    const target = window as typeof window & { adsbygoogle?: unknown[] };
    (target.adsbygoogle ??= []).push({});
  } catch {
    container.classList.add('hidden');
  }
}
