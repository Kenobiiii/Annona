// SPDX-License-Identifier: AGPL-3.0-or-later
import { View } from 'react-native';

import type { Schemas } from '@/api/client';
import { AppText } from '@/components/AppText';
import { t, type MessageKey } from '@/i18n';
import { useTheme } from '@/theme';

type Step = Schemas['RenderedStep'];

/** "placa · fuego medio · nivel 5 (aprox.) · ~10 min" */
export function stepDetails(step: Step): string {
  const parts: string[] = [];
  if (step.appliance !== 'none') parts.push(t(`recipe.appliance.${step.appliance}` as MessageKey));
  if (step.heat !== 'none') parts.push(t(`recipe.heat.${step.heat}` as MessageKey));
  if (step.dial_level != null && step.appliance === 'hob') parts.push(t('recipe.dial', { level: step.dial_level }));
  if (step.minutes != null) {
    parts.push(t(step.minutes_estimated ? 'recipe.minutes.approx' : 'recipe.minutes', { minutes: step.minutes }));
  }
  return parts.join(' · ');
}

export function StepList({ steps }: { steps: Step[] }) {
  const { spacing } = useTheme();
  return (
    <View style={{ gap: spacing.md }}>
      {steps.map((step, i) => {
        const details = stepDetails(step);
        return (
          <View key={i} style={{ gap: 2 }}>
            <AppText>
              {i + 1}. {step.text}
            </AppText>
            {details ? (
              <AppText variant="caption" muted>
                {details}
              </AppText>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}
