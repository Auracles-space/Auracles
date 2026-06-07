/**
 * Small form field primitive for auth module forms.
 *
 * This is module-local rather than `components/ui` because it includes form
 * layout conventions specific to auth and settings flows.
 */
import type { InputHTMLAttributes, ReactNode } from "react";

type FormFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  helper?: ReactNode;
  label: string;
};

/**
 * Render a labelled input using Auracles control tokens.
 *
 * @param props - Input props plus label and optional helper content.
 */
export function FormField({ helper, id, label, ...props }: FormFieldProps) {
  const inputId = id ?? props.name ?? label.toLowerCase().replace(/\s+/g, "-");

  return (
    <label className="block" htmlFor={inputId}>
      <span className="text-sm font-medium text-foreground">{label}</span>
      <input
        className="mt-2 min-h-12 w-full rounded-control border border-border-strong bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition placeholder:text-foreground-subtle focus:border-accent focus:ring-2 focus:ring-accent/15"
        id={inputId}
        {...props}
      />
      {helper ? (
        <span className="mt-2 block text-xs leading-5 text-foreground-muted">
          {helper}
        </span>
      ) : null}
    </label>
  );
}
