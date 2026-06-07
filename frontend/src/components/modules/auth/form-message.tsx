/**
 * Status copy for auth forms.
 *
 * Uses semantic color tokens only for real success/error states.
 */
type FormMessageProps = {
  kind: "error" | "success";
  message: string;
};

/**
 * Render a form status message with accessible live-region semantics.
 *
 * @param props - Status kind and safe user-facing message.
 */
export function FormMessage({ kind, message }: FormMessageProps) {
  const isError = kind === "error";

  return (
    <p
      className={[
        "rounded-control border px-3 py-2 text-sm leading-6",
        isError
          ? "border-error/30 bg-error/10 text-error"
          : "border-success/30 bg-success/10 text-success",
      ].join(" ")}
      role={isError ? "alert" : "status"}
    >
      {message}
    </p>
  );
}
