/**
 * Contributor dashboard index.
 *
 * `/dashboard` is the contributor role-landing path but has no overview screen
 * of its own yet, so it redirects to the Frameworks workspace — the contributor
 * home surfaced in the authenticated navigation.
 */
import { redirect } from "next/navigation";

/**
 * Redirect the bare dashboard route to the contributor Frameworks workspace.
 */
export default function DashboardIndexPage(): never {
  redirect("/dashboard/frameworks");
}
