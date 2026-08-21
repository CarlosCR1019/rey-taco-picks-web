import { describe, expect, it } from 'vitest';
import { telegramLinkUrl } from './account';

describe('telegramLinkUrl', () => {
  it('encodes the one-time token in a Telegram start payload', () => {
    expect(telegramLinkUrl('ReyTacoBot', 'abc 123')).toBe('https://t.me/ReyTacoBot?start=link_abc%20123');
  });

  it('rejects unsafe bot usernames', () => {
    expect(telegramLinkUrl('https://evil.example', 'token')).toBe('');
  });
});
