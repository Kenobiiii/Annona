// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';

import { usePantry, useProduct } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Async } from '@/components/StateViews';
import { AllergenSection } from '@/features/products/AllergenEditor';
import { NutritionCard } from '@/features/products/NutritionCard';
import { PantrySection } from '@/features/products/PantrySection';
import { priceLine } from '@/features/products/ProductRow';
import { formatAmount, t } from '@/i18n';

export default function ProductScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const productId = Number(id);
  const product = useProduct(productId);
  const pantry = usePantry();
  const inPantry = pantry.data?.items.find((item) => item.product_id === productId);

  return (
    <Screen onRefresh={() => void product.refetch()} refreshing={product.isRefetching}>
      <Async query={product}>
        {(data) => {
          const p = data.product;
          const price = priceLine(data);
          return (
            <View style={{ gap: 16 }}>
              <View style={{ gap: 4 }}>
                <AppText variant="title">{p.name}</AppText>
                {p.brand || p.store_id ? (
                  <AppText muted>{[p.brand, p.store_id].filter(Boolean).join(' · ')}</AppText>
                ) : null}
              </View>
              {price || p.package_amount ? (
                <Card>
                  {price ? (
                    <AppText>
                      {t('product.price')}: {price}
                    </AppText>
                  ) : null}
                  {p.package_amount && p.package_unit ? (
                    <AppText>
                      {t('product.package')}: {formatAmount(p.package_amount, p.package_unit)}
                    </AppText>
                  ) : null}
                </Card>
              ) : null}
              <NutritionCard nutrition={p.nutrition} />
              <AllergenSection key={`${String(p.allergens)}|${p.allergens_source}`} product={p} />
              <PantrySection key={`${inPantry?.id}|${inPantry?.amount}`} product={p} item={inPantry} />
            </View>
          );
        }}
      </Async>
    </Screen>
  );
}
