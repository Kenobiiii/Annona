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

export function product(extra: Partial<Schemas['Product']> = {}, price: Partial<Schemas['ProductOut']> = {}): Schemas['ProductOut'] {
  return {
    product: {
      id: 5, name: 'Arroz redondo Hacendado', store_id: 'mercadona', store_sku: '5044', brand: 'Hacendado',
      category: 'grains', type: 'rice', package_amount: '1000.0', package_unit: 'g', allergens: null,
      allergens_source: null, category_source: 'rule',
      nutrition: { basis: 'g', energy_kcal: '344', protein_g: '8.2', fat_g: '1', carbohydrates_g: '75', source: 'off' },
      ...extra,
    } as Schemas['Product'],
    latest_price_cents: 115, currency: 'EUR', unit_price_cents: 115, unit_price_per: 'kg', ...price,
  };
}

export function pantryItem(id: number, productId: number, name: string, category: string, amount: string, unit = 'g', expires: string | null = null): Schemas['PantryOut'] {
  return { id, household_id: 1, product_id: productId, amount, unit, name, category, expires_at: expires, added_at: '2026-11-20T10:00:00Z' } as Schemas['PantryOut'];
}

export function recipeOut(extra: Partial<Schemas['RecipeOut']> = {}): Schemas['RecipeOut'] {
  return {
    day: '2026-11-26', slot: 'lunch', title: 'Arroz con pollo',
    eaters: [{ name: 'Pablo', servings: '1' }],
    ingredients: [
      { product_id: 1, name: 'Arroz', amount: '200', unit: 'g' },
      { product_id: 2, name: 'Pechuga de pollo', amount: '300', unit: 'g' },
    ],
    portions: { Pablo: [{ product_id: 1, name: 'Arroz', amount: '200', unit: 'g' }] },
    steps: [
      { text: 'Corta pechuga de pollo (300 g) en dados.', appliance: 'none', heat: 'none', dial_level: null, minutes: 5, minutes_estimated: true },
      { text: 'Hierve agua para arroz (200 g).', appliance: 'hob', heat: 'high', dial_level: 7, minutes: 11, minutes_estimated: false },
      { text: 'Dora el pollo.', appliance: 'hob', heat: 'medium', dial_level: 5, minutes: 10, minutes_estimated: true },
    ],
    total_minutes: 26, calibrated: false, cooked_at: null, generated: true, ...extra,
  } as Schemas['RecipeOut'];
}

export function cookOut(lines: Partial<Schemas['CookLineOut']>[], already = false): Schemas['CookOut'] {
  return {
    already_cooked: already,
    lines: lines.map((l, i) => ({
      product_id: i + 1, name: 'Arroz', unit: 'g', needed: '200', in_pantry: '500', deduct: '200', missing: '0', note: null, ...l,
    })),
  } as Schemas['CookOut'];
}
