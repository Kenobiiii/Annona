// SPDX-License-Identifier: AGPL-3.0-or-later
import * as SecureStore from 'expo-secure-store';

// SecureStore keys: letters, digits, ".", "-" and "_" only.
const KEY = 'annona.pantry_notice_seen';

/** Has the person already been told that ticking an item adds it to the pantry? */
export async function pantryNoticeSeen(): Promise<boolean> {
  try {
    return (await SecureStore.getItemAsync(KEY)) === '1';
  } catch {
    return false; // if storage fails, show the notice again rather than hide it
  }
}

export async function markPantryNoticeSeen(): Promise<void> {
  try {
    await SecureStore.setItemAsync(KEY, '1');
  } catch {
    // not being able to remember it only means it is shown again
  }
}
