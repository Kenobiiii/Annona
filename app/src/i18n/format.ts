// SPDX-License-Identifier: AGPL-3.0-or-later
/** Display formatting only: the server computes every number. */

export const LOCALE = 'es-ES';

export function formatMoney(cents: number, currency = 'EUR'): string {
  return new Intl.NumberFormat(LOCALE, { style: 'currency', currency }).format(cents / 100);
}

/** "1000" + "g" -> "1 kg"; "1500" + "ml" -> "1,5 l"; units are shown as-is. */
export function formatAmount(amount: number | string, unit: string): string {
  const value = Number(amount);
  const number = (n: number) => new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 }).format(n);
  if (unit === 'g' && value >= 1000) return `${number(value / 1000)} kg`;
  if (unit === 'ml' && value >= 1000) return `${number(value / 1000)} l`;
  if (unit === 'unit') return `${number(value)} ud.`;
  return `${number(value)} ${unit}`;
}

/** Local calendar date as YYYY-MM-DD (not UTC: "today" is what the person's clock says). */
export function localISODate(date: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Monday of the week containing ``iso`` (YYYY-MM-DD). */
export function mondayOf(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const offset = (date.getDay() + 6) % 7; // Monday = 0
  date.setDate(date.getDate() - offset);
  return localISODate(date);
}

export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  return localISODate(new Date(y, m - 1, d + days));
}

export function formatDay(iso: string, style: 'short' | 'long' = 'short'): string {
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat(LOCALE, {
    weekday: style === 'long' ? 'long' : 'short',
    day: 'numeric',
    month: 'short',
  }).format(new Date(y, m - 1, d));
}
