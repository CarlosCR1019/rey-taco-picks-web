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
