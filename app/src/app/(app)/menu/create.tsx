// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Switch, View } from 'react-native';

import { useCatalogStores, useGeneratePlan, useJob } from '@/api/hooks';
import { ApiError } from '@/api/errors';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Screen } from '@/components/Screen';
import { Segmented } from '@/components/Segmented';
import { Async, EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { buildPlanRequest, fullGrid, plannedMeals, type Grid } from '@/features/menu/schedule';
import { SLOTS } from '@/features/today/nextMeal';
import { addDays, formatDay, formatMoney, localISODate, mondayOf, t, type MessageKey } from '@/i18n';
import { useTheme } from '@/theme';

type Variety = 'basic' | 'balanced' | 'high';

type JobResult = {
  accepted?: boolean;
  shopping_status?: string;
  issues?: string[];
  issue_codes?: string[];
  shortfalls?: { constraint: string; amount: string; unit: string; detail: string }[];
  extra_purchases?: { name: string; packs: number }[];
};

const ISSUE_KEYS: Record<string, MessageKey> = {
  portions_unrealistic: 'create.issue.portions_unrealistic',
  protein_low: 'create.issue.protein_low',
  servings_missing: 'create.issue.servings_missing',
  stock_exceeded: 'create.issue.stock_exceeded',
  appliance: 'create.issue.appliance',
  not_allowed: 'create.issue.not_allowed',
};

/** What went wrong, in Spanish: one line per kind of problem (the raw messages are for the AI). */
function issueLines(result: JobResult): string[] {
  const codes = result.issue_codes ?? [];
  if (codes.length === 0) return [];
  return codes.map((code) => `• ${t(ISSUE_KEYS[code] ?? 'create.issue.other')}`);
}

function Outcome({ jobId, week, onRetry }: { jobId: string; week: string; onRetry: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const job = useJob(jobId);
  const { spacing } = useTheme();

  if (job.isError) return <ErrorState error={job.error} onRetry={() => void job.refetch()} />;
  const data = job.data;
  if (!data || data.status === 'queued' || data.status === 'running') {
    return (
      <View style={{ gap: spacing.md }}>
        <LoadingState />
        <AppText variant="heading" style={{ textAlign: 'center' }}>
          {t('create.generating')}
        </AppText>
        <AppText muted style={{ textAlign: 'center' }}>
          {t('create.generating.hint')}
        </AppText>
      </View>
    );
  }
  if (data.status === 'failed') {
    return (
      <View style={{ gap: spacing.md }}>
        <Banner kind="warning" title={t('create.failed')}>
          {data.error ?? ''}
        </Banner>
        <Button label={t('create.retry')} onPress={onRetry} />
      </View>
    );
  }

  const result = (data.result ?? {}) as JobResult;
  if (result.shopping_status && result.shopping_status !== 'optimal') {
    return (
      <View style={{ gap: spacing.md }}>
        <Banner kind="warning" title={t('create.infeasible')}>
          {(result.shortfalls ?? [])
            .map((s) =>
              s.constraint === 'budget' && s.unit === 'cents'
                ? t('create.shortfall.budget', { amount: formatMoney(Number(s.amount)) })
                : t('create.shortfall.other', { detail: s.detail, amount: s.amount, unit: s.unit }),
            )
            .concat(t('create.infeasible.hint'))
            .join('\n')}
        </Banner>
        <Button label={t('create.retry')} onPress={onRetry} />
      </View>
    );
  }
  if (result.accepted === false) {
    return (
      <View style={{ gap: spacing.md }}>
        <Banner kind="warning" title={t('create.rejected')}>
          {[t('create.rejected.hint'), ...issueLines(result)].join('\n')}
        </Banner>
        <Button label={t('create.retry')} onPress={onRetry} />
      </View>
    );
  }
  const extras = result.extra_purchases ?? [];
  return (
    <View style={{ gap: spacing.md }}>
      <AppText variant="heading">{t('create.done')}</AppText>
      {extras.length ? (
        <Banner>{t('create.extra', { items: extras.map((e) => `${e.packs} × ${e.name}`).join(', ') })}</Banner>
      ) : null}
      <Button
        label={t('create.view')}
        onPress={async () => {
          await queryClient.invalidateQueries();
          router.replace({ pathname: '/menu', params: { week } });
        }}
      />
    </View>
  );
}

export default function CreateMenuScreen() {
  const params = useLocalSearchParams<{ week?: string; regenerate?: string }>();
  const week = mondayOf(params.week ?? localISODate());
  const { colors, spacing, MIN_TOUCH } = useTheme();
  const stores = useCatalogStores();
  const generate = useGeneratePlan();
  const [store, setStore] = useState<string | undefined>();
  const [variety, setVariety] = useState<Variety>('basic');
  const [grid, setGrid] = useState<Grid>(fullGrid);
  const [jobId, setJobId] = useState<string | undefined>();
  const [exists, setExists] = useState(false);

  async function submit(regenerate: boolean) {
    const chosen = store ?? stores.data?.[0]?.store_id;
    if (!chosen) return;
    setExists(false);
    try {
      const accepted = await generate.mutateAsync(
        buildPlanRequest({ storeId: chosen, week, variety, grid, regenerate }),
      );
      setJobId(accepted.job_id);
    } catch (error) {
      if (error instanceof ApiError && error.code === 'plan_exists') setExists(true);
    }
  }

  if (jobId) {
    return (
      <Screen>
        <Outcome jobId={jobId} week={week} onRetry={() => setJobId(undefined)} />
      </Screen>
    );
  }

  const toggle = (day: number, slot: number, value: boolean) =>
    setGrid((g) => g.map((row, d) => (d === day ? row.map((cell, s) => (s === slot ? value : cell)) : row)));

  return (
    <Screen>
      <Async
        query={stores}
        isEmpty={(data) => data.length === 0}
        empty={<EmptyState title={t('create.noStores.title')} message={t('create.noStores.message')} />}
      >
        {(list) => (
          <View style={{ gap: spacing.lg }}>
            <AppText variant="title">
              {formatDay(week)} – {formatDay(addDays(week, 6))}
            </AppText>
            {list.length > 1 ? (
              <Segmented
                label={t('create.store')}
                options={list.map((s) => ({ value: s.store_id, label: s.store_id }))}
                value={store ?? list[0].store_id}
                onChange={setStore}
              />
            ) : null}
            <View style={{ gap: spacing.xs }}>
              <Segmented
                label={t('create.variety')}
                options={(['basic', 'balanced', 'high'] as const).map((v) => ({
                  value: v,
                  label: t(`create.variety.${v}` as MessageKey),
                }))}
                value={variety}
                onChange={setVariety}
              />
              <AppText variant="caption" muted>
                {t('create.variety.hint')}
              </AppText>
            </View>

            <View style={{ gap: spacing.sm }}>
              <AppText variant="label">{t('create.when')}</AppText>
              <AppText variant="caption" muted>
                {t('create.when.hint')}
              </AppText>
              <View style={{ flexDirection: 'row' }}>
                <View style={{ width: 84 }} />
                {SLOTS.map((slot) => (
                  <AppText key={slot} variant="caption" style={{ flex: 1, textAlign: 'center' }}>
                    {t(`meal.${slot}` as MessageKey)}
                  </AppText>
                ))}
              </View>
              {grid.map((row, day) => (
                <View key={day} style={{ flexDirection: 'row', alignItems: 'center', minHeight: MIN_TOUCH }}>
                  <AppText variant="caption" style={{ width: 84 }}>
                    {formatDay(addDays(week, day))}
                  </AppText>
                  {row.map((planned, slot) => (
                    <View key={slot} style={{ flex: 1, alignItems: 'center' }}>
                      <Switch
                        value={planned}
                        onValueChange={(v) => toggle(day, slot, v)}
                        accessibilityLabel={t('create.cell', {
                          day: formatDay(addDays(week, day), 'long'),
                          meal: t(`meal.${SLOTS[slot]}` as MessageKey),
                        })}
                        trackColor={{ true: colors.primary, false: colors.border }}
                      />
                    </View>
                  ))}
                </View>
              ))}
            </View>

            {exists ? (
              <View style={{ gap: spacing.sm }}>
                <Banner kind="warning" title={t('create.replace.title')}>
                  {t('create.replace.message')}
                </Banner>
                <Button label={t('create.replace.confirm')} onPress={() => void submit(true)} />
              </View>
            ) : null}
            {generate.isError && !exists ? <ErrorState error={generate.error} /> : null}
            <Button
              label={t('create.generate')}
              disabled={plannedMeals(grid) === 0}
              loading={generate.isPending}
              onPress={() => void submit(params.regenerate === '1')}
            />
          </View>
        )}
      </Async>
    </Screen>
  );
}
