// SPDX-License-Identifier: AGPL-3.0-or-later

/** Every API failure, in the server's single error format ({error: {code, message, details}}). */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function errorFromBody(status: number, body: unknown): ApiError {
  const inner = (body as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
  if (inner && typeof inner.code === 'string') {
    return new ApiError(status, inner.code, inner.message ?? inner.code, inner.details);
  }
  return new ApiError(status, 'http_error', `HTTP ${status}`);
}

/** Field problems of a ``validation_error``: {field: message}. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) return {};
  const out: Record<string, string> = {};
  for (const item of error.details as { field?: string; message?: string }[]) {
    if (item.field) out[item.field] = item.message ?? '';
  }
  return out;
}
