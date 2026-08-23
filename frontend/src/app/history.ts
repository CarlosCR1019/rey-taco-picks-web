export function visibleHistory<T extends { estado: string }>(rows: T[]): T[] {
  const states = new Set(['ganado', 'perdido', 'pendiente', 'void', 'revision_pendiente']);
  return rows.filter(row => states.has(row.estado));
}
