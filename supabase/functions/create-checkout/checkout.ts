export function checkoutParams(userId: string, email: string, priceId: string, siteUrl: string) {
  if (!userId || !priceId || !siteUrl) throw new Error("Checkout configuration is incomplete");
  const baseUrl = siteUrl.replace(/\/$/, "");
  return {
    mode: "subscription" as const,
    customer_email: email || undefined,
    client_reference_id: userId,
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${baseUrl}/?checkout=success`,
    cancel_url: `${baseUrl}/?checkout=cancelled#vip`,
    metadata: { user_id: userId },
    subscription_data: { metadata: { user_id: userId } },
    allow_promotion_codes: true,
  };
}
