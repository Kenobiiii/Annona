// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Schemas } from '@/api/client';
import { formatAmount, formatMoney, t } from '@/i18n';

type List = Schemas['ShoppingListOut'];

/** The list as plain text, for sharing (messages, notes). One line per item. */
export function shoppingText(list: List): string {
  const lines = [t('shopping.share.title', { store: list.store_id }), t('shopping.share.total', { total: formatMoney(list.total_cents) }), ''];
  for (const item of list.items) {
    lines.push(
      t('shopping.share.item', {
        box: item.checked ? '☑' : '☐',
        packs: item.packs,
        name: item.name,
        price: item.unit_price_cents === null ? '?' : formatMoney(item.unit_price_cents),
      }),
    );
    if (item.replaces) lines.push(t('shopping.share.replaces', { name: item.replaces }));
  }
  const unavailable = list.unavailable ?? [];
  if (unavailable.length) {
    lines.push('', t('shopping.share.unavailable'));
    for (const u of unavailable) lines.push(`- ${t('shopping.unavailable.line', { name: u.name, amount: formatAmount(u.amount, u.unit) })}`);
  }
  return lines.join('\n');
}
