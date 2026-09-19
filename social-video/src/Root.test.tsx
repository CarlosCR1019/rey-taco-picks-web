import { describe, expect, it } from 'vitest';
import { REEL_COMPOSITIONS, reelCompositionConfig } from './Root';

describe('Rey Taco reel compositions', () => {
  it('registers two vertical, bounded compositions', () => {
    expect(REEL_COMPOSITIONS.map((item) => item.id)).toEqual([
      'ReyTacoResultsReel',
      'ReyTacoTeaserReel',
    ]);
    for (const item of REEL_COMPOSITIONS) {
      expect(item.width).toBe(1080);
      expect(item.height).toBe(1920);
      expect(item.fps).toBe(30);
      expect(item.durationInFrames).toBeGreaterThanOrEqual(240);
      expect(item.durationInFrames).toBeLessThanOrEqual(450);
    }
  });

  it('exposes a local render-safe config without network dependencies', () => {
    expect(reelCompositionConfig('results').defaultProps.kind).toBe('results');
    expect(reelCompositionConfig('teaser').defaultProps.kind).toBe('teaser');
  });
});
