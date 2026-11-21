// SPDX-License-Identifier: AGPL-3.0-or-later
import { View } from 'react-native';

import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Card } from '@/components/Card';
import { LOCALE, t, type MessageKey } from '@/i18n';

const number = (value: string) =>
  new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 }).format(Number(value));

const APPROXIMATE = new Set(['sample', 'llm_estimate']);

export function NutritionCard({ nutrition }: { nutrition: Schemas['NutritionFacts'] | null | undefined }) {
  if (!nutrition) {
    return (
      <Card>
        <AppText muted>{t('product.nutrition.none')}</AppText>
      </Card>
    );
  }
  const source = t(`source.${nutrition.source}` as MessageKey);
  const rows: [MessageKey, string, string][] = [
    ['product.nutrition.kcal', number(nutrition.energy_kcal), 'kcal'],
    ['product.nutrition.protein', number(nutrition.protein_g), 'g'],
    ['product.nutrition.fat', number(nutrition.fat_g), 'g'],
    ['product.nutrition.carbs', number(nutrition.carbohydrates_g), 'g'],
  ];
  return (
    <Card>
      <AppText variant="heading">{t('product.nutrition.title', { unit: nutrition.basis === 'ml' ? 'ml' : 'g' })}</AppText>
      {rows.map(([label, value, unit]) => (
        <View key={label} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          <AppText>{t(label)}</AppText>
          <AppText variant="label">{`${value} ${unit}`}</AppText>
        </View>
      ))}
      {APPROXIMATE.has(nutrition.source) ? (
        <Banner kind="warning">{t('product.nutrition.estimated', { source })}</Banner>
      ) : (
        <AppText variant="caption" muted>
          {t('product.nutrition.source', { source })}
        </AppText>
      )}
    </Card>
  );
}
