import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FilterSidebar } from "@/components/modules/explore/filter-sidebar";

describe("FilterSidebar", () => {
  it("exposes sector, function, category, and organization filters", () => {
    render(<FilterSidebar active={{}} />);

    const sectorSection = screen.getByText("Sector").closest("details");
    const functionSection = screen.getByText("Function").closest("details");
    const categorySection = screen.getByText("Category").closest("details");
    const organizationSection = screen.getByText("Organization").closest("details");

    expect(sectorSection).not.toBeNull();
    expect(functionSection).not.toBeNull();
    expect(categorySection).not.toBeNull();
    expect(organizationSection).not.toBeNull();

    expect(
      within(sectorSection as HTMLElement)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toContain("Healthcare");
    expect(
      within(functionSection as HTMLElement)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toContain("Engineering");
    expect(
      within(categorySection as HTMLElement)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toContain("Toolkit");
    expect(
      within(organizationSection as HTMLElement)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toContain("/explore?org_size=small_business&page=1");
  });

  it("preserves active filters when adding another taxonomy filter", () => {
    render(<FilterSidebar active={{ q: "health", sector: "healthcare" }} />);

    const functionSection = screen.getByText("Function").closest("details");
    const engineering = within(functionSection as HTMLElement).getByRole("link", {
      name: /engineering/i,
    });

    expect(engineering).toHaveAttribute(
      "href",
      "/explore?q=health&sector=healthcare&function=engineering&page=1",
    );
  });
});
