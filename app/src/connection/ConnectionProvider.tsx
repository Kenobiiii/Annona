// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { clearConnection, loadConnection, saveConnection, type Connection } from './storage';

type State = {
  status: 'loading' | 'unconfigured' | 'ready';
  connection: Connection | null;
  save: (connection: Connection) => Promise<void>;
  clear: () => Promise<void>;
};

const Context = createContext<State | null>(null);

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<State['status']>('loading');
  const [connection, setConnection] = useState<Connection | null>(null);

  useEffect(() => {
    let active = true;
    loadConnection()
      .then((loaded) => {
        if (!active) return;
        setConnection(loaded);
        setStatus(loaded ? 'ready' : 'unconfigured');
      })
      .catch(() => active && setStatus('unconfigured'));
    return () => {
      active = false;
    };
  }, []);

  const save = useCallback(async (next: Connection) => {
    await saveConnection(next);
    setConnection(next);
    setStatus('ready');
  }, []);

  const clear = useCallback(async () => {
    await clearConnection();
    setConnection(null);
    setStatus('unconfigured');
  }, []);

  const value = useMemo(() => ({ status, connection, save, clear }), [status, connection, save, clear]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useConnection(): State {
  const value = useContext(Context);
  if (!value) throw new Error('useConnection must be used inside ConnectionProvider');
  return value;
}
