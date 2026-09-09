/**
 * Marketplace formatting helpers.
 *
 * Keeps money, byte sizes, and labels consistent across Explore, Contributor
 * dashboards, and Operator library screens.
 */

import { PLATFORM_CURRENCY } from "@/lib/marketplace/currency";

/**
 * Format a decimal money string from the API for display.
 *
 * Some figures — admin GMV, developer commission totals — arrive as bare
 * decimal strings with no currency field beside them, because the platform
 * settles in exactly one currency. Those callers omit `currency`, so the
 * default has to be the settlement currency: defaulting to USD printed dollar
 * signs over naira amounts.
 *
 * @param price - Decimal string returned by the backend.
 * @param currency - ISO currency code; defaults to the settlement currency.
 * @returns Compact marketplace price label.
 */
export function formatMoney(
  price: string,
  currency = PLATFORM_CURRENCY,
): string {
  const amount = Number(price);
  if (!Number.isFinite(amount)) {
    return `${currency} ${price}`;
  }
  return new Intl.NumberFormat("en-US", {
    currency,
    maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
    style: "currency",
  }).format(amount);
}

/**
 * Convert an API enum/string into readable title case.
 *
 * @param value - Raw enum value such as `single_user`.
 * @returns Human-readable label.
 */
export function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/**
 * Plain-language labels for the Framework workflow status enum.
 *
 * Keeps internal pipeline jargon (pipeline_passed, pipeline_failed) out of the
 * contributor UI. Unknown values fall back to {@link formatLabel} title-casing.
 */
const FRAMEWORK_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  processing: "Checking…",
  submitted: "Submitted",
  pipeline_passed: "Ready to publish",
  pipeline_failed: "Checks failed",
  published: "Published",
  unpublished: "Unpublished",
};

/**
 * Format a Framework workflow status for display to contributors.
 *
 * @param value - Raw status enum from the backend.
 * @returns Plain-language status label.
 */
export function formatFrameworkStatus(value: string | null | undefined): string {
  if (value && value in FRAMEWORK_STATUS_LABELS) {
    return FRAMEWORK_STATUS_LABELS[value];
  }
  return formatLabel(value);
}

/**
 * Format a file size in bytes.
 *
 * @param bytes - File size in bytes.
 * @returns Human-readable byte label.
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}
