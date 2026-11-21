// SPDX-License-Identifier: AGPL-3.0-or-later
/** Colour tokens. Every text/background pair is checked for WCAG AA contrast in the tests. */

export type Palette = {
  background: string;
  surface: string;
  text: string;
  textMuted: string;
  primary: string;
  onPrimary: string;
  border: string;
  danger: string;
  onDanger: string;
  warningBg: string;
  warningText: string;
  infoBg: string;
  infoText: string;
  disabled: string;
  onDisabled: string;
};

export const palettes: Record<'light' | 'dark', Palette> = {
  light: {
    background: '#F6F4EE',
    surface: '#FFFFFF',
    text: '#1A1A17',
    textMuted: '#55554D',
    primary: '#2E6B3E',
    onPrimary: '#FFFFFF',
    border: '#8A8A80',
    danger: '#B3261E',
    onDanger: '#FFFFFF',
    warningBg: '#FFF1CC',
    warningText: '#5A4300',
    infoBg: '#E4EEF9',
    infoText: '#16406B',
    disabled: '#E3E0D6',
    onDisabled: '#5C5B54',
  },
  dark: {
    background: '#121410',
    surface: '#1C1F1A',
    text: '#ECEBE5',
    textMuted: '#B4B3A8',
    primary: '#8FD19E',
    onPrimary: '#0B2412',
    border: '#8A8F82',
    danger: '#FFB4AB',
    onDanger: '#410002',
    warningBg: '#3D3000',
    warningText: '#FFE08A',
    infoBg: '#12304F',
    infoText: '#B9D9FF',
    disabled: '#2A2D27',
    onDisabled: '#A3A298',
  },
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;
export const radius = { sm: 8, md: 12, lg: 16 } as const;
export const fontSize = { caption: 13, body: 16, label: 15, heading: 20, title: 26 } as const;
/** Smallest comfortable touch target (Material guideline: 48 dp). */
export const MIN_TOUCH = 48;
