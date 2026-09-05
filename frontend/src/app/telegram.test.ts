import { afterEach, describe, expect, it, vi } from 'vitest';
import { initTelegramMiniApp, isTelegramMiniAppLocation, miniAppWindowState, publicMiniAppDto, renderTelegramMiniApp } from './telegram';

afterEach(() => {
  delete window.Telegram;
});

describe('Telegram Mini App', () => {
  it('supports both the clean route and the static-host query fallback', () => {
    expect(isTelegramMiniAppLocation(new URL('https://reytacopicks.com/telegram'), '/telegram')).toBe(true);
    expect(isTelegramMiniAppLocation(new URL('https://reytacopicks.com/?view=telegram'), '/telegram')).toBe(true);
    expect(isTelegramMiniAppLocation(new URL('https://reytacopicks.com/'), '/telegram')).toBe(false);
  });

  it('keeps four visible windows including empty ones', () => {
    const dto = publicMiniAppDto({ date: '2026-09-05', windows: [] });
    expect(dto.windows).toHaveLength(4);
    expect(dto.windows.every((window) => window.status === 'Sin selección')).toBe(true);
  });

  it('uses the same CDMX boundaries as the existing time board', () => {
    expect(miniAppWindowState('2026-09-05T17:00:00.000Z', '2026-09-05', 1)).toBe('En curso');
    expect(miniAppWindowState('2026-09-05T23:59:00.000Z', '2026-09-05', 0)).toBe('Cerrado');
  });

  it('removes premium rows from a public DTO and escapes rendered values', () => {
    const dto = publicMiniAppDto({
      date: '2026-09-05',
      windows: [{
        slot: 0,
        vip_count: 1,
        picks: [
          { visibility: 'premium', partido: 'Privado', pick: 'No mostrar', cuota: '9.9' },
          { partido: '<A vs B>', pick: '<A>', cuota: '1.8', categoria: 'Fútbol' },
        ],
      }],
    });
    expect(dto.windows[0].picks).toHaveLength(1);
    const markup = renderTelegramMiniApp(dto, '@Rey Taco Bot');
    expect(markup).toContain('&lt;A vs B&gt;');
    expect(markup).not.toContain('Privado');
    expect(markup).toContain('https://t.me/Rey%20Taco%20Bot?startapp=telegram');
  });

  it('loads the Telegram Web App SDK before reading signed initData', async () => {
    const root = document.createElement('div');
    const ready = vi.fn();
    const sdkLoader = vi.fn(async () => {
      window.Telegram = { WebApp: { initData: 'signed-init-data', ready } };
    });
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.body).toBe(JSON.stringify({ initData: 'signed-init-data' }));
      return new Response(JSON.stringify({ date: '2026-09-05', windows: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });

    const result = await initTelegramMiniApp(root, {
      endpoint: 'https://example.supabase.co/functions/v1/telegram-mini-app',
      fetchImpl: fetchImpl as typeof fetch,
      sdkLoader,
    });

    expect(sdkLoader).toHaveBeenCalledOnce();
    expect(ready).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(result?.windows).toHaveLength(4);
  });
});
