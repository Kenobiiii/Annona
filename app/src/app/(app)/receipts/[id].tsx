// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';

import { ApiError } from '@/api/errors';
import type { Schemas } from '@/api/client';
import { useConfirmReceipt, useDiscardReceipt, useReceipt } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { confirmAction } from '@/components/confirm';
import { Screen } from '@/components/Screen';
import { Async, describeError } from '@/components/StateViews';
import { parseNumber } from '@/features/forms/numbers';
import { LineCard, type LineChoice, type Unit } from '@/features/receipts/LineCard';
import { formatAmount, formatDay, formatMoney, t } from '@/i18n';

type Receipt = Schemas['ReceiptOut'];

function initialChoices(receipt: Receipt): Record<number, LineChoice> {
  return Object.fromEntries(
    receipt.lines.map((line) => [
      line.id,
      {
        apply: line.preselected,
        productId: line.product?.product_id,
        productName: line.product?.name,
        amount: '',
        unit: (line.proposed_unit as Unit | null) ?? 'g',
        changed: false,
      } satisfies LineChoice,
    ]),
  );
}

function Review({ receipt }: { receipt: Receipt }) {
  const router = useRouter();
  const confirm = useConfirmReceipt(receipt.id);
  const discard = useDiscardReceipt(receipt.id);
  const initial = useMemo(() => initialChoices(receipt), [receipt]);
  const [choices, setChoices] = useState(initial);
  const [needAmount, setNeedAmount] = useState<number[]>([]);
  const [done, setDone] = useState<Schemas['AppliedOut'][] | null>(null);

  const selected = receipt.lines.filter((l) => choices[l.id]?.apply && choices[l.id]?.productId !== undefined);
  const sumText =
    receipt.total_matches === true
      ? { kind: 'info' as const, text: t('receipt.review.sum.ok', { total: formatMoney(receipt.total_cents ?? 0) }) }
      : receipt.total_matches === false
        ? {
            kind: 'warning' as const,
            text: t('receipt.review.sum.bad', { sum: formatMoney(receipt.lines_total_cents), total: formatMoney(receipt.total_cents ?? 0) }),
          }
        : { kind: 'warning' as const, text: t('receipt.review.sum.unknown') };

  async function submit() {
    const body: Schemas['DecisionIn'][] = receipt.lines.map((line) => {
      const c = choices[line.id];
      if (!(c.apply && c.productId !== undefined)) return { line_id: line.id, ignore: true };
      const amount = parseNumber(c.amount);
      return {
        line_id: line.id,
        product_id: c.productId,
        ignore: false,
        ...(amount !== null && amount > 0 ? { amount, unit: c.unit } : {}),
      };
    });
    confirm.mutate(body, {
      onSuccess: (out) => setDone(out.applied),
      onError: (error) => {
        if (error instanceof ApiError && error.code === 'amount_required') {
          setNeedAmount(Array.isArray(error.details) ? (error.details as number[]) : []);
        }
      },
    });
  }

  async function throwAway() {
    if (await confirmAction(t('receipt.discard.title'), t('receipt.discard.message'), t('receipt.discard'), t('common.cancel'))) {
      discard.mutate(undefined, { onSuccess: () => router.replace('/') });
    }
  }

  if (receipt.status !== 'pending_review' || done) {
    return (
      <View style={{ gap: 16 }}>
        {done ? (
          <>
            <AppText variant="heading">{t('receipt.done.title')}</AppText>
            <Card style={{ gap: 6 }}>
              {done.map((a) => (
                <AppText key={a.line_id}>
                  {t('receipt.done.line', {
                    name: a.name,
                    amount: formatAmount(a.amount, a.unit),
                    price: a.price_cents != null ? t('receipt.done.price', { price: formatMoney(a.price_cents) }) : '',
                  })}
                </AppText>
              ))}
            </Card>
            <Button label={t('receipt.done.pantry')} onPress={() => router.replace('/products')} />
          </>
        ) : (
          <Banner>{t(receipt.status === 'confirmed' ? 'receipt.closed.confirmed' : 'receipt.closed.discarded')}</Banner>
        )}
      </View>
    );
  }

  return (
    <View style={{ gap: 16 }}>
      <Card style={{ gap: 4 }}>
        <AppText variant="heading">
          {t('receipt.review.summary', {
            store: receipt.store_id ?? receipt.store_text ?? t('receipt.review.noStore'),
            date: receipt.purchased_on ? formatDay(receipt.purchased_on) : '—',
            total: receipt.total_cents != null ? formatMoney(receipt.total_cents) : '?',
          })}
        </AppText>
        <AppText variant="caption" muted>
          {t('receipt.review.selected', { count: selected.length, total: receipt.lines.length })}
        </AppText>
      </Card>
      <Banner kind={sumText.kind}>{sumText.text}</Banner>
      {receipt.skipped.length ? <AppText variant="caption" muted>{t('receipt.review.skipped', { lines: receipt.skipped.join(', ') })}</AppText> : null}
      <AppText variant="caption" muted>
        {t('receipt.double')}
      </AppText>
      {receipt.lines.map((line) => (
        <LineCard
          key={line.id}
          line={line}
          choice={choices[line.id]}
          needsAmount={needAmount.includes(line.id)}
          storeId={receipt.store_id}
          postalCode={receipt.postal_code}
          onChange={(next) => setChoices((cur) => ({ ...cur, [line.id]: next }))}
        />
      ))}
      {needAmount.length ? <Banner kind="warning">{t('receipt.amountRequired')}</Banner> : null}
      {confirm.isError && !needAmount.length ? <Banner kind="warning">{describeError(confirm.error).message}</Banner> : null}
      <Button
        label={selected.length ? t('receipt.confirm') : t('receipt.confirm.none')}
        onPress={() => void submit()}
        loading={confirm.isPending}
      />
      <Button variant="ghost" label={t('receipt.discard')} onPress={() => void throwAway()} loading={discard.isPending} />
    </View>
  );
}

export default function ReceiptScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const receipt = useReceipt(Number(id));
  return (
    <Screen>
      <AppText variant="title" accessibilityRole="header">
        {t('receipt.review.title')}
      </AppText>
      <Async query={receipt}>{(data) => <Review key={`${data.id}:${data.status}`} receipt={data} />}</Async>
    </Screen>
  );
}
