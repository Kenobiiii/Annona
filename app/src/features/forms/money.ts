// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * "60" -> 6000, "59,90" -> 5990, "0.5" -> 50 (integer cents, read digit by digit: no floating
 * point is involved). Returns null for anything that is not an amount with at most 2 decimals.
 */
export function eurosToCents(text: string): number | null {
  const match = /^(\d+)(?:[.,](\d{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  const cents = Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0') || '0');
  return Number.isSafeInteger(cents) ? cents : null;
}

export function centsToEuros(cents: number): string {
  const whole = Math.floor(cents / 100);
  const rest = String(cents % 100).padStart(2, '0');
  return rest === '00' ? String(whole) : `${whole},${rest}`;
}
