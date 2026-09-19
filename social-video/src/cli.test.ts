import { describe, expect, it } from 'vitest';
import { REMOTION_PROCESS_TIMEOUT_MS, safeChildEnvironment } from './cli';

describe('Remotion process boundary', () => {
  it('does not pass application secrets to the child process', () => {
    const environment = safeChildEnvironment({
      PATH: 'path',
      NODE_ENV: 'test',
      SUPABASE_SERVICE_ROLE_KEY: 'secret',
      TELEGRAM_BOT_TOKEN: 'secret',
    });
    expect(environment.PATH).toBe('path');
    expect(environment.NODE_ENV).toBe('test');
    expect(environment.SUPABASE_SERVICE_ROLE_KEY).toBeUndefined();
    expect(environment.TELEGRAM_BOT_TOKEN).toBeUndefined();
  });

  it('keeps a bounded process timeout', () => {
    expect(REMOTION_PROCESS_TIMEOUT_MS).toBe(180_000);
  });
});
