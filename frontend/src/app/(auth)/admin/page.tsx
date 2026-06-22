/**
 * Admin index route.
 *
 * The role landing path for admins is `/admin`, but the admin surface is split
 * into sections (analytics, users, disputes, configuration, …). Redirect the
 * bare `/admin` entry to the analytics dashboard so the landing never 404s.
 */
import { redirect } from "next/navigation";

/**
 * Redirect the bare admin route to the default admin section.
 */
export default function AdminIndexPage() {
  redirect("/admin/analytics");
}
