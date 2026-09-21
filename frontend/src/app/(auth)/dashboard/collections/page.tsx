/**
 * Contributor Collection dashboard route.
 *
 * Collections became a tab of the Frameworks workspace, since a Collection is
 * a bundle of Frameworks. This route stays so existing links and bookmarks
 * keep working, and sends them to that tab rather than rendering a second
 * copy of the builder.
 */
import { redirect } from "next/navigation";

/**
 * Redirect to the Collections tab of the Contributor workspace.
 */
export default function ContributorCollectionsPage() {
  redirect("/dashboard/frameworks?tab=collections");
}
