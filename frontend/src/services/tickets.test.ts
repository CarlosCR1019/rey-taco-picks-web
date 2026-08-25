import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadTicketManifest, normalizeTicketManifest, ticketPublicUrl } from './tickets';

describe('ticket manifest', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('keeps unique safe filenames in source order', () => {
    expect(normalizeTicketManifest([
      'ticket_1787692765.jpg',
      'ticket_1787692765.jpg',
      '../secret.jpg',
      7,
      'ticket_1787692673.jpg',
    ])).toEqual(['ticket_1787692765.jpg', 'ticket_1787692673.jpg']);
  });

  it('returns an empty list for invalid JSON shapes', () => {
    expect(normalizeTicketManifest({ tickets: [] })).toEqual([]);
    expect(normalizeTicketManifest(null)).toEqual([]);
  });

  it('fails closed when the public manifest cannot be fetched', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    expect(await loadTicketManifest()).toEqual([]);
  });

  it('builds a public URL only for a safe manifest filename', () => {
    expect(ticketPublicUrl('ticket_1787692765.jpg')).toBe('/tickets/ticket_1787692765.jpg');
    expect(ticketPublicUrl('../secret.jpg')).toBe('');
  });
});
