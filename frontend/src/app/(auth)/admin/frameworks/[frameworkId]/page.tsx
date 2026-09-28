/**
 * Authenticated admin Framework detail route.
 *
 * The only admin surface on which a Framework held by the processing pipeline
 * appears: it is not published, so it is absent from the Framework directory
 * and the suspended list alike.
 */
import { AdminFrameworkDetail } from "@/components/modules/admin/admin-framework-detail";

export const metadata = {
  title: "Framework - Admin",
};

type AdminFrameworkDetailPageProps = {
  params: Promise<{ frameworkId: string }>;
};

/**
 * Render the detail view for one Framework.
 *
 * @param props - Route params carrying the Framework id.
 */
export default async function AdminFrameworkDetailPage({
  params,
}: AdminFrameworkDetailPageProps) {
  const { frameworkId } = await params;
  return <AdminFrameworkDetail frameworkId={frameworkId} />;
}
