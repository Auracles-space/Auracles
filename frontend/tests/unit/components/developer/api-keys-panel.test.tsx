/**
 * Partner API key panel tests.
 *
 * Every key used to be minted with the full scope set regardless of what the
 * integration needed, so a Partner that only read the catalog held a key that
 * could also charge their customers. These tests hold the picker to least
 * privilege.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiKeysPanel } from "@/components/modules/developer/developer-portal-controls";

/** Render the panel with no existing keys and a spy on creation. */
function renderPanel() {
  const onCreate = vi.fn<(name: string, scopes: string[]) => Promise<void>>(
    async () => {},
  );
  render(
    <ApiKeysPanel
      apiKeys={[]}
      onClearRawKey={vi.fn()}
      onCreate={onCreate}
      onRevoke={vi.fn()}
      rawApiKey={null}
    />,
  );
  return onCreate;
}

describe("ApiKeysPanel", () => {
  it("grants only the scopes that were chosen", async () => {
    const onCreate = renderPanel();

    fireEvent.change(screen.getByLabelText("Key name"), {
      target: { value: "Catalog widget" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Read previews/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith("Catalog widget", [
        "catalog:read",
        "preview:read",
      ]);
    });
  });

  it("does not grant purchase access unless it is asked for", async () => {
    const onCreate = renderPanel();

    fireEvent.change(screen.getByLabelText("Key name"), {
      target: { value: "Read only" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith("Read only", ["catalog:read"]);
    });
    const [, granted] = onCreate.mock.calls[0];
    expect(granted).not.toContain("purchase:write");
  });

  it("sends scopes in a stable order whatever order they were clicked", async () => {
    const onCreate = renderPanel();

    fireEvent.change(screen.getByLabelText("Key name"), {
      target: { value: "Full integration" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Read purchase status/ }),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /Start purchases/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith("Full integration", [
        "catalog:read",
        "purchase:write",
        "purchases:read",
      ]);
    });
  });

  it("refuses a key with no access at all", async () => {
    const onCreate = renderPanel();

    fireEvent.change(screen.getByLabelText("Key name"), {
      target: { value: "Empty" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Read the catalog/ }));

    // The API rejects an empty scope list, so the form must not let it be sent.
    expect(screen.getByRole("button", { name: "Create key" })).toBeDisabled();
    expect(onCreate).not.toHaveBeenCalled();
  });
});
