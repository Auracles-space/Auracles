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
        className="mt-2 min-h-11 w-full rounded-control border border-border-strong bg-surface-3 px-3 py-2 text-sm text-foreground outline-none transition placeholder:text-foreground-subtle focus:border-brand focus:ring-2 focus:ring-brand/15"
        id="backup-code"
        onChange={(event) => onChange(event.target.value.trim())}
        placeholder="Enter one recovery code"
        type="text"
        value={value}
      />
    </label>
  );
}
