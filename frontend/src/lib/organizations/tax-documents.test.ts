import { describe, expect, it } from "vitest";

import { taxDocumentLabel, taxDocumentTypesFor } from "./tax-documents";

describe("tax documents", () => {
  it("offers FIRS documents to Nigerian orgs and IRS forms elsewhere", () => {
    expect(taxDocumentTypesFor("NG")).toEqual(["firs_tin", "tcc", "other"]);
    expect(taxDocumentTypesFor("gb")).toEqual(["w9", "w8ben", "other"]);
  });

  it("names stored types and tolerates missing ones", () => {
    expect(taxDocumentLabel("tcc")).toBe("Tax Clearance Certificate (TCC)");
    expect(taxDocumentLabel(null)).toBe("");
  });
});
