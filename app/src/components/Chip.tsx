// SPDX-License-Identifier: AGPL-3.0-or-later
import { Pressable } from 'react-native';

import { AppText } from './AppText';
import { useTheme } from '@/theme';

/** A toggle chip (checkbox semantics) for multi-select lists. */
export function Chip({ label, selected, onToggle }: { label: string; selected: boolean; onToggle: () => void }) {
  const { colors, radius, spacing, MIN_TOUCH } = useTheme();
  return (
    <Pressable
      onPress={onToggle}
      accessibilityRole="checkbox"
      accessibilityLabel={label}
      accessibilityState={{ checked: selected }}
      style={{
        minHeight: MIN_TOUCH,
        paddingHorizontal: spacing.lg,
        justifyContent: 'center',
        borderRadius: radius.lg,
        borderWidth: 1,
        borderColor: selected ? colors.primary : colors.border,
        backgroundColor: selected ? colors.primary : colors.surface,
      }}
    >
      <AppText variant="label" color={selected ? colors.onPrimary : colors.text}>
        {label}
      </AppText>
    </Pressable>
  );
}
