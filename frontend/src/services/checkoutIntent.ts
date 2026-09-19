export type CheckoutPlan = 'weekly' | 'monthly';

const PLAN_KEY = 'rey_taco_checkout_plan';
const AT_KEY = 'rey_taco_checkout_plan_at';
const MAX_AGE_MS = 30 * 60 * 1000;

export function saveCheckoutIntent(plan: CheckoutPlan): void {
  try {
    sessionStorage.setItem(PLAN_KEY, plan);
    sessionStorage.setItem(AT_KEY, String(Date.now()));
  } catch {}
}

export function readCheckoutIntent(): CheckoutPlan | null {
  try {
    const val = sessionStorage.getItem(PLAN_KEY);
    const at = Number(sessionStorage.getItem(AT_KEY) || 0);
    if (!val || (val !== 'weekly' && val !== 'monthly')) {
      return null;
    }
    if (at && Date.now() - at > MAX_AGE_MS) {
      clearCheckoutIntent();
      return null;
    }
    return val;
  } catch {
    return null;
  }
}

export function clearCheckoutIntent(): void {
  try {
    sessionStorage.removeItem(PLAN_KEY);
    sessionStorage.removeItem(AT_KEY);
  } catch {}
}

export function navigateWithCheckoutIntent(
  url: string,
  plan: CheckoutPlan,
  navigate: (target: string) => void
): boolean {
  saveCheckoutIntent(plan);
  try {
    navigate(url);
    return true;
  } catch {
    return false;
  }
}
