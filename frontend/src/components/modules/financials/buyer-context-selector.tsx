"use client";

/**
 * "Buy as" selector for Framework checkout.
 *
 * Lets an Operator purchase for themselves or on behalf of an organization
 * they administer. Rendered only when at least one eligible org exists.
 */
import type { BuyerOption } from "@/lib/marketplace/purchase-context";

type BuyerContextSelectorProps = {
  options: BuyerOption[];
  value: BuyerOption;
  onChange: (buyer: BuyerOption) => void;
};

function keyFor(option: BuyerOption): string {
  return option.kind === "self" ? "self" : `org:${option.orgId}`;
}

/**
 * Render a radio group of purchase identities.
 *
 * @param props - Available buyer options, current value, and change handler.
 */
export function BuyerContextSelector({ options, value, onChange }: BuyerContextSelectorProps) {
  return (
    <fieldset className="mt-6 grid gap-3">
      <legend className="text-sm font-semibold text-foreground">Purchase as</legend>
      {options.map((option) => {
        const selected = keyFor(option) === keyFor(value);
        return (
          <label
            key={keyFor(option)}
            className={[
              "flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl border p-4 transition-colors",
              selected
                ? "border-accent bg-accent/5 ring-1 ring-accent"
                : "border-border-default bg-surface-1 hover:border-border-strong hover:bg-surface-2",
            ].join(" ")}
          >
            <input
              type="radio"
              name="buyer-context"
              className="h-4 w-4"
              checked={selected}
              onChange={() => onChange(option)}
              aria-label={option.label}
            />
            <span className="text-sm font-medium text-foreground">{option.label}</span>
          </label>
        );
      })}
    </fieldset>
  );
}
