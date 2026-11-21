// SPDX-License-Identifier: AGPL-3.0-or-later
import { useColorScheme } from 'react-native';

import { fontSize, MIN_TOUCH, palettes, radius, spacing } from './tokens';

export function useTheme() {
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  return { colors: palettes[scheme], isDark: scheme === 'dark', spacing, radius, fontSize, MIN_TOUCH };
}

export type Theme = ReturnType<typeof useTheme>;
