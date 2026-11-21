// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';

/** ``value`` after it has stopped changing for ``ms`` (e.g. to search while typing). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}
