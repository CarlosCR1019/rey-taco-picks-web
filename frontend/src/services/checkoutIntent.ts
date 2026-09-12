export type CheckoutPlan = 'weekly' | 'monthly';

const CHECKOUT_INTENT_KEY = 'rey_taco_checkout_plan';
const CHECKOUT_INTENT_AT_KEY = 'rey_taco_checkout_plan_at';
const CHECKOUT_INTENT_TTL_MS = 30 * 60 * 1000;

function resolveStorage(storage?: Storage): Storage | null {
  if (storage) return storage;
  try { return typeof window !== 'undefined' ? window.sessionStorage : null; } catch { return null; }
}

export function navigateWithCheckoutIntent(
  url: string,
  plan: CheckoutPlan,
  navigate: (url: string) => void,
  storage?: Storage,
): boolean {
  const target = resolveStorage(storage);
  clearCheckoutIntent(target ?? undefined);
  try { navigate(url); return true; }
  catch { saveCheckoutIntent(plan, target ?? undefined); return false; }
}

export function saveCheckoutIntent(plan: CheckoutPlan, storage?: Storage): void {
  const target = resolveStorage(storage);
  try { target?.setItem(CHECKOUT_INTENT_KEY, plan); target?.setItem(CHECKOUT_INTENT_AT_KEY, String(Date.now())); } catch { /* storage is optional */ }
}

export function readCheckoutIntent(storage?: Storage): CheckoutPlan | null {
  const target = resolveStorage(storage);
  try {
    const value = target?.getItem(CHECKOUT_INTENT_KEY);
    const at = Number(target?.getItem(CHECKOUT_INTENT_AT_KEY));
    if ((value !== 'weekly' && value !== 'monthly') || !Number.isFinite(at) || Date.now() - at > CHECKOUT_INTENT_TTL_MS || Date.now() - at < 0) { clearCheckoutIntent(target ?? undefined); return null; }
    return value;
  } catch { return null; }
}

export function clearCheckoutIntent(storage?: Storage): void {
  const target = resolveStorage(storage);
  try { target?.removeItem(CHECKOUT_INTENT_KEY); target?.removeItem(CHECKOUT_INTENT_AT_KEY); } catch { /* storage is optional */ }
}
