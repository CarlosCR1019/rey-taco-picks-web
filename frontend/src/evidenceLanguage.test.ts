import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { formatEvidenceSupport } from './domain/evidence';

const boardSource = readFileSync('src/app/timeBoard.ts', 'utf8');
const legacyReactSource = readFileSync('src/App.jsx', 'utf8');

describe('evidence language', () => {
  it('labels the operational pick score as data support, not confidence', () => {
    expect(boardSource).toContain('formatEvidenceSupport(row.confianza)');
    expect(formatEvidenceSupport('65% respaldo de datos')).toBe('Respaldo de datos: 65%');
    expect(boardSource).not.toContain('>Confianza:');
  });

  it('keeps the legacy React consumer aligned with the same semantics', () => {
    expect(legacyReactSource).toContain('formatEvidenceSupport(pick.confianza)');
    expect(formatEvidenceSupport('65% respaldo de datos')).toBe('Respaldo de datos: 65%');
    expect(legacyReactSource).not.toContain('IA Confianza:');
  });
});
