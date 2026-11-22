// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { useDeleteProfile, useProfiles, useSaveProfile } from '@/api/hooks';
import { fieldErrors } from '@/api/errors';
import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Chip } from '@/components/Chip';
import { confirmAction } from '@/components/confirm';
import { Screen } from '@/components/Screen';
import { Segmented } from '@/components/Segmented';
import { Async, describeError } from '@/components/StateViews';
import { SwitchRow } from '@/components/SwitchRow';
import { TextField } from '@/components/TextField';
import { parseNumber } from '@/features/forms/numbers';
import { ALLERGENS } from '@/features/products/constants';
import { t } from '@/i18n';

type Out = Schemas['ProfileOut'];
type Level = 'avoid' | 'less';
const ACTIVITIES: Schemas['ActivityLevel'][] = ['inactive', 'low_active', 'active', 'very_active'];
const GOALS: Schemas['Goal'][] = ['cut', 'maintain', 'bulk'];
const DIETS: Schemas['Diet'][] = ['omnivore', 'pescatarian', 'vegetarian', 'vegan'];
const SERVINGS = ['meat', 'fish', 'eggs'] as const;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function ProfileForm({ existing }: { existing?: Out }) {
  const router = useRouter();
  const save = useSaveProfile();
  const remove = useDeleteProfile();
  const p = existing?.profile;
  const [name, setName] = useState(p?.name ?? '');
  const [sex, setSex] = useState<Schemas['Sex']>(p?.sex ?? 'female');
  const [birth, setBirth] = useState(p?.birth_date ?? '');
  const [height, setHeight] = useState(p ? String(p.height_cm) : '');
  const [weight, setWeight] = useState(p ? String(p.weight_kg) : '');
  const [activity, setActivity] = useState<Schemas['ActivityLevel']>(p?.activity ?? 'low_active');
  const [protein, setProtein] = useState(p?.protein_g_per_kg ? String(p.protein_g_per_kg).replace('.', ',') : '');
  const [goal, setGoal] = useState<Schemas['Goal']>(p?.goal ?? 'maintain');
  const [diet, setDiet] = useState<Schemas['Diet']>(p?.diet ?? 'omnivore');
  const [allergies, setAllergies] = useState<Schemas['Allergen'][]>(p?.allergies ?? []);
  const [confirmed, setConfirmed] = useState(p?.allergies_confirmed ?? false);
  const [servings, setServings] = useState<Record<string, string>>(
    Object.fromEntries(SERVINGS.map((g) => [g, String(p?.weekly_servings?.[g] ?? 0)])),
  );
  const [prefs, setPrefs] = useState<Record<string, Level>>(p?.food_preferences ?? {});
  const [prefType, setPrefType] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(existing?.allergy_notice ?? null);

  function submit() {
    const next: Record<string, string> = {};
    const h = parseNumber(height);
    const w = parseNumber(weight);
    if (!name.trim()) next.name = t('profile.invalid.name');
    if (!DATE.test(birth.trim())) next.birth_date = t('profile.invalid.date');
    if (h === null) next.height_cm = t('profile.invalid.number');
    if (w === null) next.weight_kg = t('profile.invalid.number');
    const proteinValue = protein.trim() === '' ? null : parseNumber(protein);
    if (proteinValue !== null && (proteinValue < 0.8 || proteinValue > 3)) next.protein_g_per_kg = t('profile.invalid.protein');
    if (protein.trim() !== '' && proteinValue === null) next.protein_g_per_kg = t('profile.invalid.protein');
    const counts: Record<string, number> = {};
    for (const g of SERVINGS) {
      const n = parseNumber(servings[g]);
      if (n === null || !Number.isInteger(n)) next[`weekly_servings.${g}`] = t('profile.invalid.number');
      else if (n > 0) counts[g] = n;
    }
    setErrors(next);
    if (Object.keys(next).length > 0 || h === null || w === null) return;
    save.mutate(
      {
        id: p?.id ?? undefined,
        body: {
          name: name.trim(),
          sex,
          birth_date: birth.trim(),
          height_cm: h,
          weight_kg: w,
          activity,
          goal,
          diet,
          protein_g_per_kg: proteinValue,
          allergies,
          allergies_confirmed: confirmed,
          food_preferences: prefs,
          weekly_servings: counts,
        },
      },
      {
        onSuccess: (out) => {
          if (out.allergy_notice) setNotice(out.allergy_notice);
          else router.back();
        },
        onError: (error) => setErrors(fieldErrors(error)),
      },
    );
  }

  async function del() {
    if (!p?.id) return;
    const ok = await confirmAction(t('profile.delete.title', { name: p.name }), t('profile.delete.message'), t('common.delete'), t('common.cancel'));
    if (ok) remove.mutate(p.id, { onSuccess: () => router.back() });
  }

  function addPref() {
    const type = prefType.trim().toLowerCase();
    if (!type) return;
    setPrefs((cur) => ({ ...cur, [type]: 'less' }));
    setPrefType('');
  }

  const generic = save.isError && Object.keys(fieldErrors(save.error)).length === 0;
  return (
    <View style={{ gap: 16 }}>
      <Card style={{ gap: 12 }}>
        <TextField label={t('profile.name')} value={name} onChangeText={setName} error={errors.name} autoCapitalize="words" />
        <Segmented label={t('profile.sex')} value={sex} onChange={setSex} options={(['female', 'male'] as const).map((v) => ({ value: v, label: t(`sex.${v}`) }))} />
        <AppText variant="caption" muted>
          {t('profile.sex.hint')}
        </AppText>
        <TextField label={t('profile.birth')} value={birth} onChangeText={setBirth} error={errors.birth_date} keyboardType="numbers-and-punctuation" placeholder="2000-01-31" />
        <TextField label={t('profile.height')} value={height} onChangeText={setHeight} error={errors.height_cm} keyboardType="decimal-pad" />
        <TextField label={t('profile.weight')} value={weight} onChangeText={setWeight} error={errors.weight_kg} keyboardType="decimal-pad" />
      </Card>
      <Card style={{ gap: 12 }}>
        <Segmented label={t('profile.activity')} value={activity} onChange={setActivity} options={ACTIVITIES.map((v) => ({ value: v, label: t(`activity.${v}`) }))} />
        <AppText variant="caption" muted>
          {t('profile.activity.hint')}
        </AppText>
        <Segmented label={t('profile.goal')} value={goal} onChange={setGoal} options={GOALS.map((v) => ({ value: v, label: t(`goal.${v}`) }))} />
        <TextField label={t('profile.protein')} value={protein} onChangeText={setProtein} error={errors.protein_g_per_kg} keyboardType="decimal-pad" />
        <AppText variant="caption" muted>
          {t('profile.protein.hint')}
        </AppText>
        <Segmented label={t('profile.diet')} value={diet} onChange={setDiet} options={DIETS.map((v) => ({ value: v, label: t(`diet.${v}`) }))} />
      </Card>
      <Card style={{ gap: 12 }}>
        <AppText variant="label">{t('profile.allergies')}</AppText>
        <AppText variant="caption" muted>
          {t('profile.allergies.hint')}
        </AppText>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {ALLERGENS.map((a) => (
            <Chip
              key={a}
              label={t(`allergen.${a}`)}
              selected={allergies.includes(a)}
              onToggle={() => setAllergies((cur) => (cur.includes(a) ? cur.filter((x) => x !== a) : [...cur, a]))}
            />
          ))}
        </View>
        <SwitchRow label={t('profile.allergies.confirm')} value={confirmed} onChange={setConfirmed} />
        {errors.allergies_confirmed ? <AppText variant="caption">{errors.allergies_confirmed}</AppText> : null}
        {notice ? <Banner kind="warning">{notice}</Banner> : null}
      </Card>
      <Card style={{ gap: 12 }}>
        <AppText variant="label">{t('profile.servings')}</AppText>
        {SERVINGS.map((g) => (
          <TextField
            key={g}
            label={t(`serving.${g}`)}
            value={servings[g]}
            onChangeText={(v) => setServings((cur) => ({ ...cur, [g]: v }))}
            error={errors[`weekly_servings.${g}`]}
            keyboardType="number-pad"
          />
        ))}
      </Card>
      <Card style={{ gap: 12 }}>
        <AppText variant="label">{t('profile.prefs')}</AppText>
        <AppText variant="caption" muted>
          {t('profile.prefs.hint')}
        </AppText>
        {Object.entries(prefs).map(([type, level]) => (
          <View key={type} style={{ gap: 4 }}>
            <AppText>{type}</AppText>
            <Segmented
              value={level}
              onChange={(v) => setPrefs((cur) => ({ ...cur, [type]: v }))}
              options={[
                { value: 'less', label: t('profile.pref.less') },
                { value: 'avoid', label: t('profile.pref.avoid') },
              ]}
            />
            <Button
              variant="ghost"
              label={t('common.delete')}
              a11yLabel={t('profile.pref.remove', { type })}
              onPress={() =>
                setPrefs((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => k !== type)))
              }
            />
          </View>
        ))}
        <TextField label={t('profile.prefs.type')} value={prefType} onChangeText={setPrefType} onSubmitEditing={addPref} />
        <Button variant="secondary" label={t('profile.prefs.add')} onPress={addPref} />
      </Card>
      {existing ? (
        <Card>
          <AppText variant="label">{t('profile.targets')}</AppText>
          <AppText>
            {Math.round(Number(existing.targets.energy_kcal))} kcal · {Math.round(Number(existing.targets.protein_g))} g proteína
          </AppText>
        </Card>
      ) : null}
      {generic ? <Banner kind="warning">{describeError(save.error).message}</Banner> : null}
      <Button label={t('profile.save')} onPress={submit} loading={save.isPending} />
      {existing ? <Button variant="danger" label={t('profile.delete')} onPress={() => void del()} loading={remove.isPending} /> : null}
    </View>
  );
}

export default function ProfileScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const profiles = useProfiles();
  const isNew = id === 'new';
  return (
    <Screen>
      <AppText variant="title" accessibilityRole="header">
        {t(isNew ? 'profile.new' : 'profile.edit')}
      </AppText>
      {isNew ? (
        <ProfileForm />
      ) : (
        <Async query={profiles}>
          {(list) => {
            const found = list.find((x) => String(x.profile.id) === id);
            return found ? <ProfileForm key={String(found.profile.id)} existing={found} /> : <Banner kind="warning">{t('error.generic')}</Banner>;
          }}
        </Async>
      )}
    </Screen>
  );
}
