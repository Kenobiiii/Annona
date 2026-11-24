// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import { useAddStoreProduct, useStoreConnection, useStoreSearch } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { LoadingState } from '@/components/StateViews';
import { TextField } from '@/components/TextField';
import { formatAmount, t } from '@/i18n';

import { storeErrorMessage, storeName, StoreSetup } from './StoreSetup';

type Props = {
  storeId: string;
  initialQuery: string;
  suggestedPostalCode?: string | null;
  onPicked: (productId: number, name: string) => void;
};

/** Search the store for ONE product the person bought and add the one they pick. The store is
 * asked only when the person presses search (the first search is the one they opened this for). */
export function StoreSearch({ storeId, initialQuery, suggestedPostalCode, onPicked }: Props) {
  const connection = useStoreConnection(storeId);
  const [text, setText] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);
  const ready = connection.data?.ready === true;
  const results = useStoreSearch(storeId, query, ready);
  const add = useAddStoreProduct(storeId);
  const name = storeName(storeId, connection.data?.name);

  if (connection.isPending) return <LoadingState />;
  if (!ready) return <StoreSetup storeId={storeId} suggestedPostalCode={suggestedPostalCode} />;

  const pick = async (item: { store_sku: string; name: string; product_id: number | null }) => {
    if (item.product_id != null) return onPicked(item.product_id, item.name);
    const out = await add.mutateAsync(item.store_sku);
    onPicked(out.product.id as number, out.product.name);
  };
  return (
    <View style={{ gap: 8 }}>
      <TextField label={t('store.search.field', { store: name })} value={text} onChangeText={setText} />
      <Button
        variant="secondary"
        label={t('store.search.button', { store: name })}
        disabled={text.trim().length < 2 || text.trim() === query.trim()}
        onPress={() => setQuery(text)}
      />
      {results.isFetching ? (
        <AppText variant="caption" muted>
          {t('store.search.loading', { store: name })}
        </AppText>
      ) : results.isError ? (
        <AppText variant="caption">{storeErrorMessage(results.error, name)}</AppText>
      ) : results.data && results.data.length === 0 ? (
        <AppText variant="caption" muted>
          {t('store.search.empty', { store: name })}
        </AppText>
      ) : null}
      {(results.data ?? []).map((item) => (
        <Button
          key={item.store_sku}
          variant="secondary"
          label={
            item.package_amount && item.package_unit
              ? `${item.name} · ${formatAmount(Number(item.package_amount), item.package_unit)}`
              : item.name
          }
          disabled={add.isPending}
          onPress={() => void pick(item).catch(() => undefined)}
        />
      ))}
      {add.isPending ? (
        <AppText variant="caption" muted>
          {t('store.add.loading')}
        </AppText>
      ) : add.isError ? (
        <AppText variant="caption">{storeErrorMessage(add.error, name)}</AppText>
      ) : null}
    </View>
  );
}
