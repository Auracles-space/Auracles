/**
 * Listing price label for a Framework or Collection.
 *
 * A Framework may be offered at no charge, and "Free" is a stronger signal to
 * a buyer scanning a feed than a zero amount is. Rendering it in the Accent
 * colour keeps that readable at a glance while holding the same slot and
 * typography as a priced listing, so the price column stays aligned across
 * cards in a grid.
 *
 * Maps to: FR-EXP-008, FR-FWK-014.
 */
import { formatListingPrice } from "@/lib/marketplace/format";

export type ListingPriceProps = {
  /** Decimal price string from the API. */
  price: string;
  /** ISO 4217 currency code for the listing. */
  currency?: string;
  /** Extra classes for the caller's slot, such as a smaller size in a list row. */
  className?: string;
};

/**
 * Render a listing price, or "Free" when the listing costs nothing.
 *
 * @param price - Decimal price string from the API.
 * @param currency - ISO 4217 currency code for the listing.
 * @param className - Extra classes merged onto the label.
 */
export function ListingPrice({ price, currency, className = "" }: ListingPriceProps) {
  const label = formatListingPrice(price, currency);
  const isFree = label === "Free";
  return (
    <strong
      className={[
        "font-heading font-bold",
        isFree ? "text-accent" : "text-foreground",
        className,
      ].join(" ")}
    >
      {label}
    </strong>
  );
}
