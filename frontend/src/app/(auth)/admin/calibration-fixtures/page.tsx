/**
 * Legacy admin route. Calibration fixtures are a tab of `/admin/attestors`.
 */
import { redirect } from "next/navigation";

/**
 * Redirect the old fixtures route to the attestor console's Fixtures tab.
 */
export default function AdminCalibrationFixturesPage() {
  redirect("/admin/attestors?tab=fixtures");
}
