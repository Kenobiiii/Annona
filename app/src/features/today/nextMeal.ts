// SPDX-License-Identifier: AGPL-3.0-or-later

export const SLOTS = ['breakfast', 'lunch', 'snack', 'dinner'] as const;
export type Slot = (typeof SLOTS)[number];

/** Which meal of the day it is by the clock (presentation only; hours are display choices). */
export function slotAt(now: Date): Slot {
  const hour = now.getHours();
  if (hour < 11) return 'breakfast';
  if (hour < 16) return 'lunch';
  if (hour < 19) return 'snack';
  return 'dinner';
}

/** The meal to highlight: the current one or the next planned one; the last if all are past. */
export function pickNextMeal<T extends { slot: string }>(meals: T[], now: Date): T | undefined {
  if (meals.length === 0) return undefined;
  const ordered = [...meals].sort((a, b) => SLOTS.indexOf(a.slot as Slot) - SLOTS.indexOf(b.slot as Slot));
  const current = SLOTS.indexOf(slotAt(now));
  return ordered.find((m) => SLOTS.indexOf(m.slot as Slot) >= current) ?? ordered[ordered.length - 1];
}
