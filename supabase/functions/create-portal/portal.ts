export function portalParams(customer: string, siteUrl: string) {
  if (!customer || !siteUrl) throw new Error("Portal configuration is incomplete");
  return {
    customer,
    return_url: siteUrl.replace(/\/$/, ""),
  };
}
