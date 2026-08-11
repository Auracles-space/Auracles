"use client";

/**
 * Backup code input for TOTP recovery.
 *
 * Backup codes may contain separators, so this component avoids numeric-only
 * filtering while still applying the shared auth form styling.
 */
type BackupCodeInputProps = {
  onChange: (value: string) => void;
  value: string;
};

/**
 * Render a recovery-code input for 2FA login fallback.
 *
 * @param props - Current value and change callback.
 */
export function BackupCodeInput({ onChange, value }: BackupCodeInputProps) {
  return (
    <label className="block" htmlFor="backup-code">
      <span className="text-sm font-medium text-foreground">Backup code</span>
      <input
        autoComplete="one-time-code"
        className="mt-2 min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-subtle focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent"
        id="backup-code"
        onChange={(event) => onChange(event.target.value.trim())}
        placeholder="Enter one recovery code"
        type="text"
        value={value}
      />
    </label>
  );
}
