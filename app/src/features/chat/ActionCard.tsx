// SPDX-License-Identifier: AGPL-3.0-or-later
import { View } from 'react-native';

import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { t } from '@/i18n';
import type { ActionState } from './useChat';

type Props = {
  action: ActionState;
  onResolve: (confirm: boolean) => void;
};

/** A change the assistant proposed. Nothing happens until the person presses Confirm. */
export function ActionCard({ action, onResolve }: Props) {
  const open = action.status === 'pending' || action.status === 'busy';
  return (
    <Card style={{ gap: 8 }}>
      <AppText variant="label">{t('chat.action.title')}</AppText>
      <AppText>{action.summary}</AppText>
      {open ? (
        <View style={{ gap: 8 }}>
          <AppText variant="caption" muted>
            {t('chat.action.pending')}
          </AppText>
          <Button label={t('chat.action.confirm')} onPress={() => onResolve(true)} loading={action.status === 'busy'} />
          <Button variant="ghost" label={t('chat.action.cancel')} onPress={() => onResolve(false)} disabled={action.status === 'busy'} />
        </View>
      ) : (
        <AppText variant="caption" muted accessibilityLiveRegion="polite">
          {action.status === 'confirmed'
            ? t('chat.action.confirmed')
            : action.status === 'cancelled'
              ? t('chat.action.cancelled')
              : t('chat.action.failed', { error: action.error ?? '' })}
        </AppText>
      )}
    </Card>
  );
}
