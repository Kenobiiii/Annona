// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { useProfiles, usePlan, useToday } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Async, EmptyState } from '@/components/StateViews';
import { MealDetails, needs, slotLabel, type Meal } from '@/features/meals/MealDetails';
import { MemberPicker } from '@/features/meals/MemberPicker';
import { pickNextMeal } from '@/features/today/nextMeal';
import { formatDay, localISODate, mondayOf, t } from '@/i18n';
import { useTheme } from '@/theme';

function TodayContent({ day, memberId, memberName }: { day: string; memberId?: number; memberName?: string }) {
  const router = useRouter();
  const { spacing } = useTheme();
  const meals = useToday(day, memberId);
  const plan = usePlan(mondayOf(day));
  const [open, setOpen] = useState<string | null>(null);
  const openRecipe = (slot: string) => router.push({ pathname: '/recipe', params: { day, slot } });

  return (
    <Async
      query={meals}
      isEmpty={(data) => data.length === 0}
      empty={
        plan.data === null ? (
          <EmptyState
            title={t('today.noPlan.title')}
            message={t('today.noPlan.message')}
            action={<Button label={t('today.createMenu')} onPress={() => router.push('/menu/create')} />}
          />
        ) : (
          <EmptyState title={t('today.noMeals.title')} />
        )
      }
    >
      {(data) => {
        const next = pickNextMeal<Meal>(data, new Date());
        const others = data.filter((m) => m !== next);
        return (
          <View style={{ gap: spacing.lg }}>
            {next ? (
              <View style={{ gap: spacing.sm }}>
                <AppText variant="heading">{t('today.recipe')}</AppText>
                <Card>
                  <AppText variant="caption" muted>
                    {slotLabel(next.slot)}
                    {next.needs.length ? ` · ${needs(next)}` : ''}
                  </AppText>
                  <AppText variant="heading">{next.title}</AppText>
                  <MealDetails meal={next} memberName={memberName} />
                  <Button label={t('today.openRecipe')} onPress={() => openRecipe(next.slot)} />
                </Card>
              </View>
            ) : null}
            {others.length ? (
              <View style={{ gap: spacing.sm }}>
                <AppText variant="heading">{t('today.more')}</AppText>
                {others.map((meal) => {
                  const expanded = open === meal.slot;
                  return (
                    <Card key={meal.slot}>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={t('today.showMore', { meal: `${slotLabel(meal.slot)}: ${meal.title}` })}
                        accessibilityState={{ expanded }}
                        onPress={() => setOpen(expanded ? null : meal.slot)}
                        style={{ minHeight: 48, justifyContent: 'center' }}
                      >
                        <AppText variant="caption" muted>
                          {slotLabel(meal.slot)}
                        </AppText>
                        <AppText variant="label">{meal.title}</AppText>
                      </Pressable>
                      {expanded ? <MealDetails meal={meal} memberName={memberName} /> : null}
                      {expanded ? <Button label={t('today.openRecipe')} variant="secondary" onPress={() => openRecipe(meal.slot)} /> : null}
                    </Card>
                  );
                })}
              </View>
            ) : null}
          </View>
        );
      }}
    </Async>
  );
}

export default function TodayScreen() {
  const day = localISODate();
  const profiles = useProfiles();
  const [memberId, setMemberId] = useState<number | undefined>();

  return (
    <Screen onRefresh={() => void profiles.refetch()} refreshing={profiles.isRefetching}>
      <AppText variant="title">{t('today.heading', { date: formatDay(day, 'long') })}</AppText>
      <Async query={profiles} isEmpty={(data) => data.length === 0} empty={<EmptyState title={t('error.setup_required')} message={t('error.setup_required.hint')} />}>
        {(members) => {
          const member = members.find((m) => m.profile.id === memberId) ?? members[0];
          return (
            <View style={{ gap: 16 }}>
              <MemberPicker members={members} value={member.profile.id ?? undefined} onChange={setMemberId} />
              <TodayContent day={day} memberId={member.profile.id ?? undefined} memberName={member.profile.name} />
              <View style={{ gap: 8 }}>
                <Button label={t('today.scan')} variant="secondary" disabled hint={t('today.soon.hint')} />
                <Button label={t('today.chat')} variant="secondary" disabled hint={t('today.soon.hint')} />
              </View>
            </View>
          );
        }}
      </Async>
    </Screen>
  );
}
