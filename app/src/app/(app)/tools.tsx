// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import { useEquipment, usePutEquipment } from '@/api/hooks';
import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { TextField } from '@/components/TextField';
import { parseNumber } from '@/features/forms/numbers';
import { Stopwatch } from '@/features/tools/Stopwatch';
import { Segmented } from '@/components/Segmented';
import { Async, describeError } from '@/components/StateViews';
import { SwitchRow } from '@/components/SwitchRow';
import { t } from '@/i18n';

const HOBS: Schemas['HobType'][] = ['induction', 'ceramic', 'electric_coil', 'gas', 'none'];

type Equipment = Schemas['Equipment'] | null;

function EquipmentForm({ current }: { current: Equipment }) {
  const save = usePutEquipment();
  const [hob, setHob] = useState<Schemas['HobType']>(current?.hob_type ?? 'induction');
  const [burners, setBurners] = useState(current?.burners ?? 2);
  const [oven, setOven] = useState(current?.oven ?? false);
  const [microwave, setMicrowave] = useState(current?.microwave ?? false);
  const [airFryer, setAirFryer] = useState(current?.air_fryer ?? false);
  const [saved, setSaved] = useState(false);
  const [levels, setLevels] = useState(current?.power_levels ? String(current.power_levels) : '');
  const [calLevel, setCalLevel] = useState(current?.calibration_level ? String(current.calibration_level) : '');
  const [calMinutes, setCalMinutes] = useState(
    current?.calibration_boil_1l_minutes ? String(Number(current.calibration_boil_1l_minutes)).replace('.', ',') : '',
  );
  const [errors, setErrors] = useState<{ levels?: string; level?: string; minutes?: string }>({});

  function submit() {
    setSaved(false);
    const next: typeof errors = {};
    const maxLevels = levels.trim() === '' ? null : parseNumber(levels);
    if (levels.trim() !== '' && (maxLevels === null || !Number.isInteger(maxLevels) || maxLevels < 1 || maxLevels > 20)) {
      next.levels = t('calib.invalid.levels');
    }
    const wantsCalibration = calLevel.trim() !== '' || calMinutes.trim() !== '';
    const level = calLevel.trim() === '' ? null : parseNumber(calLevel);
    const minutes = calMinutes.trim() === '' ? null : parseNumber(calMinutes);
    if (wantsCalibration) {
      const top = maxLevels ?? 20;
      if (level === null || !Number.isInteger(level) || level < 1 || level > top) {
        next.level = level === null && calLevel.trim() === '' ? t('calib.invalid.both') : t('calib.invalid.level', { max: top });
      }
      if (minutes === null || minutes < 1 || minutes > 60) {
        next.minutes = minutes === null && calMinutes.trim() === '' ? t('calib.invalid.both') : t('calib.invalid.minutes');
      }
    }
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    save.mutate(
      {
        hob_type: hob,
        burners: hob === 'none' ? 0 : burners,
        oven,
        microwave,
        air_fryer: airFryer,
        power_levels: maxLevels,
        calibration_level: wantsCalibration ? level : null,
        calibration_boil_1l_minutes: wantsCalibration ? minutes : null,
      },
      { onSuccess: () => setSaved(true) },
    );
  }

  return (
    <View style={{ gap: 16 }}>
      <Card style={{ gap: 12 }}>
        <Segmented
          label={t('tools.hob')}
          value={hob}
          onChange={setHob}
          options={HOBS.map((value) => ({ value, label: t(`hob.${value}` as const) }))}
        />
        {hob !== 'none' ? (
          <View style={{ gap: 8 }}>
            <AppText variant="label">{t('tools.burners')}</AppText>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <Button
                variant="secondary"
                label="−"
                a11yLabel={t('tools.less')}
                disabled={burners <= 1}
                onPress={() => setBurners((n) => Math.max(1, n - 1))}
              />
              <AppText variant="heading" accessibilityLabel={`${t('tools.burners')}: ${burners}`}>
                {burners}
              </AppText>
              <Button
                variant="secondary"
                label="+"
                a11yLabel={t('tools.more')}
                disabled={burners >= 12}
                onPress={() => setBurners((n) => Math.min(12, n + 1))}
              />
            </View>
          </View>
        ) : null}
      </Card>
      <Card>
        <AppText variant="label">{t('tools.appliances')}</AppText>
        <SwitchRow label={t('tools.oven')} value={oven} onChange={setOven} />
        <SwitchRow label={t('tools.microwave')} value={microwave} onChange={setMicrowave} />
        <SwitchRow label={t('tools.airFryer')} value={airFryer} onChange={setAirFryer} />
        {!oven ? (
          <AppText variant="caption" muted>
            {t('tools.noOven.hint')}
          </AppText>
        ) : null}
      </Card>
      {hob !== 'none' ? (
        <Card style={{ gap: 12 }}>
          <AppText variant="heading" accessibilityRole="header">
            {t('tools.calibration.title')}
          </AppText>
          <AppText muted>{t('calib.intro')}</AppText>
          <TextField label={t('calib.levels')} value={levels} onChangeText={setLevels} error={errors.levels} keyboardType="number-pad" />
          <TextField label={t('calib.level')} value={calLevel} onChangeText={setCalLevel} error={errors.level} keyboardType="number-pad" />
          <Stopwatch onStop={setCalMinutes} />
          <TextField label={t('calib.minutes')} value={calMinutes} onChangeText={setCalMinutes} error={errors.minutes} keyboardType="decimal-pad" />
          <AppText variant="caption" muted>
            {current?.calibration_level && current.calibration_boil_1l_minutes
              ? t('calib.status.done', {
                  minutes: String(Number(current.calibration_boil_1l_minutes)).replace('.', ','),
                  level: current.calibration_level,
                })
              : t('calib.status.none')}
          </AppText>
          {calLevel || calMinutes ? (
            <Button
              variant="ghost"
              label={t('calib.clear')}
              onPress={() => {
                setCalLevel('');
                setCalMinutes('');
              }}
            />
          ) : null}
        </Card>
      ) : null}
      {save.isError ? <Banner kind="warning">{describeError(save.error).message}</Banner> : null}
      {saved ? <Banner>{t('common.saved')}</Banner> : null}
      <Button label={t('common.save')} onPress={submit} loading={save.isPending} />
    </View>
  );
}

export default function ToolsScreen() {
  const equipment = useEquipment();
  return (
    <Screen onRefresh={() => void equipment.refetch()} refreshing={equipment.isRefetching}>
      <Async query={equipment}>
        {(data) => <EquipmentForm key={String(data?.id)} current={data ?? null} />}
      </Async>
    </Screen>
  );
}
