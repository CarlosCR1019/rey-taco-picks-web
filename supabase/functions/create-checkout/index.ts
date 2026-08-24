import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.112.3";
import Stripe from "https://esm.sh/stripe@11.1.0?target=deno";
import { checkoutParams } from "./checkout.ts";

const siteUrl = Deno.env.get("SITE_URL") ?? "https://reytacopicks.com";
const corsHeaders = {
  "Access-Control-Allow-Origin": siteUrl,
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
};

serve(async request => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (request.headers.get("Origin") && request.headers.get("Origin") !== siteUrl) {
    return new Response("Origin not allowed", { status: 403, headers: corsHeaders });
  }

  try {
    const auth = request.headers.get("Authorization") ?? "";
    const token = auth.replace(/^Bearer\s+/i, "");
    if (!token) return new Response("Authentication required", { status: 401, headers: corsHeaders });

    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const anonKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
    const stripeKey = Deno.env.get("STRIPE_SECRET_KEY") ?? "";
    const priceId = Deno.env.get("STRIPE_PRICE_ID") ?? "";
    if (!supabaseUrl || !anonKey || !stripeKey || !priceId) throw new Error("Server configuration is incomplete");

    const supabase = createClient(supabaseUrl, anonKey, { auth: { persistSession: false } });
    const { data, error } = await supabase.auth.getUser(token);
    if (error || !data.user) return new Response("Invalid session", { status: 401, headers: corsHeaders });

    const stripe = new Stripe(stripeKey, {
      apiVersion: "2022-11-15",
      httpClient: Stripe.createFetchHttpClient(),
    });
    const session = await stripe.checkout.sessions.create(
      checkoutParams(data.user.id, data.user.email ?? "", priceId, siteUrl),
    );
    if (!session.url) throw new Error("Stripe did not return a checkout URL");
    return Response.json({ url: session.url }, { headers: corsHeaders });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Checkout error";
    console.error("Create checkout error:", message);
    return new Response("Unable to create checkout", { status: 400, headers: corsHeaders });
  }
});
