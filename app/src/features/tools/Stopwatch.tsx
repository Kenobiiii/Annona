// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { t } from '@/i18n';

function clock(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Minutes with one decimal ("7,5"), as the person would type them. */
export function minutesText(ms: number): string {
  return (Math.round(ms / 6000) / 10).toString().replace('.', ',');
}

/** A plain stopwatch: start when the heat goes on, stop when the water boils. */
export function Stopwatch({ onStop }: { onStop: (minutes: string) => void }) {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (startedAt === null) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [startedAt]);

  if (startedAt === null) {
    return (
      <Button
        variant="secondary"
        label={t('calib.timer.start')}
        onPress={() => {
          const start = Date.now();
          setStartedAt(start);
          setNow(start);
        }}
      />
    );
  }
  return (
    <View style={{ gap: 8 }}>
      <AppText variant="heading" accessibilityLiveRegion="polite">
        {t('calib.timer.running', { time: clock(Math.max(0, now - startedAt)) })}
      </AppText>
      <Button
        label={t('calib.timer.stop')}
        onPress={() => {
          onStop(minutesText(Date.now() - startedAt));
          setStartedAt(null);
        }}
      />
    </View>
  );
}
