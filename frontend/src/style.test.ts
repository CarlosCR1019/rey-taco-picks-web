import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const styleSheet = readFileSync('src/style.css', 'utf8');

describe('responsive navigation contract', () => {
  it('shows the mobile navigation as soon as the desktop navigation hides', () => {
    const tabletBreakpoint = styleSheet.search(/@media\s*\(max-width:\s*960px\)/);
    const phoneBreakpoint = styleSheet.search(/@media\s*\(max-width:\s*700px\)/);
    const mobileNavigation = styleSheet.search(/\.mobile-nav\s*\{\s*position:\s*fixed/);

    expect(tabletBreakpoint).toBeGreaterThan(-1);
    expect(mobileNavigation).toBeGreaterThan(tabletBreakpoint);
    expect(mobileNavigation).toBeLessThan(phoneBreakpoint);
  });

  it('keeps both Salmo controls at a 44 pixel touch target', () => {
    const baseRule = styleSheet.match(/\.verse-icon-btn\s*\{([^}]*)\}/)?.[1] ?? '';

    expect(baseRule).toMatch(/width:\s*44px/);
    expect(baseRule).toMatch(/height:\s*44px/);
  });

  it('keeps the VIP discovery card branded and stacks it on phones', () => {
    const discovery = styleSheet.match(/\.vip-discovery\s*\{([^}]*)\}/)?.[1] ?? '';

    expect(discovery).toMatch(/background:\s*#0b172a/i);
    expect(discovery).toMatch(/grid-column:\s*1\s*\/\s*-1/);
    expect(styleSheet).toMatch(/@media\s*\(max-width:\s*700px\)[\s\S]*\.vip-discovery\s*\{[^}]*flex-direction:\s*column/);
  });

  it('shows every original winning ticket without cropping its evidence', () => {
    const ticketImage = styleSheet.match(/\.victory-card img\s*\{([^}]*)\}/)?.[1] ?? '';

    expect(ticketImage).toMatch(/object-fit:\s*contain/);
  });
});
