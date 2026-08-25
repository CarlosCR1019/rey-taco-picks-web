import { escapeHtml } from '../services/data';
import { ticketPublicUrl } from '../services/tickets';

export const TICKET_PAGE_SIZE = 6;

export function visibleTicketCount(current: number, total: number): number {
  return Math.min(Math.max(0, total), Math.max(TICKET_PAGE_SIZE, current + TICKET_PAGE_SIZE));
}

export function renderVictoryWall(tickets: string[], requested: number): string {
  const safeTickets = tickets
    .map(filename => ({ filename, url: ticketPublicUrl(filename) }))
    .filter(ticket => ticket.url !== '');
  if (!safeTickets.length) {
    return '<div class="victory-empty">Las evidencias fotográficas no están disponibles en este momento. Consulta el historial verificado.</div>';
  }
  const count = Math.min(safeTickets.length, Math.max(TICKET_PAGE_SIZE, requested));
  const cards = safeTickets.slice(0, count).map((ticket, index) => `
    <button class="victory-card" type="button" data-ticket-url="${escapeHtml(ticket.url)}" aria-label="Abrir boleto ganador ${index + 1}">
      <img src="${escapeHtml(ticket.url)}" alt="Boleto ganador verificado ${index + 1}" loading="lazy" decoding="async">
      <span>Ver evidencia original</span>
    </button>`).join('');
  const more = count < safeTickets.length
    ? '<button id="victory-load-more" class="secondary-button" type="button">Cargar más victorias</button>'
    : '';
  return `<div class="victory-count">${count} de ${safeTickets.length} evidencias</div><div class="victory-grid">${cards}</div>${more}`;
}
