// SPDX-License-Identifier: AGPL-3.0-or-later
import type { UseQueryResult } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { AppText } from './AppText';
import { Button } from './Button';
import { ApiError } from '@/api/errors';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

export function LoadingState() {
  const { colors, spacing } = useTheme();
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityLabel={t('common.loading')}
      style={{ padding: spacing.xl, alignItems: 'center', gap: spacing.sm }}
    >
      <ActivityIndicator color={colors.primary} />
      <AppText muted>{t('common.loading')}</AppText>
    </View>
  );
}

export function EmptyState({ title, message, action }: { title: string; message?: string; action?: ReactNode }) {
  const { spacing } = useTheme();
  return (
    <View style={{ padding: spacing.xl, alignItems: 'center', gap: spacing.md }}>
      <AppText variant="heading" style={{ textAlign: 'center' }}>
        {title}
      </AppText>
      {message ? (
        <AppText muted style={{ textAlign: 'center' }}>
          {message}
        </AppText>
      ) : null}
      {action}
    </View>
  );
}

/** What went wrong, in plain words, and what to do about it. */
export function describeError(error: unknown): { message: string; hint?: string; settings: boolean } {
  if (error instanceof ApiError) {
    if (error.code === 'network') {
      return { message: t('error.network'), hint: t('error.network.hint'), settings: true };
    }
    if (error.code === 'unauthorized' || error.code === 'not_configured') {
      return { message: t('error.unauthorized'), hint: t('error.unauthorized.hint'), settings: true };
    }
    if (error.code === 'setup_required') {
      return { message: t('error.setup_required'), hint: t('error.setup_required.hint'), settings: true };
    }
    return { message: error.message || t('error.generic'), settings: false };
  }
  return { message: t('error.generic'), settings: false };
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const router = useRouter();
  const { colors, spacing } = useTheme();
  const info = describeError(error);
  return (
    <View accessibilityRole="alert" style={{ padding: spacing.xl, alignItems: 'center', gap: spacing.md }}>
      <AppText variant="heading" color={colors.danger} style={{ textAlign: 'center' }}>
        {info.message}
      </AppText>
      {info.hint ? (
        <AppText muted style={{ textAlign: 'center' }}>
          {info.hint}
        </AppText>
      ) : null}
      {onRetry ? <Button label={t('common.retry')} onPress={onRetry} variant="secondary" /> : null}
      {info.settings ? (
        <Button label={t('error.goSettings')} onPress={() => router.push('/settings')} variant="ghost" />
      ) : null}
    </View>
  );
}

type AsyncProps<T> = {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
};

/** Loading, error (with retry) and empty states for a query, then the data. */
export function Async<T>({ query, children, isEmpty, empty }: AsyncProps<T>) {
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (isEmpty?.(query.data)) return <>{empty}</>;
  return <>{children(query.data)}</>;
}

