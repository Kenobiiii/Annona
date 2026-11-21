// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import type { Schemas } from '@/api/client';
import { usePantry, useSearchProducts } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Segmented } from '@/components/Segmented';
import { Async, EmptyState } from '@/components/StateViews';
import { TextField } from '@/components/TextField';
import { ProductRow } from '@/features/products/ProductRow';
import { useDebounced } from '@/hooks/useDebounced';
import { formatAmount, formatDay, t, type MessageKey } from '@/i18n';
import { useTheme } from '@/theme';

type Tab = 'pantry' | 'search';
type Item = Schemas['PantryOut'];

function groupByCategory(items: Item[]): [string, Item[]][] {
  const groups = new Map<string, Item[]>();
  for (const item of items) groups.set(item.category, [...(groups.get(item.category) ?? []), item]);
  return [...groups.entries()]
    .map(([category, list]) => [category, list.sort((a, b) => a.name.localeCompare(b.name))] as [string, Item[]])
    .sort(([a], [b]) => t(`category.${a}` as MessageKey).localeCompare(t(`category.${b}` as MessageKey)));
}

function PantryList({ onSearch }: { onSearch: () => void }) {
  const router = useRouter();
  const { spacing, colors } = useTheme();
  const pantry = usePantry();
  return (
    <Async
      query={pantry}
      isEmpty={(data) => data.items.length === 0}
      empty={
        <EmptyState
          title={t('products.pantry.empty.title')}
          message={t('products.pantry.empty.message')}
          action={<Button label={t('products.pantry.goSearch')} onPress={onSearch} />}
        />
      }
    >
      {(data) => (
        <View style={{ gap: spacing.lg }}>
          {groupByCategory(data.items).map(([category, items]) => (
            <View key={category} style={{ gap: spacing.sm }}>
              <AppText variant="heading" color={colors.primary}>
                {t(`category.${category}` as MessageKey)}
              </AppText>
              {items.map((item) => (
                <Card key={item.id}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${item.name}, ${formatAmount(item.amount, item.unit)}`}
                    onPress={() => router.push(`/products/${item.product_id}`)}
                    style={{ minHeight: 48, justifyContent: 'center' }}
                  >
                    <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md }}>
                      <AppText variant="label" style={{ flex: 1 }}>
                        {item.name}
                      </AppText>
                      <AppText>{formatAmount(item.amount, item.unit)}</AppText>
                    </View>
                    {item.expires_at ? (
                      <AppText variant="caption" muted>
                        {t('products.expires', { date: formatDay(item.expires_at) })}
                      </AppText>
                    ) : null}
                  </Pressable>
                </Card>
              ))}
            </View>
          ))}
        </View>
      )}
    </Async>
  );
}

function Search() {
  const router = useRouter();
  const [text, setText] = useState('');
  const query = useDebounced(text, 300);
  const results = useSearchProducts(query);
  return (
    <View style={{ gap: 16 }}>
      <TextField
        label={t('products.search.label')}
        value={text}
        onChangeText={setText}
        placeholder={t('products.search.placeholder')}
        autoCapitalize="none"
      />
      {query.trim().length < 2 ? (
        <AppText variant="caption" muted>
          {t('products.search.hint')}
        </AppText>
      ) : (
        <Async
          query={results}
          isEmpty={(data) => data.items.length === 0}
          empty={<EmptyState title={t('products.search.empty.title')} message={t('products.search.empty.message')} />}
        >
          {(data) => (
            <View style={{ gap: 8 }}>
              {data.items.map((item) => (
                <ProductRow key={item.product.id} item={item} onPress={() => router.push(`/products/${item.product.id}`)} />
              ))}
            </View>
          )}
        </Async>
      )}
    </View>
  );
}

export default function ProductsScreen() {
  const [tab, setTab] = useState<Tab>('pantry');
  return (
    <Screen>
      <Segmented
        options={[
          { value: 'pantry', label: t('products.tab.pantry') },
          { value: 'search', label: t('products.tab.search') },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'pantry' ? <PantryList onSearch={() => setTab('search')} /> : <Search />}
    </Screen>
  );
}
