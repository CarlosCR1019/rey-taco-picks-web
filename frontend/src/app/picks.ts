import { formatEvidenceSupport } from '../domain/evidence';
import { escapeHtml, type PickRow } from '../services/data';

export function publicCounterLabel(count: number): string {
  if (count === 0) return 'Sin selección disponible';
  if (count === 1) return '1 selección pública';
  return `${count} selecciones públicas`;
}

export function renderPublicCards(rows: PickRow[]): string {
  if (!rows.length) {
    return `
      <div class="state-card">
        <strong>No hay picks disponibles.</strong>
        <span>Vuelve más tarde; no publicamos selecciones solo para llenar espacio.</span>
      </div>`;
  }

  const cards = rows.map(row => `
    <article class="pick-card public-pick-card">
      <div class="pick-meta">
        <span>${escapeHtml(row.categoria)}</span>
        <span>${escapeHtml(row.horario)} CDMX</span>
      </div>
      <h3>${escapeHtml(row.partido)}</h3>
      <span class="selection-label">Selección del Rey</span>
      <div class="selection-row">
        <strong>${escapeHtml(row.pick)}</strong>
        <b>@ ${escapeHtml(row.cuota)}</b>
      </div>
      <div class="pick-footer">
        <span>${escapeHtml(formatEvidenceSupport(row.confianza))}</span>
        <span>Momio sujeto a cambio</span>
      </div>
    </article>`).join('');

  return `${cards}
    <aside class="vip-discovery">
      <div>
        <strong>👑 4 picks adicionales en VIP</strong>
        <span>Consulta la cartelera completa antes del inicio.</span>
      </div>
      <button id="inline-vip-button" type="button">Quiero acceso VIP</button>
    </aside>`;
}
