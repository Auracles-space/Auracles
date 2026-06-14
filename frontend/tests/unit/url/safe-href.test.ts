import { describe, expect, it } from "vitest";

import { safeHref, safeInternalPath } from "@/lib/url/safe-href";

describe("safeHref", () => {
  it("allows http and https web links", () => {
    expect(safeHref("https://example.com/path")).toBe(
      "https://example.com/path",
    );
    expect(safeHref("http://example.com")).toBe("http://example.com");
  });

  it("allows mailto links", () => {
    expect(safeHref("mailto:hi@example.com")).toBe("mailto:hi@example.com");
  });

  it("rejects javascript scheme to block stored XSS", () => {
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("  JavaScript:alert(1)")).toBeUndefined();
  });

  it("rejects data and vbscript schemes", () => {
    expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeUndefined();
    expect(safeHref("vbscript:msgbox(1)")).toBeUndefined();
  });

  it("rejects relative, empty, and nullish values", () => {
    expect(safeHref("/dashboard")).toBeUndefined();
    expect(safeHref("example.com")).toBeUndefined();
    expect(safeHref("")).toBeUndefined();
    expect(safeHref("   ")).toBeUndefined();
    expect(safeHref(null)).toBeUndefined();
    expect(safeHref(undefined)).toBeUndefined();
  });
});

describe("safeInternalPath", () => {
  it("allows single-slash internal paths", () => {
    expect(safeInternalPath("/dashboard")).toBe("/dashboard");
    expect(safeInternalPath("/projects/123?tab=files")).toBe(
      "/projects/123?tab=files",
    );
  });

  it("rejects protocol-relative and absolute external URLs", () => {
    expect(safeInternalPath("//evil.com")).toBeUndefined();
    expect(safeInternalPath("https://evil.com")).toBeUndefined();
    expect(safeInternalPath("/\\evil.com")).toBeUndefined();
  });

  it("rejects non-slash, control-char, empty, and nullish values", () => {
    expect(safeInternalPath("dashboard")).toBeUndefined();
    expect(safeInternalPath("/has space")).toBeUndefined();
    expect(safeInternalPath("/line\nbreak")).toBeUndefined();
    expect(safeInternalPath("")).toBeUndefined();
    expect(safeInternalPath(null)).toBeUndefined();
    expect(safeInternalPath(undefined)).toBeUndefined();
  });
});
