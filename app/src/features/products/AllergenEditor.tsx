// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import { usePatchProduct } from '@/api/hooks';
import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Chip } from '@/components/Chip';
import { ErrorState } from '@/components/StateViews';
import { SwitchRow } from '@/components/SwitchRow';
import { ALLERGENS } from '@/features/products/constants';
import { t, type MessageKey } from '@/i18n';

type Product = Schemas['Product'];

export function allergenLabel(allergen: string): string {
  return t(`allergen.${allergen}` as MessageKey);
}

/** Allergens of a product, with the ability to set them by hand (manual always wins). */
export function AllergenSection({ product }: { product: Product }) {
  const patch = usePatchProduct(product.id as number);
  const known = product.allergens !== null && product.allergens !== undefined;
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set(product.allergens ?? []));
  const [none, setNone] = useState(known && product.allergens!.length === 0);

  const toggle = (allergen: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(allergen)) next.delete(allergen);
      else next.add(allergen);
      return next;
    });

  async function save() {
    const allergens = none ? [] : ALLERGENS.filter((a) => selected.has(a));
    await patch.mutateAsync({ allergens });
    setEditing(false);
  }

  return (
    <Card>
      <AppText variant="heading">{t('product.allergens.title')}</AppText>
      {!known ? (
        <Banner kind="warning" title={t('product.allergens.unknown.title')}>
          {t('product.allergens.unknown.message')}
        </Banner>
      ) : product.allergens!.length === 0 ? (
        <AppText>{t('product.allergens.none')}</AppText>
      ) : (
        <AppText>{product.allergens!.map(allergenLabel).join(', ')}</AppText>
      )}
      {known && product.allergens_source ? (
        <AppText variant="caption" muted>
          {t('product.allergens.source', { source: t(`source.${product.allergens_source}` as MessageKey) })}
        </AppText>
      ) : null}
      <AppText variant="caption" muted>
        {t('product.allergens.check')}
      </AppText>

      {editing ? (
        <View style={{ gap: 12 }}>
          <AppText variant="label">{t('product.allergens.pick')}</AppText>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {ALLERGENS.map((a) => (
              <Chip key={a} label={allergenLabel(a)} selected={!none && selected.has(a)} onToggle={() => { setNone(false); toggle(a); }} />
            ))}
          </View>
          <SwitchRow
            label={t('product.allergens.noneOption')}
            value={none}
            onChange={(value) => {
              setNone(value);
              if (value) setSelected(new Set());
            }}
          />
          {patch.isError ? <ErrorState error={patch.error} /> : null}
          <Button label={t('product.allergens.save')} onPress={() => void save()} loading={patch.isPending} />
          <Button label={t('common.cancel')} variant="ghost" onPress={() => setEditing(false)} />
        </View>
      ) : (
        <View style={{ gap: 8 }}>
          <Button label={t('product.allergens.edit')} variant="secondary" onPress={() => setEditing(true)} />
          {product.allergens_source === 'manual' ? (
            <Button
              label={t('product.allergens.forget')}
              variant="ghost"
              onPress={() => void patch.mutateAsync({ allergens_unknown: true })}
            />
          ) : null}
        </View>
      )}
    </Card>
  );
}
