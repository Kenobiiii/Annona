// SPDX-License-Identifier: AGPL-3.0-or-later
import { Alert, Platform } from 'react-native';

/** Ask the person to confirm something destructive; resolves true if they accept. */
export function confirmAction(title: string, message: string, accept: string, cancel: string): Promise<boolean> {
  if (Platform.OS === 'web') {
    return Promise.resolve(globalThis.confirm?.(`${title}\n\n${message}`) ?? false);
  }
  return new Promise((resolve) =>
    Alert.alert(
      title,
      message,
      [
        { text: cancel, style: 'cancel', onPress: () => resolve(false) },
        { text: accept, style: 'destructive', onPress: () => resolve(true) },
      ],
      { cancelable: true, onDismiss: () => resolve(false) },
    ),
  );
}
