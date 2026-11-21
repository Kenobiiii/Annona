// SPDX-License-Identifier: AGPL-3.0-or-later
import { isCleartext, normalizeServerUrl } from '@/connection/url';
import { addDays, formatAmount, formatMoney, localISODate, mondayOf } from '@/i18n/format';
import { t } from '@/i18n';
import { palettes } from '@/theme/tokens';

describe('normalizeServerUrl', () => {
  it.each([
    ['192.168.1.20:8000', 'http://192.168.1.20:8000'],
    ['  http://pc.local:8000/  ', 'http://pc.local:8000'],
    ['https://annona.example.org/api/', 'https://annona.example.org/api'],
    ['HTTP://Host:8000', 'http://host:8000'],
  ])('%s -> %s', (input, expected) => {
    expect(normalizeServerUrl(input)).toEqual({ ok: true, url: expected });
  });

  it.each([
    ['', 'empty'],
    ['   ', 'empty'],
    ['ftp://host', 'protocol'],
    ['http://', 'url'],
    ['http://exa mple.com', 'url'],
  ])('rejects %j as %s', (input, error) => {
    expect(normalizeServerUrl(input)).toEqual({ ok: false, error });
  });

  it('flags cleartext http', () => {
    expect(isCleartext('http://192.168.1.20:8000')).toBe(true);
    expect(isCleartext('https://annona.example.org')).toBe(false);
  });
});

describe('formatting', () => {
  it('formats money with the household currency', () => {
    expect(formatMoney(498, 'EUR').replace(/\s/g, ' ')).toBe('4,98 €');
    expect(formatMoney(6000)).toContain('60');
  });

  it('shows kg and l from 1000', () => {
    expect(formatAmount('1000.0', 'g')).toBe('1 kg');
    expect(formatAmount(1500, 'ml')).toBe('1,5 l');
    expect(formatAmount(250, 'g')).toBe('250 g');
    expect(formatAmount(6, 'unit')).toBe('6 ud.');
  });

  it('handles weeks on the local calendar', () => {
    expect(mondayOf('2026-11-26')).toBe('2026-11-23'); // Thursday -> Monday
    expect(mondayOf('2026-11-23')).toBe('2026-11-23');
    expect(mondayOf('2026-11-29')).toBe('2026-11-23'); // Sunday belongs to the same week
    expect(addDays('2026-11-23', 7)).toBe('2026-11-30');
    expect(addDays('2026-12-30', 3)).toBe('2027-01-02');
    expect(localISODate(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});

describe('t()', () => {
  it('replaces placeholders', () => {
    expect(t('connect.ok', { version: '1.2.3' })).toBe('Conectado: Annona 1.2.3');
  });
});

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe('theme accessibility (WCAG AA: text 4.5:1, controls 3:1)', () => {
  const pairs: [keyof typeof palettes.light, keyof typeof palettes.light][] = [
    ['text', 'background'],
    ['text', 'surface'],
    ['textMuted', 'background'],
    ['textMuted', 'surface'],
    ['onPrimary', 'primary'],
    ['onDanger', 'danger'],
    ['danger', 'background'],
    ['danger', 'surface'],
    ['primary', 'background'],
    ['primary', 'surface'],
    ['warningText', 'warningBg'],
    ['infoText', 'infoBg'],
    ['onDisabled', 'disabled'],
  ];
  for (const scheme of ['light', 'dark'] as const) {
    it.each(pairs)(`${scheme}: %s on %s`, (fg, bg) => {
      expect(contrast(palettes[scheme][fg], palettes[scheme][bg])).toBeGreaterThanOrEqual(4.5);
    });
    it(`${scheme}: borders are visible`, () => {
      expect(contrast(palettes[scheme].border, palettes[scheme].surface)).toBeGreaterThanOrEqual(3);
      expect(contrast(palettes[scheme].border, palettes[scheme].background)).toBeGreaterThanOrEqual(3);
    });
  }
});
