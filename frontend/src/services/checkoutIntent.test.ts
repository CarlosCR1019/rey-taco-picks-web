import { beforeEach, describe, expect, it } from 'vitest';
import { clearCheckoutIntent, navigateWithCheckoutIntent, readCheckoutIntent, saveCheckoutIntent } from './checkoutIntent';

describe('checkout intent', () => {
  beforeEach(() => sessionStorage.clear());

  it('stores and reads weekly and monthly plans', () => {
    saveCheckoutIntent('weekly');
    expect(readCheckoutIntent()).toBe('weekly');
    saveCheckoutIntent('monthly');
    expect(readCheckoutIntent()).toBe('monthly');
  });

  it('returns null for invalid or missing values', () => {
    sessionStorage.setItem('rey_taco_checkout_plan', 'annual');
    expect(readCheckoutIntent()).toBeNull();
    sessionStorage.removeItem('rey_taco_checkout_plan');
    expect(readCheckoutIntent()).toBeNull();
  });

  it('expires an intent after thirty minutes or when its timestamp is invalid', () => {
    sessionStorage.setItem('rey_taco_checkout_plan', 'weekly');
    sessionStorage.setItem('rey_taco_checkout_plan_at', String(Date.now() - 31 * 60 * 1000));
    expect(readCheckoutIntent()).toBeNull();
    sessionStorage.setItem('rey_taco_checkout_plan', 'weekly');
    sessionStorage.setItem('rey_taco_checkout_plan_at', 'nope');
    expect(readCheckoutIntent()).toBeNull();
  });

  it('clears the stored intent', () => {
    saveCheckoutIntent('weekly');
    clearCheckoutIntent();
    expect(readCheckoutIntent()).toBeNull();
  });

  it('accepts an injected storage implementation for redirect preparation', () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    } as Storage;
    saveCheckoutIntent('weekly', storage);
    expect(readCheckoutIntent(storage)).toBe('weekly');
    clearCheckoutIntent(storage);
    expect(readCheckoutIntent(storage)).toBeNull();
  });

  it('fails safely when storage throws', () => {
    const storage = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); }, removeItem: () => { throw new Error('blocked'); } } as unknown as Storage;
    expect(() => saveCheckoutIntent('weekly', storage)).not.toThrow();
    expect(readCheckoutIntent(storage)).toBeNull();
    expect(() => clearCheckoutIntent(storage)).not.toThrow();
  });

  it('fails safely when the sessionStorage getter throws', () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
    Object.defineProperty(window, 'sessionStorage', { configurable: true, get: () => { throw new Error('blocked'); } });
    expect(() => saveCheckoutIntent('weekly')).not.toThrow();
    expect(readCheckoutIntent()).toBeNull();
    expect(() => clearCheckoutIntent()).not.toThrow();
    if (descriptor) Object.defineProperty(window, 'sessionStorage', descriptor);
  });

  it('clears before navigation and restores after navigation failure', () => {
    const storage = sessionStorage;
    saveCheckoutIntent('weekly', storage);
    const failed = navigateWithCheckoutIntent('https://checkout.stripe.com/c/pay', 'weekly', () => { throw new Error('navigation'); }, storage);
    expect(failed).toBe(false);
    expect(readCheckoutIntent(storage)).toBe('weekly');
    expect(navigateWithCheckoutIntent('https://checkout.stripe.com/c/pay', 'weekly', () => undefined, storage)).toBe(true);
    expect(readCheckoutIntent(storage)).toBeNull();
  });
});
