// SPDX-License-Identifier: AGPL-3.0-or-later
import { View, type ViewProps } from 'react-native';

import { useTheme } from '@/theme';

export function Card({ style, ...props }: ViewProps) {
  const { colors, radius, spacing } = useTheme();
  return (
    <View
      {...props}
      style={[
        {
          backgroundColor: colors.surface,
          borderRadius: radius.lg,
          borderWidth: 1,
          borderColor: colors.border,
          padding: spacing.lg,
          gap: spacing.sm,
        },
        style,
      ]}
    />
  );
}
