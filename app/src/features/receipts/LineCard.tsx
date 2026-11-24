// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import type { Schemas } from '@/api/client';
import { useCreateProduct, useSearchProducts } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Chip } from '@/components/Chip';
import { Segmented } from '@/components/Segmented';
import { SwitchRow } from '@/components/SwitchRow';
import { TextField } from '@/components/TextField';
import { StoreSearch } from '@/features/stores/StoreSearch';
import { storeName } from '@/features/stores/StoreSetup';
import { useDebounced } from '@/hooks/useDebounced';
import { parseNumber } from '@/features/forms/numbers';
import { formatMoney, t, type MessageKey } from '@/i18n';

type Line = Schemas['ReceiptLineOut'];
export type Unit = 'g' | 'ml' | 'unit';

/** What the person decided for one line. */
export type LineChoice = {
  apply: boolean;
  productId?: number;
  productName?: string;
  amount: string;
  unit: Unit;
  changed: boolean; // another product than the suggested one
};

type Props = {
  line: Line;
  choice: LineChoice;
  needsAmount: boolean;
  onChange: (next: LineChoice) => void;
  storeId?: string | null; // the receipt's store: its products can be searched there
  postalCode?: string | null; // the shop's, if the receipt prints it
};

type StoreContext = { storeId?: string | null; postalCode?: string | null };

function label(line: Line, choice: LineChoice): string {
  if (!choice.productId) return t('receipt.line.none');
  if (choice.changed) return t('receipt.line.sure');
  return line.preselected ? t('receipt.line.sure') : t('receipt.line.unsure');
}

type Category = Schemas['Category'];
const CATEGORIES: Category[] = [
  'fruit', 'vegetables', 'grains', 'legumes', 'dairy', 'eggs', 'meat', 'fish', 'oils_fats',
  'nuts_seeds', 'bakery', 'beverages', 'condiments', 'prepared', 'other',
];

