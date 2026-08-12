/**
 * Platform settlement currency for display.
 *
 * Auracles trades in exactly one currency, chosen server-side by
 * `PLATFORM_CURRENCY` (see backend/app/core/currency.py). The browser cannot
 * read that setting, so it is mirrored here as a public build-time value used
 * purely for labelling inputs — the server remains the authority and rejects
 * any amount submitted in another currency.
 *
 * Defaults to NGN to match the backend default, so a missing env var shows the
 * pilot currency rather than silently labelling naira as dollars.
 */

/** ISO 4217 code every price on this deployment is denominated in. */
export const PLATFORM_CURRENCY =
  process.env.NEXT_PUBLIC_PLATFORM_CURRENCY ?? "NGN";

/**
 * Return the currency symbol for a code, for use as an input adornment.
 *
 * Derived through `Intl` rather than a hand-kept map so a new currency needs
 * no code change. Falls back to the code itself when the runtime has no
 * symbol for it, which reads correctly ("NGN 250") even if it is not pretty.
 *
 * @param currency - ISO 4217 currency code.
 * @returns The symbol (e.g. `₦`, `$`), or the code when none is available.
 */
export function currencySymbol(currency: string = PLATFORM_CURRENCY): string {
  const parts = new Intl.NumberFormat("en-US", {
    currency,
    style: "currency",
  }).formatToParts(0);
  return parts.find((part) => part.type === "currency")?.value ?? currency;
}
