/**
 * Small form field primitive for auth module forms.
 *
 * This is module-local rather than `components/ui` because it includes form
 * layout conventions specific to auth and settings flows.
 */
import { useState } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";

type FormFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "error"> & {
  helper?: ReactNode;
  label: string;
  isValid?: boolean;
  error?: ReactNode;
};

/**
 * Render a labelled input using Auracles control tokens.
 *
 * @param props - Input props plus label, optional helper, and an optional
 *   validation error message shown beneath the field.
 */
export function FormField({
  error,
  helper,
  id,
  label,
  isValid,
  type,
  ...props
}: FormFieldProps) {
  const inputId = id ?? props.name ?? label.toLowerCase().replace(/\s+/g, "-");
  const [showPassword, setShowPassword] = useState(false);

  const inputType = type === "password" ? (showPassword ? "text" : "password") : type;

  return (
    <label className="block" htmlFor={inputId}>
      <span className="flex items-center gap-1.5 text-sm font-medium text-foreground">
        {label}
        {isValid && (
          <svg className="h-4 w-4 text-success shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" data-testid="checkmark">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
          </svg>
        )}
      </span>
      <div className="relative mt-2">
        <input
          className={`min-h-12 w-full rounded-xl border bg-surface-2 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-subtle focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent ${
            error ? "border-error focus-visible:border-error focus-visible:ring-error" : "border-border-default"
          } ${type === "password" ? "pl-4 pr-12" : "px-4"}`}
          aria-invalid={error ? true : undefined}
          id={inputId}
          type={inputType}
          {...props}
        />
        {type === "password" && (
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-3 top-1/2 -translate-y-1/2 flex h-8 w-8 items-center justify-center rounded-lg text-foreground-muted hover:bg-black/5 dark:hover:bg-white/5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
            aria-label={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? (
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
              </svg>
            ) : (
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            )}
          </button>
        )}
      </div>
      {error ? (
        <span className="mt-2 block text-xs leading-5 text-error" role="alert">
          {error}
        </span>
      ) : helper ? (
        <span className="mt-2 block text-xs leading-5 text-foreground-muted">
          {helper}
        </span>
      ) : null}
    </label>
  );
}
