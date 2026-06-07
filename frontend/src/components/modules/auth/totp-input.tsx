"use client";

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
}: TotpInputProps) {
  return (
    <label className="block" htmlFor="totp-code">
      <span className="text-sm font-medium text-foreground">{label}</span>
      <input
        autoComplete="one-time-code"
        className="mt-2 min-h-12 w-full rounded-control border border-border-strong bg-surface-2 px-4 py-2 text-center font-heading text-lg font-semibold tracking-[0.05em] text-foreground outline-none transition placeholder:text-foreground-subtle focus:border-accent focus:ring-2 focus:ring-accent/15"
        id="totp-code"
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
