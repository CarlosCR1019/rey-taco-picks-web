export function initTelegramMiniApp(_root?: HTMLElement | null, _options?: Record<string, unknown>): void {}

export function isTelegramMiniAppLocation(_location?: unknown, _path?: unknown): boolean {
  if (typeof window === 'undefined') return false;
  return new URLSearchParams(window.location.search).get('view') === 'telegram';
}
