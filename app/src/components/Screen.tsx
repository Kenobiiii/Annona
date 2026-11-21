// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactNode } from 'react';
import { RefreshControl, ScrollView } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/theme';

type Props = {
  children: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
};

/** A scrolling page with theme background, comfortable padding and pull-to-refresh. */
export function Screen({ children, onRefresh, refreshing = false }: Props) {
  const { colors, spacing } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.xl + insets.bottom, gap: spacing.lg }}
      keyboardShouldPersistTaps="handled"
      refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined}
    >
      {children}
    </ScrollView>
  );
}
