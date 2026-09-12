export type CheckoutMode = "payment" | "subscription";

export function checkoutParams(
  userId: string,
  email: string,
  priceId: string,
  siteUrl: string,
  mode: CheckoutMode,
) {
  if (!userId || !priceId || !siteUrl) throw new Error("Checkout configuration is incomplete");
  if (mode !== "payment" && mode !== "subscription") throw new Error("Unsupported Checkout mode");
  const baseUrl = siteUrl.replace(/\/$/, "");
  const params = {
    mode,
    customer_email: email || undefined,
    client_reference_id: userId,
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${baseUrl}/?checkout=success`,
    cancel_url: `${baseUrl}/?checkout=cancelled#vip`,
    metadata: { user_id: userId },
    allow_promotion_codes: true,
  };
  if (mode === "subscription") {
    return { ...params, subscription_data: { metadata: { user_id: userId } } };
  }
  return params;
}
