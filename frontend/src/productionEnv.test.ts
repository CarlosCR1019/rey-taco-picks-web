import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';


function productionValues(): Record<string, string> {
  const content = readFileSync(resolve(process.cwd(), '.env.production'), 'utf8');
  return Object.fromEntries(
    content
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('#') && line.includes('='))
      .map(line => {
        const separator = line.indexOf('=');
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
}


describe('production public data configuration', () => {
  it('contains only a real Supabase URL and an anon browser key', () => {
    const values = productionValues();
    const url = values.VITE_SUPABASE_URL;
    const key = values.VITE_SUPABASE_ANON_KEY;

    expect(url).toMatch(/^https:\/\/[a-z0-9]+\.supabase\.co$/);
    expect(key).toMatch(/^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
    const payload = JSON.parse(Buffer.from(key.split('.')[1], 'base64url').toString('utf8')) as {
      role?: string;
    };
    expect(payload.role).toBe('anon');
    expect(JSON.stringify(values)).not.toContain('service_role');
    expect(JSON.stringify(values)).not.toContain('tu_clave');
  });
});
