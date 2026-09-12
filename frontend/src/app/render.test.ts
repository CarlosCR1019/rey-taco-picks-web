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

  it('links the Mini App through the static-host fallback route', () => {
    renderShell();
    expect(document.querySelector('a[href="/?view=telegram"]')).not.toBeNull();
  });

  it('includes responsible-play and no-guarantee copy', () => {
    renderShell();
    expect(document.body.textContent).toContain('+18');
    expect(document.body.textContent).toContain('No garantizamos ganancias');
  });

  it('makes the audience and VIP offer clear on the first screen', () => {
    renderShell();
    const hero = document.querySelector('.hero')!;
    expect(hero.textContent).toContain('aficionados recreativos en México');
    expect(hero.querySelector<HTMLButtonElement>('#vip-primary-button')?.textContent).toBe('Suscribirme a VIP — $349 MXN/mes');
    expect(hero.querySelector('a[href="#picks"]')?.textContent).toBe('Ver picks gratis');
    expect(hero.textContent).toContain('puedes perder');
    expect(hero.textContent).toContain('Hasta 6 picks por ventana');
    expect(hero.textContent).toContain('Cancela tu membresía cuando quieras');
  });

  it('exposes monthly and seven-day VIP plans with explicit plan markers', () => {
    renderShell();
    expect(document.querySelector<HTMLButtonElement>('#vip-checkout-button')?.dataset.plan).toBe('monthly');
    expect(document.querySelector<HTMLButtonElement>('#vip-weekly-button')?.dataset.plan).toBe('weekly');
    expect(document.querySelector('.vip-section')?.textContent).toContain('$349');
    expect(document.querySelector('.vip-section')?.textContent).toContain('$129');
  });

  it('renders the Editorial Royal pricing hierarchy and both access destinations', () => {
    renderShell();
    const vip = document.querySelector('.vip-section')!;
    expect(vip.querySelector('h2')?.textContent).toBe('Elige cómo entrar a la cartera completa');
    expect(vip.querySelector('[data-plan="weekly"]')?.closest('article')?.textContent).toContain('7 días VIP');
    expect(vip.querySelector('[data-plan="weekly"]')?.closest('article')?.textContent).toContain('$129 MXN');
    expect(vip.querySelector('[data-plan="monthly"]')?.closest('article')?.textContent).toContain('VIP mensual');
    expect(vip.querySelector('[data-plan="monthly"]')?.closest('article')?.textContent).toContain('$349 MXN/mes');
    expect(vip.textContent).toContain('Ningún resultado está garantizado');
    expect(document.querySelector<HTMLAnchorElement>('#miniapp-access-link')?.getAttribute('href')).toBe('/?view=telegram');
    expect(document.querySelector('#telegram-access-link')).not.toBeNull();
    expect(document.querySelector('#telegram-access-link')?.hasAttribute('href')).toBe(false);
    expect(document.querySelector('#vip-access-link')).toBeNull();
  });

  it('starts the VIP access panel hidden and never embeds a channel invite', () => {
    renderShell();
    const panel = document.querySelector('#vip-access-panel');
    expect(panel?.className).toContain('access-panel');
    expect(panel?.className).toContain('hidden');
    expect(panel?.querySelector('a')?.getAttribute('href')).toBe('/?view=telegram');
    expect(panel?.innerHTML).not.toMatch(/t\.me\/(?![^?]*start=)/);
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
