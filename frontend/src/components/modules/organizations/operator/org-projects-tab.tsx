"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ProjectCreateForm } from "@/components/modules/projects/project-create-form";
import { ProjectListShell } from "@/components/modules/projects/project-list-shell";
import { Tabs, tabId, tabPanelId } from "@/components/ui/tabs";

export function OrgProjectsTab({ orgId }: { orgId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const activeTab = searchParams.get("view") ?? "posted";

  function selectTab(id: string): void {
    const params = new URLSearchParams(searchParams.toString());
    params.set("view", id);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-2xl font-semibold text-foreground">
          Projects
        </h2>
      </div>

      <Tabs
        activeId={activeTab}
        label="Organization Projects"
        tabs={[
          { id: "posted", label: "Posted Projects" },
          { id: "create", label: "Create New" },
        ]}
        onChange={selectTab}
      />

      <div
        id={tabPanelId("posted")}
        role="tabpanel"
        aria-labelledby={tabId("posted")}
        hidden={activeTab !== "posted"}
      >
        {activeTab === "posted" ? (
          <ProjectListShell mode={{ kind: "org", orgId }} />
        ) : null}
      </div>

      <div
        id={tabPanelId("create")}
        role="tabpanel"
        aria-labelledby={tabId("create")}
        hidden={activeTab !== "create"}
      >
        {activeTab === "create" ? (
          <div className="mx-auto max-w-2xl">
            <ProjectCreateForm mode={{ kind: "org", orgId }} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
