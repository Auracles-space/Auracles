import { describe, expect, it } from "vitest";

import { attestorHubSections, defaultAttestorSection } from "./attestor-hub";

const counts = { offers: 2, queue: 3, invitations: 1 };

describe("attestorHubSections", () => {
  it("has no sections before the org is an attestor, so the tab is the application", () => {
    expect(attestorHubSections({ isAdmin: true, capability: undefined, counts })).toEqual([]);
    expect(attestorHubSections({ isAdmin: true, capability: "pending", counts })).toEqual([]);
  });

  it("gives an admin of an active attestor offers, queue, and the application", () => {
    expect(attestorHubSections({ isAdmin: true, capability: "active", counts })).toEqual([
      { id: "offers", label: "Offers", count: 2 },
      { id: "queue", label: "Queue", count: 3 },
      { id: "application", label: "Application", count: 0 },
    ]);
  });

  it("gives a plain member only their queue", () => {
    expect(attestorHubSections({ isAdmin: false, capability: "active", counts })).toEqual([
      { id: "queue", label: "Queue", count: 3 },
    ]);
  });

  it("drops offers but keeps in-flight work reachable while suspended or revoked", () => {
    for (const capability of ["suspended", "revoked"]) {
      expect(
        attestorHubSections({ isAdmin: true, capability, counts }).map((s) => s.id),
      ).toEqual(["queue", "application"]);
    }
    expect(attestorHubSections({ isAdmin: false, capability: "suspended", counts })).toEqual([]);
  });
});

describe("defaultAttestorSection", () => {
  it("opens the first section that needs attention", () => {
    const sections = attestorHubSections({ isAdmin: true, capability: "active", counts });
    expect(defaultAttestorSection(sections)).toBe("offers");
  });

  it("opens the queue when nothing needs attention", () => {
    const sections = attestorHubSections({
      isAdmin: true,
      capability: "active",
      counts: { offers: 0, queue: 0, invitations: 0 },
    });
    expect(defaultAttestorSection(sections)).toBe("queue");
  });
});
