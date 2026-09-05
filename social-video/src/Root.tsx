import React from 'react';
import { Composition } from 'remotion';
import { parseReelInput, type ReelInput, type ReelKind } from './contracts';
import { ReyTacoResultsReel } from './ReyTacoResultsReel';
import { ReyTacoTeaserReel } from './ReyTacoTeaserReel';

export const REEL_COMPOSITIONS = [
  { id: 'ReyTacoResultsReel', width: 1080, height: 1920, fps: 30, durationInFrames: 300 },
  { id: 'ReyTacoTeaserReel', width: 1080, height: 1920, fps: 30, durationInFrames: 300 },
] as const;

const DEFAULT_REEL_INPUT: ReelInput = {
  batch_id: '11111111-1111-4111-8111-111111111111',
  portfolio_date: '2026-09-05',
  kind: 'results',
  picks: [{ partido: 'Rey Taco Picks', pick: 'Consulta la cartelera', cuota: '—' }],
  editorial_text: 'Resultados y selecciones de hoy',
  template_digest: 'f'.repeat(64),
  approved_image_refs: [],
};

export function reelCompositionConfig(kind: ReelKind) {
  const composition = kind === 'results' ? REEL_COMPOSITIONS[0] : REEL_COMPOSITIONS[1];
  return {
    ...composition,
    defaultProps: { ...DEFAULT_REEL_INPUT, kind },
  };
}

export function Root() {
  return (
    <>
      <Composition
        id="ReyTacoResultsReel"
        component={ReyTacoResultsReel}
        durationInFrames={REEL_COMPOSITIONS[0].durationInFrames}
        fps={REEL_COMPOSITIONS[0].fps}
        width={REEL_COMPOSITIONS[0].width}
        height={REEL_COMPOSITIONS[0].height}
        defaultProps={DEFAULT_REEL_INPUT}
        calculateMetadata={({ props }) => ({ props: parseReelInput(props) })}
      />
      <Composition
        id="ReyTacoTeaserReel"
        component={ReyTacoTeaserReel}
        durationInFrames={REEL_COMPOSITIONS[1].durationInFrames}
        fps={REEL_COMPOSITIONS[1].fps}
        width={REEL_COMPOSITIONS[1].width}
        height={REEL_COMPOSITIONS[1].height}
        defaultProps={{ ...DEFAULT_REEL_INPUT, kind: 'teaser' }}
        calculateMetadata={({ props }) => ({ props: parseReelInput(props) })}
      />
    </>
  );
}

export default Root;
