import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.112.3";
import Stripe from "https://esm.sh/stripe@11.1.0?target=deno";
import { portalParams } from "./portal.ts";

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
    const token = (request.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const anonKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
    const stripeKey = Deno.env.get("STRIPE_SECRET_KEY") ?? "";
    if (!token || !supabaseUrl || !anonKey || !serviceKey || !stripeKey) {
      throw new Error("Server configuration is incomplete");
    }

    const authClient = createClient(supabaseUrl, anonKey, { auth: { persistSession: false } });
    const { data: authData, error: authError } = await authClient.auth.getUser(token);
    if (authError || !authData.user) return new Response("Invalid session", { status: 401, headers: corsHeaders });

    const admin = createClient(supabaseUrl, serviceKey, { auth: { persistSession: false } });
    const subscription = await admin.from("subscriptions")
      .select("provider_customer_id")
      .eq("user_id", authData.user.id)
      .eq("provider", "stripe")
      .not("provider_customer_id", "is", null)
      .order("updated_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    const customer = subscription.data?.provider_customer_id ?? "";
    if (subscription.error || !customer) return new Response("Stripe customer not found", { status: 404, headers: corsHeaders });

    const stripe = new Stripe(stripeKey, {
      apiVersion: "2022-11-15",
      httpClient: Stripe.createFetchHttpClient(),
    });
    const session = await stripe.billingPortal.sessions.create(portalParams(customer, siteUrl));
    return Response.json({ url: session.url }, { headers: corsHeaders });
  } catch (error) {
    console.error("Create portal error:", error instanceof Error ? error.message : error);
    return new Response("Unable to create portal", { status: 400, headers: corsHeaders });
  }
});
