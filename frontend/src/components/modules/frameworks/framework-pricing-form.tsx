"use client";

/**
 * Organization Framework pricing control.
 *
 * Keeps commercial pricing separate from grant-level metadata editing and
 * writes through the admin-only Framework API pricing operation.
 */
import { useState } from "react";

import type { FrameworkApi } from "@/lib/frameworks/framework-api";
import type {
  FrameworkResponse,
  PricingConfig_Input,
} from "@/lib/generated/types.gen";

/**
 * Whether a price field holds an explicit zero.
 *
 * Blank is excluded deliberately: an empty organization price means "reuse the
 * base price", which is not the same as giving the tier away, and `Number("")`
 * is 0.
 *
 * @param value - Raw price field contents.
 */
function isZero(value: string): boolean {
  return value.trim() !== "" && Number(value) === 0;
}

const LICENSE_TYPES = [
  ["single_user", "Single user"],
  // Team and Enterprise tiers are not offered yet — only single-user and
  // organization licenses are sold. Re-enable when those tiers ship.
  // ["team", "Team"],
  ["organizational", "Organization"],
  // ["enterprise", "Enterprise"],
] as const;

type FrameworkPricingFormProps = {
  api: FrameworkApi;
  framework: FrameworkResponse;
  onUpdated: (framework: FrameworkResponse) => void;
};

/** Render the admin-only pricing editor for an organization Framework. */
export function FrameworkPricingForm({
  api,
  framework,
  onUpdated,
}: FrameworkPricingFormProps) {
  const [price, setPrice] = useState(framework.pricing.price);
  const [orgPrice, setOrgPrice] = useState(framework.pricing.org_price ?? "");
  // What to put back when a free toggle is switched off, so trying the toggle
  // does not discard an amount that was already typed.
  const [lastPaidPrice, setLastPaidPrice] = useState(
    isZero(framework.pricing.price) ? "" : framework.pricing.price,
  );
  const [lastPaidOrgPrice, setLastPaidOrgPrice] = useState(
    isZero(framework.pricing.org_price ?? "")
      ? ""
      : (framework.pricing.org_price ?? ""),
  );
  const [licenseTypes, setLicenseTypes] = useState<
    PricingConfig_Input["license_types"]
  >([...framework.pricing.license_types]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only offer a save when the form differs from the saved pricing, so a
  // no-op click can never fire a needless write. License order is irrelevant,
  // so compare as sets.
  const savedLicenseTypes = framework.pricing.license_types;
  const licenseTypesChanged =
    licenseTypes.length !== savedLicenseTypes.length ||
    licenseTypes.some((type) => !savedLicenseTypes.includes(type));
  const isDirty =
    price !== framework.pricing.price ||
    orgPrice !== (framework.pricing.org_price ?? "") ||
    licenseTypesChanged;

  const isFree = isZero(price);
  // An empty organization price means "reuse the base price", which is not the
  // same as an explicit zero, so blank must never read as a free org tier.
  const isOrgFree = isZero(orgPrice);
  const offersOrgTier = licenseTypes.includes("organizational");

  function toggleFree(next: boolean) {
    if (next) {
      setLastPaidPrice(price);
      setPrice("0.00");
      return;
    }
    setPrice(lastPaidPrice);
  }

  function toggleOrgFree(next: boolean) {
    if (next) {
      setLastPaidOrgPrice(orgPrice);
      setOrgPrice("0.00");
      return;
    }
    setOrgPrice(lastPaidOrgPrice);
  }

  function toggleLicenseType(
    value: PricingConfig_Input["license_types"][number],
  ) {
    setLicenseTypes((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  }

  async function savePricing() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updatePricing(framework.id, {
        pricing: {
          commercial_rights: framework.pricing.commercial_rights,
          currency: framework.pricing.currency,
          license_types: licenseTypes,
          org_price: orgPrice.trim() || null,
          price,
          usage_restrictions: framework.pricing.usage_restrictions,
        },
      });
      onUpdated(updated);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Pricing could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <h2 className="font-heading text-lg font-bold text-foreground">Pricing</h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Set the organization&apos;s marketplace license prices.
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <label className="text-sm font-semibold text-foreground">
            Base price
            <input
              className="mt-1.5 min-h-12 w-full rounded-xl border border-border-default bg-background px-4 text-sm font-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
              disabled={isFree}
              inputMode="decimal"
              onChange={(event) => setPrice(event.target.value)}
              value={price}
            />
          </label>
          <label className="flex min-h-12 items-center gap-3 rounded-xl border border-border-default bg-background px-3 text-sm font-normal text-foreground">
            <input
              checked={isFree}
              className="accent-accent"
              onChange={(event) => toggleFree(event.target.checked)}
              type="checkbox"
            />
            Offer this Framework free
          </label>
        </div>
        <div className="grid gap-2">
          <label className="text-sm font-semibold text-foreground">
            Organization price
            <input
              className="mt-1.5 min-h-12 w-full rounded-xl border border-border-default bg-background px-4 text-sm font-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
              disabled={isOrgFree}
              inputMode="decimal"
              onChange={(event) => setOrgPrice(event.target.value)}
              placeholder="Same as base price"
              value={orgPrice}
            />
          </label>
          {offersOrgTier ? (
            <label className="flex min-h-12 items-center gap-3 rounded-xl border border-border-default bg-background px-3 text-sm font-normal text-foreground">
              <input
                checked={isOrgFree}
                className="accent-accent"
                onChange={(event) => toggleOrgFree(event.target.checked)}
                type="checkbox"
              />
              Organization tier is free
            </label>
          ) : null}
        </div>
      </div>
      <fieldset className="mt-4 grid gap-2 sm:grid-cols-2">
        <legend className="mb-1 text-sm font-semibold text-foreground">
          License types
        </legend>
        {LICENSE_TYPES.map(([value, label]) => (
          <label
            className="flex min-h-12 items-center gap-3 rounded-xl border border-border-default bg-background px-3 text-sm text-foreground"
            key={value}
          >
            <input
              checked={licenseTypes.includes(value)}
              className="accent-accent"
              onChange={() => toggleLicenseType(value)}
              type="checkbox"
            />
            {label}
          </label>
        ))}
      </fieldset>
      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
      <button
        className="mt-4 min-h-12 rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90 disabled:opacity-60"
        disabled={
          saving || !isDirty || !price.trim() || licenseTypes.length === 0
        }
        onClick={savePricing}
        type="button"
      >
        {saving ? "Saving pricing" : "Save pricing"}
      </button>
    </section>
  );
}
