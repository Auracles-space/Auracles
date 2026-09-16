/**
 * Helpers for the admin Treasury page.
 *
 * Treasury statements are cut by calendar month in Lagos time (treasury
 * decision 11), so the month picker is built in that zone rather than the
 * admin's browser zone.
 *
 * Maps to: docs/superpowers/specs/2026-09-15-platform-treasury-design.md §Frontend.
 */

const LAGOS_TIME_ZONE = "Africa/Lagos";

/**
 * List the most recent statement months, newest first, in Lagos time.
 *
 * @param now - The current moment.
 * @param count - How many months to list.
 * @returns Month keys in `YYYY-MM` form.
 */
export function recentStatementMonths(now: Date, count = 12): string[] {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: LAGOS_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
  }).formatToParts(now);
  let year = Number(parts.find((part) => part.type === "year")?.value);
  let month = Number(parts.find((part) => part.type === "month")?.value);
  const months: string[] = [];
  for (let index = 0; index < count; index += 1) {
    months.push(`${year}-${String(month).padStart(2, "0")}`);
    month -= 1;
    if (month === 0) {
      month = 12;
      year -= 1;
    }
  }
  return months;
}

/**
 * Return whether an API decimal string is below zero.
 *
 * @param amount - Decimal string such as "-6750.00", or null.
 */
export function isNegativeAmount(amount: string | null | undefined): boolean {
  return amount != null && Number(amount) < 0;
}

/**
 * Return whether the platform bank account is still inside its 24-hour hold.
 *
 * @param account - The account, or null when none is set.
 * @param now - The current moment.
 */
export function bankAccountOnHold(
  account: { usable_from: string } | null | undefined,
  now: Date,
): boolean {
  return account != null && new Date(account.usable_from).getTime() > now.getTime();
}

/**
 * Format the time left on a hold for a live countdown.
 *
 * Long waits read as hours and minutes; the last hour counts seconds so the
 * admin can see it moving.
 *
 * @param milliseconds - Time remaining; negative values read as zero.
 */
export function formatCountdown(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}
