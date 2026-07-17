import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  listAttestationAnnotations,
  createAttestationAnnotation,
} from "@/lib/generated/sdk.gen";
import { AnnotationsPanel } from "./annotations-panel";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAttestationAnnotations: vi.fn(),
  createAttestationAnnotation: vi.fn(),
  deleteAttestationAnnotation: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/auth/form-client")>()),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer member" }),
}));

describe("AnnotationsPanel error handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAttestationAnnotations).mockResolvedValue({
      response: { ok: true },
      data: [],
    } as never);
  });

  it("shows the backend error inline when creating an annotation fails", async () => {
    const alertSpy = vi.fn();
    vi.stubGlobal("alert", alertSpy);
    vi.mocked(createAttestationAnnotation).mockResolvedValue({
      data: undefined,
      error: { detail: "Review is not open for annotations." },
      response: new Response(null, { status: 409 }),
    } as never);

    render(<AnnotationsPanel attestationId="att-1" canWrite />);

    fireEvent.click(await screen.findByRole("button", { name: /Add Annotation/i }));
    fireEvent.change(screen.getByPlaceholderText(/Section 2\.1/i), {
      target: { value: "Section 3" },
    });
    fireEvent.change(screen.getByPlaceholderText(/Your finding or suggestion/i), {
      target: { value: "Scope is ambiguous." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save Annotation/i }));

    expect(
      await screen.findByText(/Review is not open for annotations/i),
    ).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
  });
});