/** A readable product name from a printed line: "1 TOMATE TRITURADO" -> "Tomate triturado". */
export function nameFromReceipt(raw: string): string {
  const words = raw.replace(/^\s*\d+\s+/, '').trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Create the product a line refers to when the catalogue does not have it. Nothing is invented:
 * nutrition and allergens stay unknown until the person adds them. */
function NewProduct({ line, onCreated }: { line: Line; onCreated: (id: number, name: string) => void }) {
  const [name, setName] = useState(nameFromReceipt(line.raw_text));
  const [category, setCategory] = useState<Category>('other');
  const [pack, setPack] = useState('');
  const [packUnit, setPackUnit] = useState<Unit>('g');
  const create = useCreateProduct();
  const packAmount = parseNumber(pack);
  const valid = name.trim().length > 0 && (pack.trim() === '' || (packAmount !== null && packAmount > 0));
  const submit = async () => {
    if (!valid) return;
    const out = await create.mutateAsync({
      name: name.trim(),
      category,
      ...(packAmount !== null && packAmount > 0 ? { package_amount: packAmount, package_unit: packUnit } : {}),
    });
    onCreated(out.product.id as number, out.product.name);
  };
  return (
    <View style={{ gap: 8 }}>
      <AppText variant="caption" muted>
        {t('receipt.line.create.hint')}
      </AppText>
      <TextField label={t('receipt.line.create.name')} value={name} onChangeText={setName} />
      <AppText variant="caption" muted>
        {t('receipt.line.create.category')}
      </AppText>
      <Segmented
        value={category}
        onChange={setCategory}
        options={CATEGORIES.map((c) => ({ value: c, label: t(`category.${c}` as MessageKey) }))}
      />
      <TextField
        label={t('receipt.line.create.pack')}
        value={pack}
        onChangeText={setPack}
        keyboardType="decimal-pad"
      />
      <Segmented
        value={packUnit}
        onChange={setPackUnit}
        options={(['g', 'ml', 'unit'] as const).map((u) => ({ value: u, label: t(`receipt.line.unit.${u}` as MessageKey) }))}
      />
      {create.isError ? <AppText variant="caption">{t('receipt.line.create.failed')}</AppText> : null}
      <Button
        label={t('receipt.line.create.submit')}
        disabled={!valid || create.isPending}
        onPress={() => void submit().catch(() => undefined)}
      />
    </View>
  );
}

function ProductSearch({ line, onPick, store }: { line: Line; onPick: (id: number, name: string) => void; store: StoreContext }) {
  const [text, setText] = useState('');
  const [creating, setCreating] = useState(false);
  const [inStore, setInStore] = useState(false);
  const storeId = store.storeId;
  const results = useSearchProducts(useDebounced(text, 300));
  return (
    <View style={{ gap: 8 }}>
      {line.alternatives.length ? (
        <View style={{ gap: 4 }}>
          <AppText variant="caption" muted>
            {t('receipt.line.alternatives')}
          </AppText>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {line.alternatives.map((a) => (
              <Chip key={a.product_id} label={a.name} selected={false} onToggle={() => onPick(a.product_id, a.name)} />
            ))}
          </View>
        </View>
      ) : null}
      <TextField label={t('receipt.line.search')} value={text} onChangeText={setText} />
      {(results.data?.items ?? []).map((item) => (
        <Button
          key={item.product.id}
          variant="secondary"
          label={item.product.name}
          onPress={() => onPick(item.product.id as number, item.product.name)}
        />
      ))}
      {storeId ? (
        <Button
          variant="ghost"
          label={t(inStore ? 'receipt.line.store.hide' : 'receipt.line.store', { store: storeName(storeId) })}
          onPress={() => setInStore((v) => !v)}
        />
      ) : null}
      {storeId && inStore ? (
        <StoreSearch
          storeId={storeId}
          initialQuery={line.search_name ?? nameFromReceipt(line.raw_text)}
          suggestedPostalCode={store.postalCode}
          onPicked={onPick}
        />
      ) : null}
      <Button
        variant="ghost"
        label={creating ? t('receipt.line.create.hide') : t('receipt.line.create')}
        onPress={() => setCreating((c) => !c)}
      />
      {creating ? <NewProduct line={line} onCreated={onPick} /> : null}
    </View>
  );
}

/** One receipt line: what it says, the suggested product and what the person decides. */
export function LineCard({ line, choice, needsAmount, onChange, storeId, postalCode }: Props) {
  const [searching, setSearching] = useState(false);
  const noteKeys = (line.notes ?? []).map((n) => `receipt.line.note.${n}` as MessageKey);
  const issueKeys = (line.issues ?? []).map((n) => `receipt.line.issue.${n}` as MessageKey);
  const unknownAmount = line.proposed_amount == null || choice.changed;
  const showAmount = choice.apply && choice.productId !== undefined && (needsAmount || (unknownAmount && line.notes?.includes('unknown_pack_size')));
  const name = choice.productName ?? line.product?.name;

  return (
    <Card style={{ gap: 8 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
        <AppText variant="label" style={{ flex: 1 }}>
          {line.raw_text}
        </AppText>
        <AppText>{formatMoney(line.total_cents)}</AppText>
      </View>
      <AppText variant="caption" muted>
        {label(line, choice)}
        {name ? ` · ${choice.changed || !line.confidence ? name : t('receipt.line.matched', { name, confidence: Math.round(Number(line.confidence) * 100) })}` : ''}
      </AppText>
      <SwitchRow
        label={t('receipt.line.add')}
        value={choice.apply && choice.productId !== undefined}
        onChange={(on) => onChange({ ...choice, apply: on })}
      />
      {!choice.changed ? noteKeys.map((k) => (
        <AppText key={k} variant="caption" muted>
          {t(k)}
        </AppText>
      )) : null}
      {issueKeys.map((k) => (
        <AppText key={k} variant="caption">
          {t(k)}
        </AppText>
      ))}
      {showAmount ? (
        <View style={{ gap: 6 }}>
          <AppText variant="caption" muted>
            {t('receipt.line.amount.hint')}
          </AppText>
          <TextField
            label={t('receipt.line.amount')}
            value={choice.amount}
            onChangeText={(amount) => onChange({ ...choice, amount })}
            keyboardType="decimal-pad"
          />
          <Segmented
            value={choice.unit}
            onChange={(unit) => onChange({ ...choice, unit })}
            options={(['g', 'ml', 'unit'] as const).map((u) => ({ value: u, label: t(`receipt.line.unit.${u}` as MessageKey) }))}
          />
        </View>
      ) : null}
      <Button
        variant="ghost"
        label={searching ? t('receipt.line.changeHide') : t('receipt.line.change')}
        onPress={() => setSearching((s) => !s)}
      />
      {searching ? (
        <ProductSearch
          line={line}
          store={{ storeId, postalCode }}
          onPick={(productId, productName) => {
            onChange({ ...choice, productId, productName, apply: true, changed: productId !== line.product?.product_id });
            setSearching(false);
          }}
        />
      ) : null}
    </Card>
  );
}
