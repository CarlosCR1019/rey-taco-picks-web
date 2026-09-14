import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import { renderShell } from './render';

describe('educational and methodology content for AdSense compliance', () => {
  const publicDir = path.resolve(__dirname, '../../public');
  const aprendeDir = path.join(publicDir, 'aprende');

  const expectedGuides = [
    'momios-americanos-y-decimales.html',
    'margen-de-la-casa-overround.html',
    'apuesta-simple-frente-a-parlay.html',
    'por-que-una-racha-no-garantiza-resultados.html',
    'como-interpretar-nuestro-historial.html',
    'que-puede-y-que-no-puede-hacer-la-ia.html',
  ];

  it('verifies that all six educational guides exist with substantial editorial content', () => {
    expectedGuides.forEach((filename) => {
      const filePath = path.join(aprendeDir, filename);
      expect(fs.existsSync(filePath), `Guide ${filename} should exist`).toBe(true);

      const content = fs.readFileSync(filePath, 'utf-8');
      // Substantial text check (at least 3,000 characters per guide)
      expect(content.length).toBeGreaterThan(3000);

      // Must have canonical URL
      expect(content).toContain(`https://reytacopicks.com/aprende/${filename}`);

      // Must have Schema.org JSON-LD Article
      expect(content).toContain('"@type": "Article"');

      // Editorial ownership and maintenance must be visible, not metadata-only.
      expect(content).toContain('class="byline"');
      expect(content).toMatch(/"dateModified": "\d{4}-\d{2}-\d{2}"/);

      // Each guide must cite at least one independent, authoritative source.
      expect(content).toContain('class="sources"');
      expect(content).toMatch(
        /href="https:\/\/(?:www\.)?(?:gob\.mx|gamblingcommission\.gov\.uk|responsiblegambling\.org|nist\.gov)\//,
      );

      // Must have responsible gaming notice (+18)
      expect(content).toContain('+18');
      expect(content).toContain('responsabilidad');
    });
  });

  it('verifies that guides are truly unique and not repetitive word-substituted texts', () => {
    const titles = expectedGuides.map((filename) => {
      const content = fs.readFileSync(path.join(aprendeDir, filename), 'utf-8');
      const match = content.match(/<h1>(.*?)<\/h1>/);
      return match ? match[1] : '';
    });

    // All titles must be distinct and non-empty
    expect(new Set(titles).size).toBe(expectedGuides.length);
    titles.forEach((title) => expect(title.length).toBeGreaterThan(15));
  });

  it('verifies that the methodology page exists with required transparency sections', () => {
    const metodologiaPath = path.join(publicDir, 'metodologia.html');
    expect(fs.existsSync(metodologiaPath)).toBe(true);

    const content = fs.readFileSync(metodologiaPath, 'utf-8');
    expect(content.length).toBeGreaterThan(3500);
    expect(content).toContain('observed_at');
    expect(content).toContain('Playdoit');
    expect(content).toContain('Juego responsable');
    expect(content).toContain('Línea de la Vida');
    expect(content).toContain('CONASAMA');
    expect(content).not.toContain('CONADIC');
    expect(content).toContain('class="sources"');
    expect(content).toContain('https://www.gob.mx/conasama/');
    expect(content).toContain('"@type": "AboutPage"');
  });

  it('verifies that sitemap.xml lists all guides and methodology without empty archives', () => {
    const sitemapPath = path.join(publicDir, 'sitemap.xml');
    expect(fs.existsSync(sitemapPath)).toBe(true);

    const sitemapContent = fs.readFileSync(sitemapPath, 'utf-8');
    expectedGuides.forEach((filename) => {
      expect(sitemapContent).toContain(`https://reytacopicks.com/aprende/${filename}`);
    });
    expect(sitemapContent).toContain('https://reytacopicks.com/aprende/');
    expect(sitemapContent).toContain('https://reytacopicks.com/metodologia.html');
    expect(sitemapContent).not.toContain('https://reytacopicks.com/analisis/');
    expect(sitemapContent).not.toContain('/analisis/plantilla.html');
  });

  it('does not publish placeholder or empty analysis pages as real editorial content', () => {
    const archivePath = path.join(publicDir, 'analisis', 'index.html');
    const placeholderPath = path.join(publicDir, 'analisis', 'plantilla.html');
    expect(fs.existsSync(archivePath)).toBe(false);
    expect(fs.existsSync(placeholderPath)).toBe(false);
  });

  it('keeps advertising scripts disabled during human quality review', () => {
    const pages = [
      ...expectedGuides.map((filename) => path.join(aprendeDir, filename)),
      path.join(aprendeDir, 'index.html'),
      path.join(publicDir, 'metodologia.html'),
    ];

    pages.forEach((page) => {
      const content = fs.readFileSync(page, 'utf-8');
      expect(content).not.toContain('adsbygoogle');
      expect(content).not.toContain('googlesyndication');
    });
  });

  it('describes the deployed AI ranking boundary without unsupported performance claims', () => {
    const aiGuide = fs.readFileSync(
      path.join(aprendeDir, 'que-puede-y-que-no-puede-hacer-la-ia.html'),
      'utf-8',
    );

    expect(aiGuide).toContain('catálogo acotado');
    expect(aiGuide).toContain('Gemini y Groq');
    expect(aiGuide).toContain('identificador exacto');
    expect(aiGuide).toContain('un solo proveedor');
    expect(aiGuide).toContain('85');
    expect(aiGuide).not.toContain('únicamente coincidencias válidas');
    [
      'total frialdad',
      'abogado del diablo',
      'estadísticas históricas',
      '54% y el 58%',
      'llevará a la bancarrota',
      'sin sesgos',
    ].forEach((unsupportedClaim) => {
      expect(aiGuide).not.toContain(unsupportedClaim);
    });
  });

  it('uses the deployed audit field names and UTC storage semantics', () => {
    const methodology = fs.readFileSync(path.join(publicDir, 'metodologia.html'), 'utf-8');

    expect(methodology).toContain('<code>source_observed_at</code>');
    expect(methodology).toContain('<code>source_selection_key</code>');
    expect(methodology).toContain('almacena en UTC');
    expect(methodology).toContain('un solo proveedor');
    expect(methodology).toContain('85');
    expect(methodology).not.toContain('<code>observed_at</code>');
    expect(methodology).not.toContain('<code>outcome_key</code>');
    expect(methodology).not.toContain('únicamente coincidencias válidas');
  });

  it('describes administrative corrections without promising immutable public rows', () => {
    const methodology = fs.readFileSync(path.join(publicDir, 'metodologia.html'), 'utf-8');

    expect(methodology).toContain('correcciones administrativas');
    expect(methodology).toContain('campos de auditoría de la fuente');
    expect(methodology).not.toContain('Cero edición retroactiva');
    expect(methodology).not.toContain('Ningún pronóstico publicado es eliminado');
    expect(methodology).not.toContain('permanece inalterable');
  });

  it('labels proportional de-vig as an estimate and keeps the example arithmetic exact', () => {
    const marginGuide = fs.readFileSync(
      path.join(aprendeDir, 'margen-de-la-casa-overround.html'),
      'utf-8',
    );

    expect(marginGuide).toContain('estimación proporcional sin margen');
    expect(marginGuide).toContain('<strong>44.72%</strong>');
    expect(marginGuide).toContain('<strong>28.46%</strong>');
    expect(marginGuide).toContain('<strong>26.83%</strong>');
    expect(marginGuide).toContain('cuota de referencia sin margen');
    expect(marginGuide).not.toContain('Probabilidad Real');
    expect(marginGuide).not.toContain('cuota matemáticamente justa');
  });

  it('qualifies parlay probability examples with their mathematical assumptions', () => {
    const parlayGuide = fs.readFileSync(
      path.join(aprendeDir, 'apuesta-simple-frente-a-parlay.html'),
      'utf-8',
    );

    expect(parlayGuide).toContain('Si cada selección fuera independiente y tuviera 50%');
    expect(parlayGuide).not.toContain('tu probabilidad de ganar es apenas');
  });

  it('limits independence and regression claims to stable assumptions', () => {
    const streakGuide = fs.readFileSync(
      path.join(aprendeDir, 'por-que-una-racha-no-garantiza-resultados.html'),
      'utf-8',
    );

    expect(streakGuide).toContain('solo bajo el supuesto');
    expect(streakGuide).toContain('resultados previos pueden aportar evidencia');
    [
      'no altera en un solo ápice',
      'sigue siendo exactamente 55%',
      'El inevitable regreso',
      'la varianza dominan por completo',
      'sale a flote',
    ].forEach((overclaim) => {
      expect(streakGuide).not.toContain(overclaim);
    });
  });

  it('avoids invented sample thresholds and labels illustrative parlay math', () => {
    const historyGuide = fs.readFileSync(
      path.join(aprendeDir, 'como-interpretar-nuestro-historial.html'),
      'utf-8',
    );
    const parlayGuide = fs.readFileSync(
      path.join(aprendeDir, 'apuesta-simple-frente-a-parlay.html'),
      'utf-8',
    );

    expect(historyGuide).toContain('No existe un umbral universal');
    expect(historyGuide).toContain('señal descriptiva');
    expect(historyGuide).not.toContain('Muestra menor a 200 picks');
    expect(historyGuide).not.toContain('Muestra mayor a 500 picks');
    expect(historyGuide).not.toContain('indicador más confiable');

    expect(parlayGuide).toContain('ejemplo ilustrativo');
    expect(parlayGuide).toContain('https://www.gamblingcommission.gov.uk/');
    expect(parlayGuide).toContain('Probabilidad conjunta asumida');
    expect(parlayGuide).toContain('<td>5.00%</td>');
    expect(parlayGuide).toContain('<td>~33.66%</td>');
    expect(parlayGuide).not.toContain('<td>~5.26%</td>');
    expect(parlayGuide).not.toContain('<td>~33.80%</td>');
    expect(parlayGuide).not.toContain('Probabilidad Real (asumiendo 50% c/u)');
    expect(parlayGuide).not.toContain('propiedad matemática inapelable');
    expect(parlayGuide).not.toContain('varianza es controlable');
  });

  it('keeps library card summaries consistent with the qualified guides', () => {
    const libraryIndex = fs.readFileSync(path.join(aprendeDir, 'index.html'), 'utf-8');

    expect(libraryIndex).toContain('ejemplo ilustrativo');
    expect(libraryIndex).toContain('bajo supuestos que deben comprobarse');
    expect(libraryIndex).toContain('catálogo acotado');
    [
      'suma 106% o 110%',
      'acumulación exponencial',
      '5 aciertos seguidos no alteran',
      'filtrado de volumen masivo',
    ].forEach((overclaim) => {
      expect(libraryIndex).not.toContain(overclaim);
    });
  });

  it('verifies that desktop navigation and footer link to Aprende and Metodología', () => {
    document.body.innerHTML = '<div id="app"></div>';
    renderShell();

    const desktopNav = document.querySelector('.desktop-nav');
    expect(desktopNav).not.toBeNull();
    expect(desktopNav!.querySelector('a[href="/aprende/"]')).not.toBeNull();
    expect(desktopNav!.querySelector('a[href="/metodologia.html"]')).not.toBeNull();

    const footer = document.querySelector('.site-footer');
    expect(footer).not.toBeNull();
    expect(footer!.querySelector('a[href="/aprende/"]')).not.toBeNull();
    expect(footer!.querySelector('a[href="/metodologia.html"]')).not.toBeNull();
  });
});
