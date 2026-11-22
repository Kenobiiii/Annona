// SPDX-License-Identifier: AGPL-3.0-or-later
import * as SecureStore from 'expo-secure-store';

// SecureStore keys: letters, digits, ".", "-" and "_" only.

/** Has this one-time notice already been shown? If storage fails, show it again. */
export async function noticeSeen(key: string): Promise<boolean> {
  try {
    return (await SecureStore.getItemAsync(key)) === '1';
  } catch {
    return false;
  }
}

export async function markNoticeSeen(key: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(key, '1');
  } catch {
    // not being able to remember it only means it is shown again
  }
}
