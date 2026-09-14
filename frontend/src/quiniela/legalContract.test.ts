import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const terms = readFileSync(resolve(process.cwd(), 'public/terminos.html'), 'utf8');
const privacy = readFileSync(resolve(process.cwd(), 'public/privacidad.html'), 'utf8');
const parser = new DOMParser();
const termsDocument = parser.parseFromString(terms, 'text/html');
const privacyDocument = parser.parseFromString(privacy, 'text/html');
const rulesSection = termsDocument.querySelector(
  '#reglamento-quiniela-apertura-2026-v1',
);
const privacyHeading = [...privacyDocument.querySelectorAll('h2')].find(
  (heading) => heading.textContent?.trim() === 'Quiniela semanal',
) ?? null;
const privacySectionElements: Element[] = [];

for (
  let element: Element | null = privacyHeading;
  element && (element === privacyHeading || element.tagName !== 'H2');
  element = element.nextElementSibling
) {
  privacySectionElements.push(element);
}

const normalizedTerms = terms.replace(/\s+/g, ' ');
const normalizedRules = (rulesSection?.textContent ?? '').replace(/\s+/g, ' ');
const normalizedRulesHtml = (rulesSection?.innerHTML ?? '').replace(/\s+/g, ' ');
const normalizedPrivacySection = privacySectionElements
  .map((element) => element.textContent ?? '')
  .join(' ')
  .replace(/\s+/g, ' ');

describe('versioned quiniela legal publication', () => {
  it('publishes the exact Apertura 2026 rules version and complete participation contract', () => {
    expect(rulesSection).not.toBeNull();
    expect(normalizedRules).toContain('quiniela-apertura-2026-v1');
    expect(normalizedRules).toContain('gratuita y sin compra necesaria');
    expect(normalizedRules).toContain('mayores de 18 años');
    expect(normalizedRules).toContain('ubicadas en México');
    expect(normalizedRules).toContain('una participación completa por cuenta');
    expect(normalizedRules).toContain('no puede editarse ni reemplazarse');
    expect(normalizedRules).toContain('hora del servidor decide el cierre antes del primer partido listado');
    expect(normalizedRules).toContain('participaciones tardías, incompletas');
    expect(normalizedRules).toContain('resultados 1/X/2 no coincidan con los marcadores estimados');
    expect(normalizedRules).toContain('más resultados 1/X/2 correctos');
    expect(normalizedRules).toContain('menor suma de diferencias absolutas');
    expect(normalizedRules).toContain('hora de envío registrada por el servidor');
    expect(normalizedRules).toContain('identificador técnico e inmutable');
    expect(normalizedRules).toContain('siete días consecutivos de acceso VIP');
    expect(normalizedRules).toContain('no tiene valor en efectivo');
    expect(normalizedRules).toContain('no es transferible');
    expect(normalizedRules).toContain('ya tiene acceso activo');
    expect(normalizedRules).toContain('corregirse y volverse a calificar');
    expect(normalizedRules).toContain('reversión auditada');
    expect(normalizedRules).toContain('fraude');
    expect(normalizedRules).toContain('automatización abusiva');
    expect(normalizedRules).toContain('falla técnica material');
    expect(normalizedRules).toContain('partido abandonado');
    expect(normalizedRules).toContain('falta de una fuente confiable');
    expect(normalizedRules).toContain('cancelar esa semana');
    expect(normalizedRules).toContain('soporte@reytacopicks.com');
    expect(normalizedRulesHtml).toContain('href="/privacidad.html"');
  });

  it('preserves the current public VIP prices while adding the promotion', () => {
    expect(normalizedTerms).toContain('$129 MXN por 7 días');
    expect(normalizedTerms).toContain('$349 MXN al mes');
  });

  it('discloses contest records and aggregate-only analytics without promising public identity data', () => {
    expect(privacyHeading).not.toBeNull();
    expect(normalizedPrivacySection).toContain('Quiniela semanal');
    expect(normalizedPrivacySection).toContain('alias público');
    expect(normalizedPrivacySection).toContain('pronósticos');
    expect(normalizedPrivacySection).toContain('versión de términos aceptada');
    expect(normalizedPrivacySection).toContain('hora de envío registrada por el servidor');
    expect(normalizedPrivacySection).toContain('otorgamiento o reversión del premio VIP');
    expect(normalizedPrivacySection).toContain('correo electrónico ni el identificador interno de usuario');
    expect(normalizedPrivacySection).toContain('clave pública de la semana');
    expect(normalizedPrivacySection).toContain('solo la superficie web y la clave pública de la semana');
    expect(normalizedPrivacySection).toContain('nunca pronósticos ni identificadores personales');
  });
});
