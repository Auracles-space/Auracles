/**
 * Contributor workspace tab-shell tests.
 *
 * Collections stopped being a nav destination and became a tab beside
 * Frameworks, so these cover the shell: which panel opens, deep-linking, and
 * that the framework-only action does not follow you into Collections.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContributorWorkspace } from "@/components/modules/frameworks/contributor-workspace";

const searchParams = { value: new URLSearchParams() };
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard/frameworks",
  useRouter: () => ({ replace }),
  useSearchParams: () => searchParams.value,
}));

vi.mock("@/components/modules/frameworks/framework-list", () => ({
  FrameworkList: () => <div>framework list panel</div>,
}));

vi.mock("@/components/modules/collections/collection-builder", () => ({
  CollectionBuilder: () => <div>collection builder panel</div>,
}));

describe("ContributorWorkspace", () => {
  beforeEach(() => {
    replace.mockReset();
    searchParams.value = new URLSearchParams();
  });

  it("opens on Frameworks when no tab is requested", () => {
    render(<ContributorWorkspace />);

    expect(screen.getByText("framework list panel")).toBeInTheDocument();
    expect(screen.queryByText("collection builder panel")).not.toBeInTheDocument();
  });

  it("opens on Collections when the URL asks for it", () => {
    // The old /dashboard/collections route redirects here, so this is the
    // path every existing Collections link now takes.
    searchParams.value = new URLSearchParams("tab=collections");

    render(<ContributorWorkspace />);

    expect(screen.getByText("collection builder panel")).toBeInTheDocument();
    expect(screen.queryByText("framework list panel")).not.toBeInTheDocument();
  });

  it("puts the chosen tab in the URL so the panel can be linked to", () => {
    render(<ContributorWorkspace />);

    fireEvent.click(screen.getByRole("tab", { name: /collections/i }));

    expect(replace).toHaveBeenCalledWith(
      "/dashboard/frameworks?tab=collections",
      { scroll: false },
    );
    expect(screen.getByText("collection builder panel")).toBeInTheDocument();
  });

  it("hides Create framework while Collections is open", () => {
    // The action builds a Framework, not a Collection; leaving it visible on
    // the Collections panel offers the wrong verb for what is on screen.
    render(<ContributorWorkspace />);
    expect(screen.getByRole("link", { name: /create framework/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /collections/i }));

    expect(screen.queryByRole("link", { name: /create framework/i })).not.toBeInTheDocument();
  });
});
