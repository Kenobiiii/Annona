// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { Pressable, Share, View } from 'react-native';

import type { Schemas } from '@/api/client';
import { useCatalogStores, useCheckShoppingItem, usePlan, useShoppingList } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { confirmAction } from '@/components/confirm';
import { Screen } from '@/components/Screen';
import { Segmented } from '@/components/Segmented';
import { Async, EmptyState } from '@/components/StateViews';
import { markPantryNoticeSeen, pantryNoticeSeen } from '@/features/shopping/notice';
import { shoppingText } from '@/features/shopping/text';
import { formatAmount, formatMoney, localISODate, mondayOf, t } from '@/i18n';
import { useTheme } from '@/theme';

type Item = Schemas['ShoppingItemOut'];
type Alternative = Schemas['AlternativeOut'];

function alternativeLine(a: Alternative): string {
  const extra =
    a.extra_cost_cents === 0
      ? t('shopping.alt.same')
      : `${a.extra_cost_cents > 0 ? '+' : '−'}${formatMoney(Math.abs(a.extra_cost_cents))}`;
  const kcal =
    a.kcal_diff_pct == null ? '' : t('shopping.alt.kcal', { pct: `${Number(a.kcal_diff_pct) > 0 ? '+' : ''}${Number(a.kcal_diff_pct).toLocaleString('es-ES')}` });
  return t('shopping.alt.line', { name: a.name, extra, kcal });
}

function Row({ item, onToggle }: { item: Item; onToggle: () => void }) {
  const { colors, spacing, MIN_TOUCH } = useTheme();
  const [open, setOpen] = useState(false);
  const name = t('shopping.item', { packs: item.packs, name: item.name });
  return (
    <View style={{ gap: spacing.xs }}>
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
          {item.replaces ? (
            <AppText variant="caption" muted>
              {t('shopping.replaces', { name: item.replaces })}
            </AppText>
          ) : null}
        </View>
      </Pressable>
      {(item.alternatives ?? []).length ? (
        <View style={{ paddingLeft: spacing.xl, gap: spacing.xs }}>
          <Button
            variant="ghost"
            label={open ? t('shopping.alternatives.hide') : t('shopping.alternatives')}
            onPress={() => setOpen((v) => !v)}
          />
          {open ? (item.alternatives ?? []).map((a) => <AppText key={a.product_id} variant="caption">{alternativeLine(a)}</AppText>) : null}
        </View>
      ) : null}
    </View>
  );
}

function List({ planId, defaultStore }: { planId: number; defaultStore?: string }) {
  const { spacing } = useTheme();
  const stores = useCatalogStores();
  const [store, setStore] = useState<string | undefined>(defaultStore);
  const list = useShoppingList(planId, store);
  const check = useCheckShoppingItem(planId);
  const [effect, setEffect] = useState<string | null>(null);

  async function toggle(item: Item) {
    if (!item.checked && !(await pantryNoticeSeen())) {
      const ok = await confirmAction(t('shopping.pantry.firstTitle'), t('shopping.pantry.firstMessage'), t('shopping.pantry.ok'), t('common.cancel'));
      if (!ok) return;
      await markPantryNoticeSeen();
    }
    check.mutate(
      { id: item.id, checked: !item.checked },
      {
        onSuccess: (updated) => {
          const e = updated.pantry_effect;
          setEffect(
            e ? t(e.direction === 'added' ? 'shopping.pantry.added' : 'shopping.pantry.removed', { item: `${e.name} (${formatAmount(e.amount, e.unit)})` }) : null,
          );
        },
      },
    );
  }

  const options = (stores.data ?? []).map((s) => ({ value: s.store_id, label: s.store_id }));
  return (
    <View style={{ gap: spacing.lg }}>
      {options.length > 1 ? (
        <Segmented label={t('shopping.store.choose')} options={options} value={store ?? list.data?.store_id ?? options[0].value} onChange={setStore} />
      ) : null}
      <Async
        query={list}
        isEmpty={(data) => data.items.length === 0 && (data.unavailable ?? []).length === 0}
        empty={<EmptyState title={t('shopping.empty.title')} message={t('shopping.empty.message')} />}
      >
        {(data) => {
          const done = data.items.filter((i) => i.checked).length;
          return (
            <View style={{ gap: spacing.lg }}>
              <Card>
                <AppText variant="heading">{t('shopping.store', { store: data.store_id })}</AppText>
                <AppText>{t('shopping.total', { total: formatMoney(data.total_cents) })}</AppText>
                <AppText variant="caption" muted>
                  {t('shopping.progress', { done, total: data.items.length })}
                </AppText>
              </Card>
              <AppText variant="caption" muted>
                {t('shopping.pantry.note')}
              </AppText>
              {effect ? <Banner>{effect}</Banner> : null}
              {data.items.length ? (
                <Card>
                  {data.items.map((item) => (
                    <Row key={item.id} item={item} onToggle={() => void toggle(item)} />
                  ))}
                </Card>
              ) : null}
              {(data.unavailable ?? []).length ? (
                <Banner kind="warning" title={t('shopping.unavailable.title')}>
                  {[
                    ...(data.unavailable ?? []).map((u) => t('shopping.unavailable.line', { name: u.name, amount: formatAmount(u.amount, u.unit) })),
                    t('shopping.unavailable.hint'),
                  ].join('\n')}
                </Banner>
              ) : null}
              <Button variant="secondary" label={t('shopping.share')} onPress={() => void Share.share({ message: shoppingText(data) })} />
            </View>
          );
        }}
      </Async>
    </View>
  );
}

export default function ShoppingScreen() {
  const week = mondayOf(localISODate());
  const plan = usePlan(week);
  const latest = useShoppingList(plan.data?.plan.id ?? undefined);
  return (
    <Screen onRefresh={() => void plan.refetch()} refreshing={plan.isRefetching}>
      <Async
        query={plan}
        isEmpty={(data) => !data}
        empty={<EmptyState title={t('shopping.empty.title')} message={t('shopping.empty.message')} />}
      >
        {(data) =>
          latest.isPending ? null : (
            <List key={data!.plan.id} planId={data!.plan.id!} defaultStore={latest.data?.store_id} />
          )
        }
      </Async>
    </Screen>
  );
}
