import { describe, expect, it } from 'vitest';
import { visibleHistory } from './history';

describe('history', () => {
  it('keeps wins, losses, pending, void, and review rows', () => {
    const states = ['ganado', 'perdido', 'pendiente', 'void', 'revision_pendiente'];
    const rows = states.map((estado, id) => ({ id, estado }));
    expect(visibleHistory(rows).map(row => row.estado)).toEqual(states);
  });
});
