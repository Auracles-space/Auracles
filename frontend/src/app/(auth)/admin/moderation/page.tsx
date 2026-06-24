/**
 * Authenticated admin moderation route.
 */
import { AdminModerationPanel } from "@/components/modules/admin/admin-moderation-panel";
import { AdminSuspendedFrameworksPanel } from "@/components/modules/admin/admin-suspended-frameworks-panel";

/**
 * Render the unified admin moderation queue and suspended-framework controls.
 */
export default function AdminModerationPage() {
  return (
    <div className="space-y-6">
      <AdminModerationPanel />
      <AdminSuspendedFrameworksPanel />
    </div>
  );
}
