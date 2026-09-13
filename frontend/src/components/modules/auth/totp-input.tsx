"use client";

import { useId } from "react";

/**
 * Controlled TOTP code input.
 *
 * Filters user input down to the six numeric characters accepted by the TOTP
 * login and setup endpoints while preserving a normal text-input experience.
 */
type TotpInputProps = {
  label?: string;
  onChange: (value: string) => void;
  value: string;
  /** Focus the field on mount (dialogs). */
  autoFocus?: boolean;
};

/**
 * Render a six-digit authenticator code input.
 *
 * @param props - Current value, change callback, and optional label.
 */
export function TotpInput({
  label = "Authenticator code",
  onChange,
  value,
  autoFocus = false,
}: TotpInputProps) {
  // Unique per instance: the step-up dialog can render beside the 2FA setup
  // form, and two inputs sharing one id would break their labels.
  const id = useId();
  return (
    <label className="block" htmlFor={id}>
      <span className="text-sm font-medium text-foreground">{label}</span>
      <input
        autoComplete="one-time-code"
        autoFocus={autoFocus}
        className="mt-2 min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-center font-heading text-lg font-semibold tracking-[0.05em] text-foreground outline-none transition-colors placeholder:text-foreground-subtle focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent"
        id={id}
        inputMode="numeric"
        maxLength={6}
        onChange={(event) => {
          onChange(event.target.value.replace(/\D/g, "").slice(0, 6));
        }}
        pattern="[0-9]*"
        placeholder="000000"
        type="text"
        value={value}
      />
    </label>
  );
}
