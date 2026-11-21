// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { usePlan, useProfiles } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Async, EmptyState } from '@/components/StateViews';
import { MealDetails, needs, slotLabel, type Meal } from '@/features/meals/MealDetails';
import { MemberPicker } from '@/features/meals/MemberPicker';
import { addDays, formatDay, localISODate, mondayOf, t } from '@/i18n';
import { useTheme } from '@/theme';

function groupByDay(meals: Meal[]): [string, Meal[]][] {
  const days = new Map<string, Meal[]>();
  for (const meal of meals) days.set(meal.day, [...(days.get(meal.day) ?? []), meal]);
  return [...days.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export default function MenuScreen() {
  const router = useRouter();
  const { spacing, colors } = useTheme();
  const params = useLocalSearchParams<{ week?: string }>();
  const [week, setWeek] = useState(() => mondayOf(params.week ?? localISODate()));
  const [open, setOpen] = useState<string | null>(null);
  const [memberId, setMemberId] = useState<number | undefined>();
  const plan = usePlan(week);
  const profiles = useProfiles();
  const members = profiles.data ?? [];
  const member = members.find((m) => m.profile.id === memberId) ?? members[0];
  const create = (regenerate: boolean) =>
    router.push({ pathname: '/menu/create', params: { week, ...(regenerate ? { regenerate: '1' } : {}) } });

  return (
    <Screen onRefresh={() => void plan.refetch()} refreshing={plan.isRefetching}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <Button label="‹" a11yLabel={t('menu.prevWeek')} variant="secondary" onPress={() => setWeek(addDays(week, -7))} />
        <AppText variant="label" style={{ flex: 1, textAlign: 'center' }}>
          {t('menu.week', { from: formatDay(week), to: formatDay(addDays(week, 6)) })}
        </AppText>
        <Button label="›" a11yLabel={t('menu.nextWeek')} variant="secondary" onPress={() => setWeek(addDays(week, 7))} />
      </View>

      <Async
        query={plan}
        isEmpty={(data) => data === null}
        empty={
          <EmptyState
            title={t('menu.empty.title')}
            message={t('menu.empty.message')}
            action={<Button label={t('menu.create')} onPress={() => create(false)} />}
          />
        }
      >
        {(data) => (
          <View style={{ gap: spacing.lg }}>
            <MemberPicker members={members} value={member?.profile.id ?? undefined} onChange={setMemberId} />
            {groupByDay(data!.meals).map(([day, meals]) => (
              <View key={day} style={{ gap: spacing.sm }}>
                <AppText variant="heading" color={colors.primary}>
                  {formatDay(day, 'long')}
                </AppText>
                {meals.map((meal) => {
                  const id = `${meal.day}-${meal.slot}`;
                  const expanded = open === id;
                  return (
                    <Card key={id}>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`${slotLabel(meal.slot)}: ${meal.title}`}
                        accessibilityState={{ expanded }}
                        onPress={() => setOpen(expanded ? null : id)}
                        style={{ minHeight: 48, justifyContent: 'center' }}
                      >
                        <AppText variant="caption" muted>
                          {slotLabel(meal.slot)}
                          {meal.needs.length ? ` · ${needs(meal)}` : ''}
                        </AppText>
                        <AppText variant="label">{meal.title}</AppText>
                      </Pressable>
                      {expanded ? <MealDetails meal={meal} memberName={member?.profile.name} /> : null}
                    </Card>
                  );
                })}
              </View>
            ))}
            <Button label={t('menu.regenerate')} variant="secondary" onPress={() => create(true)} />
          </View>
        )}
      </Async>
    </Screen>
  );
}
