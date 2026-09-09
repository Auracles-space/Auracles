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
 * How every money amount on this platform writes its currency.
 *
 * CLDR's default (`"symbol"`) resolves NGN to the literal string "NGN" in
 * every locale except en-NG, so the pilot's own currency reads as an ISO code
 * on charts, ledgers and price tags — "NGN 350" where a Nigerian reader
 * expects "₦350". `"narrowSymbol"` resolves it to ₦ and leaves $, £ and €
 * exactly as they were.
 *
 * Shared rather than repeated so a money formatter can never quietly disagree
 * with the others about how the currency is written.
 */
export const CURRENCY_DISPLAY = "narrowSymbol" as const;

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
  try {
    const parts = new Intl.NumberFormat("en-US", {
      currency,
      currencyDisplay: CURRENCY_DISPLAY,
      style: "currency",
    }).formatToParts(0);
    return parts.find((part) => part.type === "currency")?.value ?? currency;
  } catch {
    // An unknown code, or an engine without narrow-symbol support, must not
    // take down the form this label sits in.
    return currency;
  }
}

/** Payment rails a payout account can settle on. */
export type PayoutProvider = "paystack" | "stripe";

/**
 * Return the rail a payout account in `country` settles on.
 *
 * Mirrors `select_provider` in backend/app/integrations/payment_router.py. The
 * backend is authoritative and rejects a provider that disagrees with its own
 * routing, so this exists only to send the right one and ask for the right
 * fields — not to make the decision.
 *
 * Note the currency arm: on an NGN deployment every country settles through
 * Paystack, because Stripe cannot pay out naira at all. Deciding from country
 * alone would send "stripe" for a non-NG account and earn a 422.
 *
 * @param country - ISO 3166-1 alpha-2 country of the payout account.
 * @returns The provider that settles that country on this deployment.
 */
export function payoutProviderForCountry(country: string): PayoutProvider {
  if (country.toUpperCase() === "NG") {
    return "paystack";
  }
  if (PLATFORM_CURRENCY.toUpperCase() === "NGN") {
    return "paystack";
  }
  return "stripe";
}
