// SPDX-License-Identifier: AGPL-3.0-or-later

/** Parse what a person types ("1,5", " 250 ") into a number; null if it is not a valid number. */
export function parseNumber(text: string): number | null {
  const cleaned = text.trim().replace(',', '.');
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}
