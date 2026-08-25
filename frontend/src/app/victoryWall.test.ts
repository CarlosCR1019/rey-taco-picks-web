import { describe, expect, it } from 'vitest';
import { renderVictoryWall, visibleTicketCount } from './victoryWall';

const tickets = Array.from({ length: 14 }, (_, index) => `ticket_${1000 + index}.jpg`);

describe('victory wall', () => {
  it('renders six originals initially and offers six more', () => {
    const html = renderVictoryWall(tickets, 6);
    expect(html.match(/class="victory-card"/g)).toHaveLength(6);
    expect(html).toContain('Cargar más victorias');
    expect(html).toContain('6 de 14 evidencias');
  });

  it('caps pagination at the manifest length', () => {
    expect(visibleTicketCount(6, tickets.length)).toBe(12);
    expect(visibleTicketCount(12, tickets.length)).toBe(14);
  });

  it('uses lazy original images and safe dialog controls', () => {
    const html = renderVictoryWall(tickets, 6);
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('decoding="async"');
    expect(html).toContain('data-ticket-url="/tickets/ticket_1000.jpg"');
  });

  it('shows a neutral empty state', () => {
    expect(renderVictoryWall([], 6)).toContain('Las evidencias fotográficas no están disponibles');
  });

  it('drops unsafe filenames even when called outside the manifest loader', () => {
    const html = renderVictoryWall(['../secret.jpg', 'ticket_1000.jpg'], 6);
    expect(html).not.toContain('../secret.jpg');
    expect(html.match(/class="victory-card"/g)).toHaveLength(1);
  });
});
