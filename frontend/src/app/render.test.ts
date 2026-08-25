import { beforeEach, describe, expect, it } from 'vitest';
import { renderShell } from './render';

describe('approved application shell', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="app"></div>';
  });

  it('puts Salmo and picks before advertising', () => {
    renderShell();
    const html = document.getElementById('app')!.innerHTML;
    expect(html.indexOf('id="daily-verse-container"')).toBeLessThan(html.indexOf('id="picks-container"'));
    expect(html.indexOf('id="picks-container"')).toBeLessThan(html.indexOf('data-ad-unit'));
  });

  it('exposes four mobile navigation destinations', () => {
    renderShell();
    expect(document.querySelectorAll('.mobile-nav a')).toHaveLength(4);
  });

  it('includes responsible-play and no-guarantee copy', () => {
    renderShell();
    expect(document.body.textContent).toContain('+18');
    expect(document.body.textContent).toContain('No garantizamos ganancias');
  });

  it('links to public privacy and terms pages', () => {
    renderShell();
    expect(document.querySelector('a[href="/privacidad.html"]')).not.toBeNull();
    expect(document.querySelector('a[href="/terminos.html"]')).not.toBeNull();
  });

  it('uses the approved public portfolio and verified history headings', () => {
    renderShell();

    expect(document.getElementById('picks-title')?.textContent).toBe('La mesa está servida');
    expect(document.getElementById('history-title')?.textContent).toBe('Los picks que recibió VIP');
    expect(document.querySelector('#resultados .section-kicker')?.textContent).toContain('Resultados verificados');
  });

  it('keeps the verified table and mounts the victory wall directly below it', () => {
    renderShell();
    const html = document.getElementById('app')!.innerHTML;

    expect(html).toContain('id="victory-wall"');
    expect(html).toContain('Muro de victorias');
    expect(html).toContain('id="victory-dialog"');
    expect(html.indexOf('history-table-wrap')).toBeLessThan(html.indexOf('id="victory-wall"'));
  });
});
