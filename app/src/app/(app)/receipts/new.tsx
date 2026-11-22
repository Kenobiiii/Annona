// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { ApiError } from '@/api/errors';
import { useUploadReceipt } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { confirmAction } from '@/components/confirm';
import { Screen } from '@/components/Screen';
import { LoadingState } from '@/components/StateViews';
import { markReceiptNoticeSeen, receiptNoticeSeen } from '@/features/receipts/notice';
import { PermissionDenied, pickReceiptPhoto, type PhotoSource } from '@/features/receipts/photo';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

export default function NewReceiptScreen() {
  const router = useRouter();
  const upload = useUploadReceipt();
  const { spacing } = useTheme();
  const [problem, setProblem] = useState<string | null>(null);

  async function start(source: PhotoSource) {
    setProblem(null);
    if (!(await receiptNoticeSeen())) {
      const ok = await confirmAction(t('receipt.privacy.title'), t('receipt.privacy.message'), t('receipt.privacy.ok'), t('common.cancel'));
      if (!ok) return;
      await markReceiptNoticeSeen();
    }
    let uri: string | null;
    try {
      uri = await pickReceiptPhoto(source);
    } catch (error) {
      setProblem(error instanceof PermissionDenied ? t('receipt.new.permission') : t('receipt.new.failed'));
      return;
    }
    if (!uri) return; // cancelled
    upload.mutate(uri, {
      onSuccess: (receipt) => router.replace({ pathname: '/receipts/[id]', params: { id: String(receipt.id) } }),
    });
  }

  const failure =
    upload.error instanceof ApiError && upload.error.code === 'bad_image'
      ? t('receipt.new.bad_image')
      : upload.isError
        ? `${t('receipt.new.failed')}: ${upload.error instanceof ApiError ? upload.error.message : ''}`.trim()
        : null;

  return (
    <Screen>
      <AppText variant="title" accessibilityRole="header">
        {t('receipt.new.title')}
      </AppText>
      {upload.isPending ? (
        <View style={{ gap: spacing.md }}>
          <LoadingState />
          <AppText variant="heading" style={{ textAlign: 'center' }}>
            {t('receipt.new.reading')}
          </AppText>
          <AppText muted style={{ textAlign: 'center' }}>
            {t('receipt.new.reading.hint')}
          </AppText>
        </View>
      ) : (
        <View style={{ gap: spacing.md }}>
          <AppText>{t('receipt.new.intro')}</AppText>
          <AppText variant="caption" muted>
            {t('receipt.new.tips')}
          </AppText>
          {problem ? <Banner kind="warning">{problem}</Banner> : null}
          {failure ? <Banner kind="warning">{failure}</Banner> : null}
          <Button label={t('receipt.new.camera')} onPress={() => void start('camera')} />
          <Button variant="secondary" label={t('receipt.new.gallery')} onPress={() => void start('gallery')} />
        </View>
      )}
    </Screen>
  );
}
