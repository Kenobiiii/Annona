// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import type { Schemas } from '@/api/client';
import { useSearchProducts } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Chip } from '@/components/Chip';
import { Segmented } from '@/components/Segmented';
import { SwitchRow } from '@/components/SwitchRow';
import { TextField } from '@/components/TextField';
import { useDebounced } from '@/hooks/useDebounced';
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
};

function label(line: Line, choice: LineChoice): string {
  if (!choice.productId) return t('receipt.line.none');
  if (choice.changed) return t('receipt.line.sure');
  return line.preselected ? t('receipt.line.sure') : t('receipt.line.unsure');
}

function ProductSearch({ line, onPick }: { line: Line; onPick: (id: number, name: string) => void }) {
  const [text, setText] = useState('');
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
    </View>
  );
}

/** One receipt line: what it says, the suggested product and what the person decides. */
export function LineCard({ line, choice, needsAmount, onChange }: Props) {
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
          onPick={(productId, productName) => {
            onChange({ ...choice, productId, productName, apply: true, changed: productId !== line.product?.product_id });
            setSearching(false);
          }}
        />
      ) : null}
    </Card>
  );
}
