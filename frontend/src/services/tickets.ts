const SAFE_TICKET = /^ticket_[0-9]{1,20}[.]jpg$/;
const MAX_TICKETS = 500;

export function normalizeTicketManifest(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const entry of value) {
    if (typeof entry !== 'string' || !SAFE_TICKET.test(entry) || seen.has(entry)) continue;
    seen.add(entry);
    result.push(entry);
    if (result.length === MAX_TICKETS) break;
  }
  return result;
}

export async function loadTicketManifest(): Promise<string[]> {
  try {
    const response = await fetch('/tickets/manifest.json', { cache: 'no-store' });
    if (!response.ok) return [];
    return normalizeTicketManifest(await response.json());
  } catch {
    return [];
  }
}

export function ticketPublicUrl(filename: string): string {
  return SAFE_TICKET.test(filename) ? `/tickets/${filename}` : '';
}
