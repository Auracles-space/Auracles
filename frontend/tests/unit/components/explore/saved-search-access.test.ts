import { describe, expect, it } from "vitest";

import {
  canUseSavedSearches,
  SAVED_SEARCH_ROLES,
} from "@/lib/marketplace/saved-search-access";

describe("canUseSavedSearches", () => {
  it("admits operators", () => {
    expect(canUseSavedSearches(["operator"])).toBe(true);
    expect(canUseSavedSearches(["contributor", "operator"])).toBe(true);
  });

  it("refuses every role the saved-search API would 403", () => {
    // Explore used to render the save form on `isAuthenticated` alone, so
    // these roles saw a button that could only fail.
    for (const roles of [[], ["contributor"], ["attestor"], ["developer"], ["admin"]]) {
      expect(canUseSavedSearches(roles)).toBe(false);
    }
  });

  it("names the operator role as the single source of the gate", () => {
    expect([...SAVED_SEARCH_ROLES]).toEqual(["operator"]);
  });
});
