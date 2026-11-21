// SPDX-License-Identifier: AGPL-3.0-or-later
import { Pressable, View } from 'react-native';

import { AppText } from './AppText';
import { useTheme } from '@/theme';

type Option<T extends string> = { value: T; label: string };

type Props<T extends string> = {
  label?: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
};

/** A row of exclusive choices (radio group). */
export function Segmented<T extends string>({ label, options, value, onChange }: Props<T>) {
  const { colors, radius, spacing, MIN_TOUCH } = useTheme();
  return (
    <View style={{ gap: spacing.xs }}>
      {label ? <AppText variant="label">{label}</AppText> : null}
      <View accessibilityRole="radiogroup" style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              key={option.value}
              onPress={() => onChange(option.value)}
              accessibilityRole="radio"
              accessibilityLabel={option.label}
              accessibilityState={{ selected }}
              style={{
                minHeight: MIN_TOUCH,
                paddingHorizontal: spacing.lg,
                justifyContent: 'center',
                borderRadius: radius.md,
                borderWidth: 1,
                borderColor: selected ? colors.primary : colors.border,
                backgroundColor: selected ? colors.primary : colors.surface,
              }}
            >
              <AppText variant="label" color={selected ? colors.onPrimary : colors.text}>
                {option.label}
              </AppText>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
