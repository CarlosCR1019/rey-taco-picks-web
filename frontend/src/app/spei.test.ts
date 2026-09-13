import { describe, expect, it } from 'vitest';
import { speiWhatsAppUrl, type SpeiPlan } from './spei';

describe('SPEI WhatsApp links', () => {
  it('builds the seven-day request for the commercial number', () => {
    const url = new URL(speiWhatsAppUrl('weekly'));

    expect(`${url.origin}${url.pathname}`).toBe('https://wa.me/523339643226');
    expect(url.searchParams.get('text')).toBe(
      'Hola, quiero contratar 7 días VIP por $129 MXN y pagar por SPEI.',
    );
  });

  it('builds the monthly request for the commercial number', () => {
    const url = new URL(speiWhatsAppUrl('monthly'));

    expect(url.searchParams.get('text')).toBe(
      'Hola, quiero contratar 30 días VIP por $349 MXN y pagar por SPEI.',
    );
  });

  it('rejects unsupported plans at runtime', () => {
    expect(() => speiWhatsAppUrl('annual' as SpeiPlan)).toThrow('Unsupported SPEI plan');
  });
});
