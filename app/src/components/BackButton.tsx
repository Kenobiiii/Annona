// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRouter, type Href } from 'expo-router';
import { Pressable } from 'react-native';

import { AppText } from './AppText';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

/** Header "back" for detail screens that live inside the drawer. */
export function BackButton({ fallback }: { fallback: Href }) {
  const router = useRouter();
  const { colors, spacing, MIN_TOUCH } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={t('nav.back')}
      onPress={() => (router.canGoBack() ? router.back() : router.replace(fallback))}
      style={{ minHeight: MIN_TOUCH, minWidth: MIN_TOUCH, justifyContent: 'center', paddingHorizontal: spacing.md }}
    >
      <AppText color={colors.primary} variant="label">
        ‹ {t('nav.back')}
      </AppText>
    </Pressable>
  );
}
