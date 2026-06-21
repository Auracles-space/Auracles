/**
 * Legacy Attestor application route.
 *
 * The application flow moved to `/settings/attestor` (outside the role-gated
 * `/attestor/*` area so applicants without an approved role can reach it). This
 * route now redirects to preserve any existing links and bookmarks.
 */
import { redirect } from "next/navigation";

/**
 * Redirect the old attestor application path to its new settings home.
 */
export default function AttestorApplicationsPage() {
  redirect("/settings/attestor");
}
