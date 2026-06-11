/**
 * Developer platform dashboard route.
 *
 * Hosts the Partner Developer workspace for application status, API keys,
 * webhooks, analytics, and partner payout operations.
 */
import { DeveloperPortal } from "@/components/modules/developer/developer-portal";

/**
 * Render the Developer platform workspace inside the authenticated shell.
 */
export default function DeveloperDashboardPage() {
  return <DeveloperPortal />;
}
