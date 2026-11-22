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

type ReceiptLine = Schemas['ReceiptLineOut'];

export function receiptLine(id: number, raw: string, total: number, extra: Partial<ReceiptLine> = {}): ReceiptLine {
  return {
    id, raw_text: raw, total_cents: total, quantity: null, unit: null, product: null, confidence: null,
    preselected: false, alternatives: [], proposed_amount: null, proposed_unit: null, proposed_price_cents: null,
    notes: [], issues: [], status: 'suggested', ...extra,
  } as ReceiptLine;
}

export function receiptOut(extra: Partial<Schemas['ReceiptOut']> = {}): Schemas['ReceiptOut'] {
  const rice = receiptLine(1, 'ARROZ REDONDO 1KG', 115, {
    product: { product_id: 10, name: 'Arroz redondo Hacendado', confidence: '0.97' }, confidence: '0.97',
    preselected: true, proposed_amount: '1000', proposed_unit: 'g', proposed_price_cents: 115,
  });
  const milk = receiptLine(2, 'LECHE', 498, {
    product: { product_id: 11, name: 'Leche entera Hacendado', confidence: '0.70' }, confidence: '0.70',
    preselected: false, proposed_amount: '6000', proposed_unit: 'ml', proposed_price_cents: 498,
    alternatives: [{ product_id: 12, name: 'Leche semidesnatada Hacendado', confidence: '0.70' }],
    notes: ['assumed_one_pack'],
  });
  const bag = receiptLine(3, 'BOLSA PLASTICO', 5, { status: 'unmatched' });
  const yogurt = receiptLine(4, 'YOGUR NAT.', 105, {
    product: { product_id: 13, name: 'Yogur natural Hacendado', confidence: '0.91' }, confidence: '0.91',
    preselected: true, notes: ['unknown_pack_size'], proposed_price_cents: 105,
  });
  return {
    id: 5, status: 'pending_review', store_id: 'mercadona', store_text: 'MERCADONA S.A.', purchased_on: '2026-11-12',
    total_cents: 723, lines_total_cents: 723, total_matches: true, issues: [], skipped: [], has_image: true,
    lines: [rice, milk, bag, yogurt], ...extra,
  } as Schemas['ReceiptOut'];
}
