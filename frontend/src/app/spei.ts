export type SpeiPlan = 'weekly' | 'monthly';

const COMMERCIAL_WHATSAPP = '523339643226';
const REQUESTS: Record<SpeiPlan, string> = {
  weekly: 'Hola, quiero contratar 7 días VIP por $129 MXN y pagar por SPEI.',
  monthly: 'Hola, quiero contratar 30 días VIP por $349 MXN y pagar por SPEI.',
};

export function speiWhatsAppUrl(plan: SpeiPlan): string {
  const message = REQUESTS[plan];
  if (!message) throw new Error('Unsupported SPEI plan');
  return `https://wa.me/${COMMERCIAL_WHATSAPP}?text=${encodeURIComponent(message)}`;
}
