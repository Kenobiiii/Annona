// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';

import { ApiError } from '@/api/errors';
import type { Schemas } from '@/api/client';
import { useRecipe, useRegenerateRecipe } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { ErrorState, LoadingState } from '@/components/StateViews';
import { CookSection } from '@/features/recipe/CookSection';
import { StepList } from '@/features/recipe/StepList';
import { formatAmount, t } from '@/i18n';
import { useTheme } from '@/theme';

const SLOTS: Schemas['MealSlot'][] = ['breakfast', 'lunch', 'snack', 'dinner'];

function Failure({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { spacing } = useTheme();
  if (error instanceof ApiError && error.code === 'recipe_rejected') {
    return (
      <View style={{ gap: spacing.md }}>
        <Banner kind="warning" title={t('recipe.rejected')}>
          {t('recipe.rejected.hint')}
        </Banner>
        <Button label={t('create.retry')} onPress={onRetry} />
      </View>
    );
  }
  if (error instanceof ApiError && error.code === 'not_found') {
    return <Banner kind="warning">{t('recipe.notPlanned')}</Banner>;
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}

export default function RecipeScreen() {
  const params = useLocalSearchParams<{ day: string; slot: string }>();
  const day = String(params.day);
  const slot = (SLOTS.includes(params.slot as Schemas['MealSlot']) ? params.slot : 'lunch') as Schemas['MealSlot'];
  const recipe = useRecipe(day, slot);
  const another = useRegenerateRecipe(day, slot);
  const { spacing } = useTheme();

  return (
    <Screen>
      {recipe.isPending || another.isPending ? (
        <View style={{ gap: spacing.md }}>
          <LoadingState />
          <AppText variant="heading" style={{ textAlign: 'center' }}>
            {t('recipe.loading')}
          </AppText>
          <AppText muted style={{ textAlign: 'center' }}>
            {t('recipe.loading.hint')}
          </AppText>
        </View>
      ) : recipe.isError ? (
        <Failure error={recipe.error} onRetry={() => void recipe.refetch()} />
      ) : (
        (() => {
          const data = recipe.data;
          return (
            <View style={{ gap: spacing.lg }}>
              <View style={{ gap: 4 }}>
                <AppText variant="title">{data.title}</AppText>
                <AppText muted>{t('recipe.eaters', { names: data.eaters.map((e) => e.name).join(', ') })}</AppText>
              </View>
              {another.isError ? <Failure error={another.error} onRetry={() => another.mutate()} /> : null}
              <Card style={{ gap: 6 }}>
                <AppText variant="label">{t('recipe.ingredients')}</AppText>
                {data.ingredients.map((i) => (
                  <AppText key={i.product_id}>
                    {i.name}: {formatAmount(i.amount, i.unit)}
                  </AppText>
                ))}
                {Object.entries(data.portions).length > 1
                  ? Object.entries(data.portions).map(([name, items]) => (
                      <AppText key={name} variant="caption" muted>
                        {t('recipe.portion', { name })}: {items.map((i) => `${i.name} ${formatAmount(i.amount, i.unit)}`).join(' · ')}
                      </AppText>
                    ))
                  : null}
              </Card>
              <View style={{ gap: spacing.sm }}>
                <AppText variant="heading" accessibilityRole="header">
                  {t('recipe.steps')}
                </AppText>
                <StepList steps={data.steps} />
                {data.total_minutes > 0 ? <AppText muted>{t('recipe.total', { minutes: data.total_minutes })}</AppText> : null}
              </View>
              {!data.calibrated ? <Banner>{t('recipe.calibrate')}</Banner> : null}
              <CookSection key={String(data.cooked_at)} day={day} slot={slot} cooked={data.cooked_at != null} />
              <Button variant="ghost" label={t('recipe.another')} onPress={() => another.mutate()} disabled={data.cooked_at != null} />
            </View>
          );
        })()
      )}
    </Screen>
  );
}
