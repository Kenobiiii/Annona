// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Schemas } from '@/api/client';

export const targets = {
  bmr_kcal: '1906', tee_kcal: '3336', energy_kcal: '3336', energy_kcal_min: '3169',
  energy_kcal_max: '3503', protein_g: '136', fat_g: '111', fat_g_min: '74', fat_g_max: '130',
  carbohydrates_g: '448', warnings: [],
} as Schemas['DailyTargets'];

export function profile(name = 'Pablo', id = 1, extra: Partial<Schemas['UserProfile']> = {}): Schemas['ProfileOut'] {
  return {
    profile: {
      id, household_id: 1, name, sex: 'male', birth_date: '2005-01-01', height_cm: '185',
      weight_kg: '85', activity: 'active', goal: 'maintain', diet: 'omnivore', allergies: [],
      allergies_confirmed: true, food_preferences: {}, weekly_servings: {}, ...extra,
    } as Schemas['UserProfile'],
    targets,
    allergy_notice: null,
  };
}

export function meal(slot: Schemas['MealOut']['slot'], title: string, day = '2026-11-26', extra: Partial<Schemas['MealOut']> = {}): Schemas['MealOut'] {
  return {
    day, slot, title, steps: [`Prepara ${title.toLowerCase()}.`], needs: [],
    portions: { Pablo: [{ product_id: 1, name: 'Arroz', amount: '100.0', unit: 'g' }, { product_id: 2, name: 'Aceite', amount: '1500', unit: 'ml' }] },
    ...extra,
  };
}

export const household = { id: 1, name: 'Casa', weekly_budget_cents: 6000, currency: 'EUR' };

export function plan(week: string, meals: Schemas['MealOut'][]): Schemas['PlanOut'] {
  return { plan: { id: 7, household_id: 1, week_start: week, status: 'active', created_at: '2026-11-23T10:00:00Z' }, meals };
}
