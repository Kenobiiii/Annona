// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Schemas } from '@/api/client';
import { SLOTS, type Slot } from '@/features/today/nextMeal';

/** grid[dayIndex][slotIndex]: is that meal planned? (day 0 = Monday, slots in SLOTS order). */
export type Grid = boolean[][];

export function fullGrid(): Grid {
  return Array.from({ length: 7 }, () => SLOTS.map(() => true));
}

export function plannedMeals(grid: Grid): number {
  return grid.flat().filter(Boolean).length;
}

type Variety = Schemas['PlanIn']['variety'];

/** Turn the checkbox grid into the server's schedule: days to plan plus the meals to skip. */
export function buildPlanRequest(options: {
  storeId: string;
  week: string;
  variety: NonNullable<Variety>;
  grid: Grid;
  regenerate?: boolean;
}): Schemas['PlanIn'] {
  const weekdays: number[] = [];
  const skip: [number, Slot][] = [];
  options.grid.forEach((row, day) => {
    if (!row.some(Boolean)) return; // a day with nothing planned is not planned at all
    weekdays.push(day);
    row.forEach((planned, index) => {
      if (!planned) skip.push([day, SLOTS[index]]);
    });
  });
  return {
    store_id: options.storeId,
    variety: options.variety,
    health_limits: false, // optional WHO limits are not offered in the app yet
    schedule: { week_start: options.week, weekdays, skip },
    regenerate: options.regenerate ?? false,
  };
}
