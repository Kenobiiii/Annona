// SPDX-License-Identifier: AGPL-3.0-or-later
import { buildPlanRequest, fullGrid, plannedMeals } from '@/features/menu/schedule';
import { pickNextMeal, slotAt } from '@/features/today/nextMeal';

describe('which meal to show', () => {
  const at = (h: number) => new Date(2026, 10, 26, h, 0);
  it.each([[7, 'breakfast'], [11, 'lunch'], [15, 'lunch'], [17, 'snack'], [21, 'dinner']])('%ih -> %s', (h, slot) => {
    expect(slotAt(at(h))).toBe(slot);
  });

  const meals = [{ slot: 'dinner' }, { slot: 'breakfast' }, { slot: 'lunch' }];
  it('picks the current meal, or the next planned one', () => {
    expect(pickNextMeal(meals, at(8))?.slot).toBe('breakfast');
    expect(pickNextMeal(meals, at(13))?.slot).toBe('lunch');
    expect(pickNextMeal(meals, at(17))?.slot).toBe('dinner'); // no snack planned: next is dinner
  });
  it('falls back to the last meal once all are past, and handles an empty day', () => {
    expect(pickNextMeal([{ slot: 'breakfast' }, { slot: 'lunch' }], at(22))?.slot).toBe('lunch');
    expect(pickNextMeal([], at(12))).toBeUndefined();
  });
});

describe('buildPlanRequest', () => {
  it('plans the whole week by default', () => {
    const request = buildPlanRequest({ storeId: 'mercadona', week: '2026-11-23', variety: 'basic', grid: fullGrid() });
    expect(request.schedule).toEqual({ week_start: '2026-11-23', weekdays: [0, 1, 2, 3, 4, 5, 6], skip: [] });
    expect(request).toMatchObject({ store_id: 'mercadona', variety: 'basic', regenerate: false });
  });

  it("the owner's example: Mon-Fri, no snack, no dinner on Tue/Thu/Fri", () => {
    const grid = fullGrid().map((row, day) => (day > 4 ? row.map(() => false) : [...row]));
    grid.forEach((row, day) => {
      if (day <= 4) row[2] = false; // no snack
      if ([1, 3, 4].includes(day)) row[3] = false; // no dinner
    });
    const { schedule } = buildPlanRequest({ storeId: 'm', week: '2026-11-23', variety: 'balanced', grid });
    expect(schedule.weekdays).toEqual([0, 1, 2, 3, 4]); // weekend has nothing planned: not planned
    expect(schedule.skip).toEqual([
      [0, 'snack'], [1, 'snack'], [1, 'dinner'], [2, 'snack'], [3, 'snack'], [3, 'dinner'], [4, 'snack'], [4, 'dinner'],
    ]);
    expect(plannedMeals(grid)).toBe(12);
  });

  it('can ask to replace an existing plan', () => {
    expect(buildPlanRequest({ storeId: 'm', week: '2026-11-23', variety: 'high', grid: fullGrid(), regenerate: true }).regenerate).toBe(true);
  });
});
