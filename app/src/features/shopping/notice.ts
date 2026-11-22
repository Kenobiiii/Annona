// SPDX-License-Identifier: AGPL-3.0-or-later
import { markNoticeSeen, noticeSeen } from '@/features/forms/seenNotice';

const KEY = 'annona.pantry_notice_seen';

/** Has the person been told that ticking an item adds it to the pantry? */
export const pantryNoticeSeen = () => noticeSeen(KEY);
export const markPantryNoticeSeen = () => markNoticeSeen(KEY);
