// SPDX-License-Identifier: AGPL-3.0-or-later
import { Pressable, View } from 'react-native';

import { useCheckShoppingItem, usePlan, useShoppingList } from '@/api/hooks';
import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Async, EmptyState } from '@/components/StateViews';
import { formatMoney, localISODate, mondayOf, t } from '@/i18n';
import { useTheme } from '@/theme';

function Row({ item, onToggle }: { item: Schemas['ShoppingItemOut']; onToggle: () => void }) {
  const { colors, spacing, MIN_TOUCH } = useTheme();
  const name = t('shopping.item', { packs: item.packs, name: item.name });
  return (
    <Pressable
      onPress={onToggle}
      accessibilityRole="checkbox"
      accessibilityLabel={name}
      accessibilityHint={t('shopping.check', { name: item.name })}
      accessibilityState={{ checked: item.checked }}
      style={{ minHeight: MIN_TOUCH, flexDirection: 'row', alignItems: 'center', gap: spacing.md }}
    >
      <AppText variant="heading" color={item.checked ? colors.primary : colors.textMuted}>
        {item.checked ? '☑' : '☐'}
      </AppText>
      <View style={{ flex: 1 }}>
        <AppText style={item.checked ? { textDecorationLine: 'line-through' } : undefined} muted={item.checked}>
          {name}
        </AppText>
        {item.unit_price_cents !== null ? (
          <AppText variant="caption" muted>
            {t('shopping.perPack', { price: formatMoney(item.unit_price_cents) })}
          </AppText>
        ) : null}
      </View>
    </Pressable>
  );
}

function List({ planId }: { planId: number }) {
  const list = useShoppingList(planId);
  const check = useCheckShoppingItem(planId);
  return (
    <Async
      query={list}
      isEmpty={(data) => data.items.length === 0}
      empty={<EmptyState title={t('shopping.empty.title')} message={t('shopping.empty.message')} />}
    >
      {(data) => {
        const done = data.items.filter((i) => i.checked).length;
        return (
          <View style={{ gap: 16 }}>
            <Card>
              <AppText variant="heading">{t('shopping.store', { store: data.store_id })}</AppText>
              <AppText>{t('shopping.total', { total: formatMoney(data.total_cents) })}</AppText>
              <AppText variant="caption" muted>
                {t('shopping.progress', { done, total: data.items.length })}
              </AppText>
            </Card>
            <Card>
              {data.items.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  onToggle={() => check.mutate({ id: item.id, checked: !item.checked })}
                />
              ))}
            </Card>
          </View>
        );
      }}
    </Async>
  );
}

export default function ShoppingScreen() {
  const week = mondayOf(localISODate());
  const plan = usePlan(week);
  return (
    <Screen onRefresh={() => void plan.refetch()} refreshing={plan.isRefetching}>
      <Async
        query={plan}
        isEmpty={(data) => !data}
        empty={<EmptyState title={t('shopping.empty.title')} message={t('shopping.empty.message')} />}
      >
        {(data) => <List planId={data!.plan.id!} />}
      </Async>
    </Screen>
  );
}
