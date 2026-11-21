// SPDX-License-Identifier: AGPL-3.0-or-later

export type UrlResult =
  | { ok: true; url: string }
  | { ok: false; error: 'empty' | 'url' | 'protocol' };

/** Normalise what the user typed: add http:// if missing, drop trailing slashes. */
export function normalizeServerUrl(input: string): UrlResult {
  const text = input.trim();
  if (!text) return { ok: false, error: 'empty' };
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `http://${text}`;
  let parsed: URL;
  try {
    parsed = new URL(withScheme);
  } catch {
    return { ok: false, error: 'url' };
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, error: 'protocol' };
  }
  if (!parsed.hostname) return { ok: false, error: 'url' };
  return { ok: true, url: `${parsed.origin}${parsed.pathname.replace(/\/+$/, '')}` };
}

export function isCleartext(url: string): boolean {
  return url.startsWith('http://');
}
