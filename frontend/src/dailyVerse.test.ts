import { beforeEach, describe, expect, it } from 'vitest';
import { initDailyVerseBanner } from './dailyVerse';

describe('daily Salmo', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="daily-verse-container"></div>';
    sessionStorage.clear();
  });

  it('has no dismiss action and remains visible', () => {
    initDailyVerseBanner();
    expect(document.querySelector('#btn-dismiss-verse')).toBeNull();
    expect(document.querySelector('.verse-banner')).not.toBeNull();
  });
});
