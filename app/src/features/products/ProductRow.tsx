// SPDX-License-Identifier: AGPL-3.0-or-later
import { Pressable, View } from 'react-native';

import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Card } from '@/components/Card';
import { formatMoney, t } from '@/i18n';

export function priceLine(item: Schemas['ProductOut']): string | null {
  if (item.latest_price_cents === null) return null;
  const price = formatMoney(item.latest_price_cents, item.currency ?? 'EUR');
  if (item.unit_price_cents === null || !item.unit_price_per) return price;
  const unit = formatMoney(item.unit_price_cents, item.currency ?? 'EUR');
  return t('products.price', { price, unitPrice: `${unit}/${item.unit_price_per}` });
}

export function ProductRow({ item, onPress }: { item: Schemas['ProductOut']; onPress: () => void }) {
  const { product } = item;
  const price = priceLine(item);
  return (
    <Card>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={[product.name, price].filter(Boolean).join(', ')}
        onPress={onPress}
        style={{ minHeight: 48, justifyContent: 'center' }}
      >
        <View style={{ gap: 2 }}>
          <AppText variant="label">{product.name}</AppText>
          {price || product.store_id ? (
            <AppText variant="caption" muted>
              {[product.store_id, price].filter(Boolean).join(' · ')}
            </AppText>
          ) : null}
        </View>
      </Pressable>
    </Card>
  );
}
