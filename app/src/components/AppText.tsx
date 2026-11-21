// SPDX-License-Identifier: AGPL-3.0-or-later
import { Text, type TextProps } from 'react-native';

import { useTheme } from '@/theme';

type Variant = 'title' | 'heading' | 'body' | 'caption' | 'label';

type Props = TextProps & { variant?: Variant; muted?: boolean; color?: string };

/** Text that follows the theme and the system font size (scaling is capped, never disabled). */
export function AppText({ variant = 'body', muted, color, style, ...props }: Props) {
  const { colors, fontSize } = useTheme();
  const weight = variant === 'title' || variant === 'heading' || variant === 'label' ? '600' : '400';
  return (
    <Text
      maxFontSizeMultiplier={2}
      accessibilityRole={variant === 'title' || variant === 'heading' ? 'header' : undefined}
      {...props}
      style={[
        { fontSize: fontSize[variant], fontWeight: weight, color: color ?? (muted ? colors.textMuted : colors.text) },
        style,
      ]}
    />
  );
}
