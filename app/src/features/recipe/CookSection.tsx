// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import { useCookMeal, useCookPreview } from '@/api/hooks';
import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Async, describeError } from '@/components/StateViews';
import { SwitchRow } from '@/components/SwitchRow';
import { formatAmount, t } from '@/i18n';

type Slot = Schemas['MealSlot'];
type Line = Schemas['CookLineOut'];

function noteText(line: Line): string | null {
  if (line.note === 'not_in_pantry') return t('cook.note.not_in_pantry');
  if (line.note === 'not_enough') return t('cook.note.not_enough', { have: formatAmount(line.in_pantry, line.unit) });
  if (line.note === 'unit_unknown') return t('cook.note.unit_unknown');
  return null;
}

/** Shows what would be taken from the pantry and applies it only after confirmation. */
export function CookSection({ day, slot, cooked }: { day: string; slot: Slot; cooked: boolean }) {
  const [open, setOpen] = useState(false);
  const [skipped, setSkipped] = useState<number[]>([]);
  const preview = useCookPreview(day, slot, open && !cooked);
  const cook = useCookMeal(day, slot);

  if (cooked) return <Banner>{t('cook.already')}</Banner>;
  if (cook.isSuccess) return <Banner>{t('cook.done')}</Banner>;
  if (!open) return <Button label={t('recipe.cook')} onPress={() => setOpen(true)} />;

  return (
    <Card style={{ gap: 12 }}>
      <AppText variant="heading" accessibilityRole="header">
        {t('cook.title')}
      </AppText>
      <AppText muted>{t('cook.intro')}</AppText>
      <Async query={preview}>
        {(data) => {
          const nothing = data.lines.every((l) => Number(l.deduct) === 0);
          return (
            <View style={{ gap: 12 }}>
              {data.lines.map((line) => {
                const note = noteText(line);
                return (
                  <View key={line.product_id} style={{ gap: 2 }}>
                    <SwitchRow
                      label={t('cook.skip', { name: line.name })}
                      value={skipped.includes(line.product_id)}
                      onChange={(on) =>
                        setSkipped((cur) => (on ? [...cur, line.product_id] : cur.filter((id) => id !== line.product_id)))
                      }
                    />
                    <AppText>
                      {t('cook.line', {
                        name: line.name,
                        deduct: formatAmount(line.deduct, line.unit),
                        needed: formatAmount(line.needed, line.unit),
                      })}
                    </AppText>
                    {note ? (
                      <AppText variant="caption" muted>
                        {note}
                      </AppText>
                    ) : null}
                  </View>
                );
              })}
              {nothing ? <AppText muted>{t('cook.nothing')}</AppText> : null}
              {cook.isError ? <Banner kind="warning">{describeError(cook.error).message}</Banner> : null}
              <Button label={t('cook.confirm')} onPress={() => cook.mutate(skipped)} loading={cook.isPending} />
              <Button variant="ghost" label={t('cook.cancel')} onPress={() => setOpen(false)} />
            </View>
          );
        }}
      </Async>
    </Card>
  );
}
