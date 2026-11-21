// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { useHousehold, useLlmSettings, usePutHousehold, useProfiles } from '@/api/hooks';
import { ApiError } from '@/api/errors';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { confirmAction } from '@/components/confirm';
import { Screen } from '@/components/Screen';
import { Async, describeError, LoadingState } from '@/components/StateViews';
import { TextField } from '@/components/TextField';
import { useConnection } from '@/connection/ConnectionProvider';
import { ConnectionForm } from '@/features/connection/ConnectionForm';
import { centsToEuros, eurosToCents } from '@/features/forms/money';
import { formatMoney, t } from '@/i18n';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: 8 }}>
      <AppText variant="heading" accessibilityRole="header">
        {title}
      </AppText>
      {children}
    </View>
  );
}

function ServerSection() {
  const { connection, clear } = useConnection();
  async function forget() {
    if (await confirmAction(t('settings.server.forget.title'), t('settings.server.forget.message'), t('common.delete'), t('common.cancel'))) {
      await clear();
    }
  }
  return (
    <Section title={t('settings.server')}>
      <Card style={{ gap: 12 }}>
        {connection ? <AppText muted>{connection.baseUrl}</AppText> : null}
        <ConnectionForm />
        <Button variant="ghost" label={t('settings.server.forget')} onPress={() => void forget()} />
      </Card>
    </Section>
  );
}

function AiSection() {
  const llm = useLlmSettings();
  return (
    <Section title={t('settings.ai')}>
      <Card style={{ gap: 8 }}>
        <Async query={llm}>
          {(data) => (
            <>
              {data.models.map((m) => (
                <View key={m.tier}>
                  <AppText variant="label">{t(`settings.ai.tier.${m.tier}` as 'settings.ai.tier.small')}</AppText>
                  <AppText>{m.model}</AppText>
                  <AppText variant="caption" muted>
                    {t(
                      m.key_configured === null
                        ? 'settings.ai.key.unknown'
                        : m.key_configured
                          ? 'settings.ai.key.ok'
                          : 'settings.ai.key.missing',
                    )}
                  </AppText>
                </View>
              ))}
              <AppText variant="caption" muted>
                {t('settings.ai.spent', { amount: `${data.spent_usd} $` })}
              </AppText>
            </>
          )}
        </Async>
        <AppText variant="caption" muted>
          {t('settings.ai.where')}
        </AppText>
      </Card>
    </Section>
  );
}

function HouseholdForm({ initial }: { initial?: { name: string; cents: number; currency: string } }) {
  const save = usePutHousehold();
  const [name, setName] = useState(initial?.name ?? '');
  const [budget, setBudget] = useState(initial ? centsToEuros(initial.cents) : '');
  const [currency, setCurrency] = useState(initial?.currency ?? 'EUR');
  const [errors, setErrors] = useState<{ name?: string; budget?: string }>({});
  const [saved, setSaved] = useState(false);

  function submit() {
    const cents = eurosToCents(budget);
    const next = {
      name: name.trim() ? undefined : t('profile.invalid.name'),
      budget: cents === null ? t('settings.household.invalid') : undefined,
    };
    setErrors(next);
    setSaved(false);
    if (next.name || next.budget || cents === null) return;
    save.mutate(
      { name: name.trim(), weekly_budget_cents: cents, currency: currency.trim().toUpperCase() || 'EUR' },
      { onSuccess: () => setSaved(true) },
    );
  }

  return (
    <Card style={{ gap: 12 }}>
      {!initial ? <AppText>{t('settings.household.intro')}</AppText> : null}
      <TextField label={t('settings.household.name')} value={name} onChangeText={setName} error={errors.name} autoCapitalize="sentences" />
      <TextField label={t('settings.household.budget')} value={budget} onChangeText={setBudget} error={errors.budget} keyboardType="decimal-pad" />
      <TextField label={t('settings.household.currency')} value={currency} onChangeText={setCurrency} maxLength={3} autoCapitalize="characters" />
      {save.isError ? <Banner kind="warning">{describeError(save.error).message}</Banner> : null}
      {saved ? <Banner>{t('common.saved')}</Banner> : null}
      <Button label={initial ? t('common.save') : t('settings.household.create')} onPress={submit} loading={save.isPending} />
    </Card>
  );
}

function PeopleSection() {
  const router = useRouter();
  const profiles = useProfiles();
  return (
    <Section title={t('settings.people')}>
      <Async query={profiles}>
        {(data) => (
          <View style={{ gap: 8 }}>
            {data.length === 0 ? <AppText muted>{t('settings.people.empty')}</AppText> : null}
            {data.map(({ profile, targets }) => (
              <Card key={profile.id}>
                <Button
                  variant="ghost"
                  label={profile.name}
                  hint={t('common.edit')}
                  onPress={() => router.push(`/settings/profile/${profile.id}`)}
                />
                <AppText variant="caption" muted style={{ textAlign: 'center' }}>
                  {t('settings.people.kcal', { kcal: Math.round(Number(targets.energy_kcal)) })}
                </AppText>
              </Card>
            ))}
            <Button variant="secondary" label={t('settings.people.add')} onPress={() => router.push('/settings/profile/new')} />
          </View>
        )}
      </Async>
    </Section>
  );
}

export default function SettingsScreen() {
  const household = useHousehold();
  const needsSetup = household.error instanceof ApiError && household.error.code === 'setup_required';
  return (
    <Screen onRefresh={() => void household.refetch()} refreshing={household.isRefetching}>
      <ServerSection />
      <Section title={t('settings.household')}>
        {household.isPending ? (
          <LoadingState />
        ) : needsSetup ? (
          <HouseholdForm />
        ) : household.isError ? (
          <Async query={household}>{() => null}</Async>
        ) : (
          <HouseholdForm
            key={`${household.data.name}|${household.data.weekly_budget_cents}|${household.data.currency}`}
            initial={{ name: household.data.name, cents: household.data.weekly_budget_cents, currency: household.data.currency }}
          />
        )}
        {household.data ? (
          <AppText variant="caption" muted>
            {formatMoney(household.data.weekly_budget_cents, household.data.currency)}
          </AppText>
        ) : null}
      </Section>
      {household.data ? <PeopleSection /> : null}
      <AiSection />
      <Section title={t('settings.app')}>
        <Card>
          <AppText>
            {t('settings.language')}: {t('settings.language.es')}
          </AppText>
          <AppText>
            {t('settings.units')}: {t('settings.units.value')}
          </AppText>
        </Card>
        <Banner>{t('settings.disclaimer')}</Banner>
      </Section>
    </Screen>
  );
}
