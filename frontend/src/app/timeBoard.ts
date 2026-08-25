import { formatEvidenceSupport } from '../domain/evidence';
import { groupDailyPicks } from '../domain/timeBlocks';
import { statusLabel, type PickStatus } from '../domain/picks';
import { escapeHtml, type PickRow } from '../services/data';

type BoardOptions = Readonly<{
  dateKey: string;
  activeBlock: number;
  isVip: boolean;
}>;

function card(row: PickRow): string {
  return `<article class="pick-card public-pick-card">
    <div class="pick-meta"><span>${escapeHtml(row.categoria)}</span><span>${escapeHtml(row.horario)} CDMX</span></div>
    <h3>${escapeHtml(row.partido)}</h3>
    <span class="selection-label">Selección del Rey</span>
    <div class="selection-row"><strong>${escapeHtml(row.pick)}</strong><b>@ ${escapeHtml(row.cuota)}</b></div>
    <div class="pick-footer"><span>${escapeHtml(formatEvidenceSupport(row.confianza))}</span>
      <span class="status status-${row.estado}">${statusLabel(row.estado as PickStatus)}</span></div>
  </article>`;
}

export function renderTimeBoard(rows: PickRow[], options: BoardOptions): string {
  const visibleRows = options.isVip ? rows : rows.filter(row => row.visibility === 'public');
  const groups = groupDailyPicks(visibleRows, options.dateKey);
  const sections = groups.map((group, index) => {
    const past = index < options.activeBlock;
    const state = group.rows.length
      ? (past ? 'Cerrado' : index === options.activeBlock ? 'En curso' : 'Próximo')
      : 'Sin selección';
    const content = group.rows.length
      ? group.rows.map(card).join('')
      : '<div class="time-block-empty"><strong>Sin selección en este periodo</strong><span>No publicamos picks solo para llenar espacio.</span></div>';
    return `<section class="time-block${index === options.activeBlock ? ' active' : ''}${past ? ' past' : ''}" aria-labelledby="time-block-${group.definition.id}">
      <header><h3 id="time-block-${group.definition.id}">${group.definition.icon} ${group.definition.label}</h3><span>${state}</span></header>
      <div class="time-block-grid">${content}</div>
    </section>`;
  }).join('');
  const cta = options.isVip ? '' : `<aside class="vip-discovery"><div><strong>👑 Más selecciones disponibles en VIP</strong><span>Consulta la cartera completa antes del inicio.</span></div><button id="inline-vip-button" type="button">Quiero acceso VIP</button></aside>`;
  return `<div class="time-board">${sections}${cta}</div>`;
}
