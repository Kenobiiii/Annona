// SPDX-License-Identifier: AGPL-3.0-or-later
import { ActivityIndicator, Pressable, View } from 'react-native';

import { AppText } from './AppText';
import { useTheme } from '@/theme';

type Props = {
  label: string;
  onPress?: () => void;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  disabled?: boolean;
  loading?: boolean;
  hint?: string;
  testID?: string;
};

export function Button({ label, onPress, variant = 'primary', disabled, loading, hint, testID }: Props) {
  const { colors, radius, spacing, MIN_TOUCH } = useTheme();
  const inactive = disabled || loading;
  const background = inactive
    ? colors.disabled
    : variant === 'primary'
      ? colors.primary
      : variant === 'danger'
        ? colors.danger
        : variant === 'secondary'
          ? colors.surface
          : 'transparent';
  const foreground = inactive
    ? colors.onDisabled
    : variant === 'primary'
      ? colors.onPrimary
      : variant === 'danger'
        ? colors.onDanger
        : colors.text;
  return (
    <Pressable
      testID={testID}
      onPress={inactive ? undefined : onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ disabled: !!inactive, busy: !!loading }}
      style={({ pressed }) => ({
        minHeight: MIN_TOUCH,
        paddingHorizontal: spacing.lg,
        paddingVertical: spacing.sm,
        borderRadius: radius.md,
        backgroundColor: background,
        borderWidth: variant === 'secondary' ? 1 : 0,
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        {loading ? <ActivityIndicator color={foreground} /> : null}
        <AppText variant="label" color={foreground}>
          {label}
        </AppText>
      </View>
    </Pressable>
  );
}
