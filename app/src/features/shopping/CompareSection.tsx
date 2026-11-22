// SPDX-License-Identifier: AGPL-3.0-or-later
import { View } from 'react-native';

import type { Schemas } from '@/api/client';
import { useCompareStores } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { describeError } from '@/components/StateViews';
import { formatMoney, t } from '@/i18n';

type Comparison = Schemas['CompareOut'];

function Result({ result, onUse }: { result: Comparison; onUse: (store: string) => void }) {
  const split = result.split;
  return (
    <Card style={{ gap: 10 }}>
      <AppText variant="heading" accessibilityRole="header">
        {t('compare.title')}
      </AppText>
      {result.stores.map((s) => (
        <View key={s.store_id} style={{ gap: 2 }}>
          <AppText variant="label">{t('compare.store.total', { store: s.store_id, total: formatMoney(s.total_cents) })}</AppText>
          <AppText variant="caption" muted>
            {s.complete ? t('compare.store.complete') : t('compare.store.missing', { items: s.unavailable.join(', ') })}
          </AppText>
        </View>
      ))}
      <AppText>
        {result.best_single_store
          ? t('compare.best', { store: result.best_single_store, total: formatMoney(result.best_single_cents ?? 0) })
          : t('compare.best.none')}
      </AppText>
      {split ? (
        <View style={{ gap: 6 }}>
          <Banner>
            {t(result.best_single_store ? 'compare.split.yes' : 'compare.split.only', {
              a: split.stores[0],
              b: split.stores[1],
              saving: formatMoney(result.saving_cents),
              total: formatMoney(split.total_cents),
            })}
          </Banner>
          {split.stores.map((store) => (
            <AppText key={store} variant="caption">
              {t('compare.split.at', {
                store,
                total: formatMoney(split.totals[store]),
                items: split.assignments[store].map((l) => `${l.packs} × ${l.name}`).join(', '),
              })}
            </AppText>
          ))}
        </View>
      ) : result.best_single_store ? (
        <AppText variant="caption" muted>
          {t('compare.split.no')}
        </AppText>
      ) : null}
      {result.best_single_store ? (
        <Button variant="secondary" label={t('compare.use', { store: result.best_single_store })} onPress={() => onUse(result.best_single_store as string)} />
      ) : null}
    </Card>
  );
}

/** Compare the whole basket at every store, and see if splitting between two is worth it. */
export function CompareSection({ planId, storeIds, onUse }: { planId: number; storeIds: string[]; onUse: (store: string) => void }) {
  const compare = useCompareStores(planId);
  return (
    <View style={{ gap: 12 }}>
      <Button variant="secondary" label={t('compare.button')} onPress={() => compare.mutate(storeIds)} loading={compare.isPending} />
      {compare.isError ? <Banner kind="warning">{t('compare.error', { error: describeError(compare.error).message })}</Banner> : null}
      {compare.data ? <Result result={compare.data} onUse={onUse} /> : null}
    </View>
  );
}
