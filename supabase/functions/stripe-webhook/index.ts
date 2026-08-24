import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.7.1";
import Stripe from "https://esm.sh/stripe@11.1.0?target=deno";
import { shouldPersistSubscription, subscriptionPatch } from "./subscription.ts";


const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") ?? "", {
  apiVersion: "2022-11-15",
  httpClient: Stripe.createFetchHttpClient(),
});
const cryptoProvider = Stripe.createSubtleCryptoProvider();

const supportedEvents = new Set([
  "checkout.session.completed",
  "invoice.paid",
  "invoice.payment_failed",
  "customer.subscription.updated",
  "customer.subscription.deleted",
]);


serve(async (req) => {
  const signature = req.headers.get("Stripe-Signature");
  if (!signature) return new Response("No signature provided", { status: 400 });

  try {
    const body = await req.text();
    const event = await stripe.webhooks.constructEventAsync(
      body,
      signature,
      Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "",
      undefined,
      cryptoProvider,
    );

    if (!supportedEvents.has(event.type)) {
      return Response.json({ received: true, ignored: event.type });
    }

    const object = event.data.object as unknown as Record<string, unknown>;
    if (!shouldPersistSubscription(event.type)) {
      return Response.json({ received: true, pending_payment: true });
    }
    let subscriptionObject = object;
    const subscriptionId = String(object.subscription ?? (
      event.type.startsWith("customer.subscription.") ? object.id : ""
    ));

    if (subscriptionId && event.type !== "checkout.session.completed") {
      const subscription = await stripe.subscriptions.retrieve(subscriptionId);
      subscriptionObject = {
        ...object,
        ...subscription,
        customer: subscription.customer,
        subscription: subscription.id,
      } as unknown as Record<string, unknown>;
    }

    const metadata = (subscriptionObject.metadata ?? object.metadata ?? {}) as Record<string, string>;
    const userId = String(metadata.user_id ?? object.client_reference_id ?? "");
    if (!userId) throw new Error("Stripe subscription is missing metadata.user_id");

    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
    if (!supabaseUrl || !serviceKey) throw new Error("Supabase service configuration is missing");

    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false },
    });
    const patch = subscriptionPatch(event.type, subscriptionObject);
    if (!patch.provider_subscription_id) {
      throw new Error("Stripe event is missing a subscription id");
    }

    const { data: applied, error } = await supabase.rpc("apply_stripe_subscription_event", {
      p_event_id: event.id,
      p_event_created: event.created,
      p_user_id: userId,
      p_customer_id: patch.provider_customer_id,
      p_subscription_id: patch.provider_subscription_id,
      p_status: patch.status,
      p_current_period_end: patch.current_period_end,
    });
    if (error) throw error;

    return Response.json({ received: true, applied: applied === true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Webhook error";
    console.error("Stripe webhook error:", message);
    return new Response(message, { status: 400 });
  }
});
