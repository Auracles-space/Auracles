/**
 * Authenticated admin moderation route.
 */
import { AdminFrameworkDirectoryPanel } from "@/components/modules/admin/admin-framework-directory-panel";
import { AdminModerationPanel } from "@/components/modules/admin/admin-moderation-panel";
import { AdminSuspendedFrameworksPanel } from "@/components/modules/admin/admin-suspended-frameworks-panel";

/**
 * Render the admin moderation queue plus Framework delist and relist controls.
 */
export default function AdminModerationPage() {
  return (
    <div className="space-y-6">
      <AdminModerationPanel />
      <AdminFrameworkDirectoryPanel />
      <AdminSuspendedFrameworksPanel />
    </div>
  );
}
