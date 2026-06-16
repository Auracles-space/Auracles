import { describe, expect, it } from "vitest";

import {
  allValid,
  isEmail,
  isHttpUrl,
  isLengthBetween,
  isNonEmpty,
  isPasswordLongEnough,
  isPositiveNumber,
} from "@/lib/forms/validators";

describe("form validators", () => {
  it("isNonEmpty rejects blank/whitespace", () => {
    expect(isNonEmpty("x")).toBe(true);
    expect(isNonEmpty("   ")).toBe(false);
    expect(isNonEmpty("")).toBe(false);
  });

  it("isEmail validates basic shape", () => {
    expect(isEmail("a@b.co")).toBe(true);
    expect(isEmail("a@b")).toBe(false);
    expect(isEmail("nope")).toBe(false);
  });

  it("isPasswordLongEnough enforces 12 chars", () => {
    expect(isPasswordLongEnough("StrongerPass1")).toBe(true);
    expect(isPasswordLongEnough("short")).toBe(false);
  });

  it("isHttpUrl accepts http(s) only", () => {
    expect(isHttpUrl("https://x.com")).toBe(true);
    expect(isHttpUrl("http://x.com")).toBe(true);
    expect(isHttpUrl("ftp://x.com")).toBe(false);
    expect(isHttpUrl("not a url")).toBe(false);
  });

  it("isLengthBetween checks bounds on trimmed length", () => {
    expect(isLengthBetween("abc", 1, 5)).toBe(true);
    expect(isLengthBetween("", 1, 5)).toBe(false);
    expect(isLengthBetween("abcdef", 1, 5)).toBe(false);
  });

  it("isPositiveNumber accepts >0 finite numbers", () => {
    expect(isPositiveNumber("5")).toBe(true);
    expect(isPositiveNumber(5)).toBe(true);
    expect(isPositiveNumber("0")).toBe(false);
    expect(isPositiveNumber("-1")).toBe(false);
    expect(isPositiveNumber("abc")).toBe(false);
  });

  it("allValid is true only when every check passes", () => {
    expect(allValid(true, true)).toBe(true);
    expect(allValid(true, false)).toBe(false);
    expect(allValid()).toBe(true);
  });
});
