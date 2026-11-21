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

  function submit() {
    setSaved(false);
    save.mutate(
      {
        hob_type: hob,
        burners: hob === 'none' ? 0 : burners,
        oven,
        microwave,
        air_fryer: airFryer,
        // Kept as they are: the calibration itself arrives in a later phase.
        power_levels: current?.power_levels ?? null,
        calibration_level: current?.calibration_level ?? null,
        calibration_boil_1l_minutes: current?.calibration_boil_1l_minutes ?? null,
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
      <Banner title={t('tools.calibration.title')}>{t('tools.calibration.message')}</Banner>
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
