// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRouter } from 'expo-router';
import { View } from 'react-native';

import { AppText } from '@/components/AppText';
import { Screen } from '@/components/Screen';
import { ConnectionForm } from '@/features/connection/ConnectionForm';
import { t } from '@/i18n';

/** First run: connect the app to the user's own Annona server. */
export default function ConnectScreen() {
  const router = useRouter();
  return (
    <Screen>
      <View style={{ gap: 12, paddingTop: 24 }}>
        <AppText variant="title">{t('connect.title')}</AppText>
        <AppText muted>{t('connect.intro')}</AppText>
      </View>
      <ConnectionForm onSaved={() => router.replace('/')} />
    </Screen>
  );
}
