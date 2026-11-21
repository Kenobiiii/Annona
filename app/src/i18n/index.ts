// SPDX-License-Identifier: AGPL-3.0-or-later
import { es, type MessageKey } from './es';

export type { MessageKey };
export * from './format';

/** Catalogs by language; the default is Spanish. Add more here. */
const catalogs: Record<string, Record<string, string>> = { es };
let language = 'es';

export function setLanguage(code: string): void {
  language = code in catalogs ? code : 'es';
}

/** Translate ``key``, replacing ``{name}`` placeholders. Unknown keys show the key itself. */
export function t(key: MessageKey, params: Record<string, string | number> = {}): string {
  const template = catalogs[language]?.[key] ?? es[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`));
}
