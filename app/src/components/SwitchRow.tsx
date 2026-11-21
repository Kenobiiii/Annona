// SPDX-License-Identifier: AGPL-3.0-or-later
import { Switch, View } from 'react-native';

import { AppText } from './AppText';
import { useTheme } from '@/theme';

type Props = { label: string; value: boolean; onChange: (value: boolean) => void; hint?: string };

export function SwitchRow({ label, value, onChange, hint }: Props) {
  const { colors, spacing, MIN_TOUCH } = useTheme();
  return (
    <View style={{ minHeight: MIN_TOUCH, flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
      <View style={{ flex: 1 }}>
        <AppText>{label}</AppText>
        {hint ? (
          <AppText variant="caption" muted>
            {hint}
          </AppText>
        ) : null}
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        accessibilityLabel={label}
        trackColor={{ true: colors.primary, false: colors.border }}
      />
    </View>
  );
}
