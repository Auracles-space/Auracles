/**
 * Authenticated admin calibration-fixtures management route.
 */
import { Metadata } from "next";

import { AdminCalibrationFixturesPanel } from "@/components/modules/admin/admin-calibration-fixtures-panel";

export const metadata: Metadata = {
  title: "Admin - Calibration Fixtures",
};

export default function AdminCalibrationFixturesPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <AdminCalibrationFixturesPanel />
    </div>
  );
}
