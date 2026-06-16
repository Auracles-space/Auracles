/**
 * Pure client-side form validators.
 *
 * Used to gate submit buttons so they only become active once required fields
 * are filled correctly. Backend Pydantic validation remains the authority;
 * these helpers are UX guards, not the security boundary.
 */

/** True when the trimmed string has at least one character. */
export function isNonEmpty(value: string): boolean {
  return value.trim().length > 0;
}

/** True when the value looks like a syntactically valid email address. */
export function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

/** True when the string meets the platform minimum password length (12). */
export function isPasswordLongEnough(value: string): boolean {
  return value.length >= 12;
}

/** True when the value parses as an http(s) URL. */
export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

/** True when the trimmed string length is within [min, max]. */
export function isLengthBetween(value: string, min: number, max: number): boolean {
  const length = value.trim().length;
  return length >= min && length <= max;
}

/** True when the value is a finite number greater than zero. */
export function isPositiveNumber(value: string | number): boolean {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0;
}

/** True when every provided field passes its own validity check. */
export function allValid(...checks: boolean[]): boolean {
  return checks.every(Boolean);
}
