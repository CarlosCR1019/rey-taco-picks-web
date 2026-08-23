export type ResultRow = {
  estado: string;
  cuota: number | string;
};

export type Performance = {
  wins: number;
  losses: number;
  pending: number;
  units: number;
  roi: number;
};

export function calculatePerformance(rows: ResultRow[]): Performance {
  const wins = rows.filter(row => row.estado === 'ganado').length;
  const losses = rows.filter(row => row.estado === 'perdido').length;
  const pending = rows.filter(
    row => !['ganado', 'perdido', 'void'].includes(row.estado),
  ).length;
  const units = rows.reduce((total, row) => {
    if (row.estado === 'ganado') return total + Number(row.cuota) - 1;
    if (row.estado === 'perdido') return total - 1;
    return total;
  }, 0);
  const settled = wins + losses;
  return {
    wins,
    losses,
    pending,
    units: Number(units.toFixed(2)),
    roi: settled ? Number(((units / settled) * 100).toFixed(1)) : 0,
  };
}
