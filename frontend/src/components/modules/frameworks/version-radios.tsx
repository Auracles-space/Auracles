"use client";

/**
 * Framework version change-type radios.
 *
 * Used when creating a new draft version from a published Framework.
 */
type VersionRadiosProps = {
  onChange: (value: "fix" | "improvement" | "major") => void;
  value: "fix" | "improvement" | "major";
};

const options = [
  { label: "Fix", value: "fix" },
  { label: "Improvement", value: "improvement" },
  { label: "Major", value: "major" },
] as const;

/**
 * Render version change-type choices.
 *
 * @param props - Current value and change handler.
 */
export function VersionRadios({ onChange, value }: VersionRadiosProps) {
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-2 text-sm font-semibold text-foreground">
        Version change type
      </legend>
      {options.map((option) => (
        <label
          className="flex min-h-11 items-center gap-3 rounded-[6px] border border-border-default bg-surface-2 px-3 text-sm text-foreground"
          key={option.value}
        >
          <input
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            type="radio"
          />
          {option.label}
        </label>
      ))}
    </fieldset>
  );
}
