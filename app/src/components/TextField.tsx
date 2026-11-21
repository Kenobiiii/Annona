// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { TextInput, View, type TextInputProps } from 'react-native';

import { AppText } from './AppText';
import { Button } from './Button';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

type Props = Omit<TextInputProps, 'style'> & {
  label: string;
  error?: string;
  /** Hide the text with a show/hide button (tokens, passwords). */
  secret?: boolean;
};

export function TextField({ label, error, secret, ...input }: Props) {
  const { colors, radius, spacing, MIN_TOUCH, fontSize } = useTheme();
  const [visible, setVisible] = useState(false);
  return (
    <View style={{ gap: spacing.xs }}>
      <AppText variant="label">{label}</AppText>
      <View style={{ flexDirection: 'row', gap: spacing.sm, alignItems: 'center' }}>
        <TextInput
          accessibilityLabel={label}
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          {...input}
          secureTextEntry={secret && !visible}
          style={{
            flex: 1,
            minHeight: MIN_TOUCH,
            borderWidth: 1,
            borderColor: error ? colors.danger : colors.border,
            borderRadius: radius.md,
            paddingHorizontal: spacing.md,
            color: colors.text,
            backgroundColor: colors.surface,
            fontSize: fontSize.body,
          }}
        />
        {secret ? (
          <Button
            variant="ghost"
            label={visible ? t('connect.hide') : t('connect.show')}
            onPress={() => setVisible((v) => !v)}
          />
        ) : null}
      </View>
      {error ? (
        <AppText variant="caption" color={colors.danger} accessibilityLiveRegion="polite">
          {error}
        </AppText>
      ) : null}
    </View>
  );
}
