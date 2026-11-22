// SPDX-License-Identifier: AGPL-3.0-or-later
import { markNoticeSeen, noticeSeen } from '@/features/forms/seenNotice';

const KEY = 'annona.receipt_notice_seen';

/** Has the person been told that the photo is sent to the AI provider to be read? */
export const receiptNoticeSeen = () => noticeSeen(KEY);
export const markReceiptNoticeSeen = () => markNoticeSeen(KEY);
