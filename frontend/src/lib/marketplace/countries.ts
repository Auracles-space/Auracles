/**
 * Country lists for payout onboarding and checkout.
 *
 * Three questions need three lists. `STRIPE_CONNECT_COUNTRIES` is bounded by
 * Stripe Connect and is only about that rail — it is deliberately NOT the
 * registration list, because Nigeria is not a Connect country and the pilot
 * market could not have registered at all.
 * `CHECKOUT_COUNTRIES` answers "where is this buyer paying from", which routes
 * the charge. `PAYOUT_COUNTRIES` answers "where can we pay someone out", which
 * spans both rails — Connect for its own countries, Paystack for Nigeria — and
 * is what organization registration uses: an org that sells has to be payable.
 *
 * Codes are the value; names are display-only. Kept sorted by name so the
 * rendered dropdown reads alphabetically.
 */
export type CountryOption = {
  /** ISO 3166-1 alpha-2 code, uppercase. Stored and sent to the API. */
  code: string;
  /** Human-readable country name for display. */
  name: string;
};

/**
 * Countries where Stripe Connect can create a payout account.
 *
 * Authoritative for organization registration (`country`). Nigeria (NG) is
 * intentionally absent: Connect does not support Nigerian payout accounts.
 * Contributor payout onboarding uses `PAYOUT_COUNTRIES`, which adds Nigeria
 * on the Paystack rail.
 *
 * Source: https://stripe.com/global — cross-border payouts availability.
 */
export const STRIPE_CONNECT_COUNTRIES = [
  { code: "AU", name: "Australia" },
  { code: "AT", name: "Austria" },
  { code: "BE", name: "Belgium" },
  { code: "BR", name: "Brazil" },
  { code: "BG", name: "Bulgaria" },
  { code: "CA", name: "Canada" },
  { code: "HR", name: "Croatia" },
  { code: "CY", name: "Cyprus" },
  { code: "CZ", name: "Czechia" },
  { code: "DK", name: "Denmark" },
  { code: "EE", name: "Estonia" },
  { code: "FI", name: "Finland" },
  { code: "FR", name: "France" },
  { code: "DE", name: "Germany" },
  { code: "GI", name: "Gibraltar" },
  { code: "GR", name: "Greece" },
  { code: "HK", name: "Hong Kong" },
  { code: "HU", name: "Hungary" },
  { code: "IE", name: "Ireland" },
  { code: "IT", name: "Italy" },
  { code: "JP", name: "Japan" },
  { code: "LV", name: "Latvia" },
  { code: "LI", name: "Liechtenstein" },
  { code: "LT", name: "Lithuania" },
  { code: "LU", name: "Luxembourg" },
  { code: "MY", name: "Malaysia" },
  { code: "MT", name: "Malta" },
  { code: "MX", name: "Mexico" },
  { code: "NL", name: "Netherlands" },
  { code: "NZ", name: "New Zealand" },
  { code: "NO", name: "Norway" },
  { code: "PL", name: "Poland" },
  { code: "PT", name: "Portugal" },
  { code: "RO", name: "Romania" },
  { code: "SG", name: "Singapore" },
  { code: "SK", name: "Slovakia" },
  { code: "SI", name: "Slovenia" },
  { code: "ES", name: "Spain" },
  { code: "SE", name: "Sweden" },
  { code: "CH", name: "Switzerland" },
  { code: "TH", name: "Thailand" },
  { code: "AE", name: "United Arab Emirates" },
  { code: "GB", name: "United Kingdom" },
  { code: "US", name: "United States" },
] as const satisfies readonly CountryOption[];

/**
 * Countries a buyer can declare at checkout, used to pick the payment rail.
 *
 * Broader than the payout list: it adds Nigeria, whose charges settle on
 * Paystack. The field is optional on the API, so a buyer whose country is not
 * listed simply sends nothing and settles on the default (Stripe) rail —
 * which is where they would have landed anyway.
 */
export const CHECKOUT_COUNTRIES: readonly CountryOption[] = [
  ...STRIPE_CONNECT_COUNTRIES,
  { code: "NG", name: "Nigeria" },
].sort((a, b) => a.name.localeCompare(b.name));

/**
 * Countries a Contributor can register a payout account in.
 *
 * Spans both rails — Stripe Connect for its own countries, Paystack for
 * Nigerian NUBAN accounts. The backend decides which rail a country settles on
 * and rejects a mismatch, so this list only governs what is offered.
 */
export const PAYOUT_COUNTRIES: readonly CountryOption[] = [
  ...STRIPE_CONNECT_COUNTRIES,
  { code: "NG", name: "Nigeria" },
].sort((a, b) => a.name.localeCompare(b.name));

/** Countries whose payout accounts settle on the Paystack rail. */
export const PAYSTACK_PAYOUT_COUNTRIES: readonly string[] = ["NG"];

/**
 * Best initial guess at the payer's billing country, from the browser locale.
 *
 * Only a default — the payer can always change it, and the value is what picks
 * the payment rail, so every surface renders it visibly rather than inferring
 * it silently. Shared by checkout and the escrow funding surfaces.
 */
export function defaultBillingCountry(): string {
  if (typeof navigator === "undefined") {
    return "US";
  }
  const region = new Intl.Locale(navigator.language).maximize().region;
  return CHECKOUT_COUNTRIES.some((c) => c.code === region) ? (region ?? "US") : "US";
}
