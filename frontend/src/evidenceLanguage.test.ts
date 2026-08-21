import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const mainSource = readFileSync('src/main.ts', 'utf8');
const legacyReactSource = readFileSync('src/App.jsx', 'utf8');

describe('evidence language', () => {
  it('labels the operational pick score as data support, not confidence', () => {
    expect(mainSource).toContain('Respaldo de datos:');
    expect(mainSource).not.toContain('>Confianza:');
  });

  it('keeps the legacy React consumer aligned with the same semantics', () => {
    expect(legacyReactSource).toContain('Respaldo de datos:');
    expect(legacyReactSource).not.toContain('IA Confianza:');
  });
});
