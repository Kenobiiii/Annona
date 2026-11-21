// SPDX-License-Identifier: AGPL-3.0-or-later
import { View } from 'react-native';

import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { t, formatAmount, type MessageKey } from '@/i18n';
import { useTheme } from '@/theme';

export type Meal = Schemas['MealOut'];

export function slotLabel(slot: string): string {
  return t(`meal.${slot}` as MessageKey);
}

function needLabel(need: string): string {
  return t(`meal.need.${need}` as MessageKey);
}

/** Appliances a dish needs (the hob is assumed), e.g. "airfryer · microondas". */
export function needs(meal: Meal): string {
  return meal.needs.map(needLabel).join(' · ');
}

/** Steps, and the ingredients with the portion of one member. */
export function MealDetails({ meal, memberName }: { meal: Meal; memberName?: string }) {
  const { spacing } = useTheme();
  const portions = memberName ? meal.portions[memberName] : Object.values(meal.portions)[0];
  return (
    <View style={{ gap: spacing.sm }}>
      {memberName && !portions ? (
        <AppText muted>{t('meal.notForYou', { name: memberName })}</AppText>
      ) : null}
      {portions?.length ? (
        <View style={{ gap: spacing.xs }}>
          <AppText variant="label">{t('meal.ingredients', { name: memberName ?? '' }).trim()}</AppText>
          <AppText>{portions.map((p) => `${p.name} ${formatAmount(p.amount, p.unit)}`).join(' · ')}</AppText>
        </View>
      ) : null}
      {meal.steps.length ? (
        <View style={{ gap: spacing.xs }}>
          <AppText variant="label">{t('meal.steps')}</AppText>
          {meal.steps.map((step, i) => (
            <AppText key={i}>{step}</AppText>
          ))}
        </View>
      ) : null}
    </View>
  );
}
