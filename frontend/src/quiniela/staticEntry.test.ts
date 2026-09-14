import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('quiniela static entry', () => {
  it('provides a Vite entry for the hosted /quiniela/ path', () => {
    const entry = resolve('quiniela/index.html');

    expect(existsSync(entry)).toBe(true);
    const html = readFileSync(entry, 'utf8');
    expect(html).toContain('<link rel="canonical" href="https://reytacopicks.com/quiniela/"');
    expect(html).toContain('<script type="module" src="/src/main.ts"></script>');
  });

  it('lists the public promotion route in the sitemap', () => {
    const sitemap = readFileSync(resolve('public/sitemap.xml'), 'utf8');

    expect(sitemap).toContain('<loc>https://reytacopicks.com/quiniela/</loc>');
  });
});
