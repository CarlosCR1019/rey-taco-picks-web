export type PickStatus = 'pendiente' | 'ganado' | 'perdido' | 'void' | 'revision_pendiente';
export type PickVisibility = 'public' | 'premium';

export function publicPick<T extends Record<string, unknown>>(pick: T) {
  if (pick.visibility !== 'premium') return { ...pick };
  const safe = { ...pick };
  delete safe.pick;
  delete safe.razonamiento;
  return safe;
}

export function statusLabel(status: PickStatus): string {
  return {
    pendiente: 'Pendiente',
    ganado: 'Ganado',
    perdido: 'Perdido',
    void: 'Nulo',
    revision_pendiente: 'En revisión',
  }[status];
}
