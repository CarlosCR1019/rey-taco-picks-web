import { describe, expect, it } from 'vitest';
import { parseReelInput } from './contracts';

describe('ReelInput', () => {
  it('accepts a bounded persisted payload', () => {
    expect(parseReelInput({
      batch_id: '11111111-1111-1111-1111-111111111111',
      portfolio_date: '2026-09-05',
      kind: 'results',
      picks: [{ partido: 'A vs B', pick: 'A', cuota: '1.80', estado: 'ganado' }],
      editorial_text: 'Resultados verificados',
      template_digest: 'f'.repeat(64),
      approved_image_refs: [],
    }).picks).toHaveLength(1);
  });

  it('rejects hidden identity and unbounded text', () => {
    expect(() => parseReelInput({ telegram_id: '1' })).toThrow('invalid reel input');
    expect(() => parseReelInput({ editorial_text: 'x'.repeat(1001) })).toThrow('invalid reel input');
  });
});
