// SPDX-License-Identifier: AGPL-3.0-or-later
import { View } from 'react-native';

import { AppText } from './AppText';
import { useTheme } from '@/theme';

type Props = { kind?: 'info' | 'warning'; title?: string; children: string };

export function Banner({ kind = 'info', title, children }: Props) {
  const { colors, radius, spacing } = useTheme();
  const background = kind === 'warning' ? colors.warningBg : colors.infoBg;
  const color = kind === 'warning' ? colors.warningText : colors.infoText;
  return (
    <View
      accessibilityRole="alert"
      style={{ backgroundColor: background, borderRadius: radius.md, padding: spacing.md, gap: spacing.xs }}
    >
      {title ? (
        <AppText variant="label" color={color}>
          {title}
        </AppText>
      ) : null}
      <AppText variant="caption" color={color}>
        {children}
      </AppText>
    </View>
  );
}
