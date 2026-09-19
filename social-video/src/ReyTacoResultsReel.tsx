import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { ReelInput } from './contracts';

const COLORS = {
  background: '#101827',
  card: '#1c2a42',
  cream: '#fff7e8',
  accent: '#ffb347',
  muted: '#aebbd0',
};

function safeFont(text: string): React.CSSProperties {
  return {
    fontFamily: 'Arial, Helvetica, sans-serif',
    color: text,
  };
}

export const ReelFrame: React.FC<{
  input: ReelInput;
  teaser?: boolean;
}> = ({ input, teaser = false }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const introOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: 'clamp' });
  const ctaOpacity = interpolate(frame, [durationInFrames - 35, durationInFrames - 10], [0, 1], { extrapolateLeft: 'clamp' });
  const visibleIndex = teaser ? Math.min(1, Math.floor(Math.max(0, frame - 45) / 70)) : Math.floor(Math.max(0, frame - 45) / 48);
  const visiblePicks = input.picks.slice(0, Math.max(1, Math.min(input.picks.length, visibleIndex + 1)));

  return (
    <AbsoluteFill style={{ ...safeFont(COLORS.cream), backgroundColor: COLORS.background, padding: 72 }}>
      <div style={{ opacity: introOpacity, flex: 1, display: 'flex', flexDirection: 'column', gap: 28 }}>
        <div style={{ color: COLORS.accent, fontSize: 42, fontWeight: 800, letterSpacing: 2 }}>REY TACO PICKS</div>
        <div style={{ fontSize: 78, fontWeight: 900, lineHeight: 1.02 }}>
          {teaser ? 'La jugada de hoy' : 'Resultados verificados'}
        </div>
        <div style={{ color: COLORS.muted, fontSize: 30 }}>{input.editorial_text || 'Análisis deportivo, claro y responsable.'}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18, marginTop: 34 }}>
          {visiblePicks.map((pick, index) => (
            <div key={`${pick.partido}-${index}`} style={{ backgroundColor: COLORS.card, borderRadius: 24, padding: 28, opacity: interpolate(frame, [45 + index * 48, 65 + index * 48], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) }}>
              <div style={{ color: COLORS.muted, fontSize: 23 }}>{pick.partido}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, fontSize: 35, fontWeight: 800 }}>
                <span>{pick.pick}</span><span style={{ color: COLORS.accent }}>{pick.cuota}</span>
              </div>
              {pick.estado && <div style={{ color: COLORS.muted, fontSize: 22, marginTop: 8 }}>{pick.estado}</div>}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 'auto', opacity: ctaOpacity, color: COLORS.accent, fontSize: 34, fontWeight: 800 }}>reytacopicks.com</div>
        <div style={{ color: COLORS.muted, fontSize: 20 }}>18+ · Juego responsable · Sin promesas de ganancias</div>
      </div>
    </AbsoluteFill>
  );
};

export const ReyTacoResultsReel: React.FC<ReelInput> = (input) => <ReelFrame input={input} />;
