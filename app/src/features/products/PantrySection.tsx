// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';

import { useDeletePantryItem, useSavePantryItem } from '@/api/hooks';
import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Segmented } from '@/components/Segmented';
import { ErrorState } from '@/components/StateViews';
import { TextField } from '@/components/TextField';
import { UNITS } from '@/features/products/constants';
import { parseNumber } from '@/features/forms/numbers';
import { t, type MessageKey } from '@/i18n';

type Props = { product: Schemas['Product']; item?: Schemas['PantryOut'] };

/** Add the product to the pantry, or change / remove what is there. */
export function PantrySection({ product, item }: Props) {
  const save = useSavePantryItem();
  const remove = useDeletePantryItem();
  const defaultUnit = item?.unit ?? product.nutrition?.basis ?? product.package_unit ?? 'g';
  const [amount, setAmount] = useState(item ? String(Number(item.amount)) : '');
  const [unit, setUnit] = useState<Schemas['Unit']>(defaultUnit);
  const [error, setError] = useState<string | undefined>();

  async function submit() {
    const value = parseNumber(amount);
    if (value === null) {
      setError(t('product.pantry.invalid'));
      return;
    }
    setError(undefined);
    await save.mutateAsync({
      id: item?.id ?? undefined,
      body: { product_id: product.id as number, amount: String(value), unit, expires_at: item?.expires_at ?? null },
    });
  }

  return (
    <Card>
      <AppText variant="heading">{t('product.pantry.title')}</AppText>
      <TextField
        label={t('product.pantry.amount')}
        value={amount}
        onChangeText={setAmount}
        keyboardType="decimal-pad"
        error={error}
      />
      <Segmented
        label={t('product.pantry.unit')}
        options={UNITS.map((u) => ({ value: u, label: t(`unit.${u}` as MessageKey) }))}
        value={unit}
        onChange={setUnit}
      />
      {save.isError ? <ErrorState error={save.error} /> : null}
      <Button
        label={item ? t('product.pantry.update') : t('product.pantry.add')}
        onPress={() => void submit()}
        loading={save.isPending}
      />
      {item?.id ? (
        <Button
          label={t('product.pantry.remove')}
          variant="danger"
          onPress={() => void remove.mutateAsync(item.id as number)}
          loading={remove.isPending}
        />
      ) : null}
    </Card>
  );
}
