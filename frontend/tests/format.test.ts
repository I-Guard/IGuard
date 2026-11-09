import { describe, expect, it } from "vitest";
import { DASH, formatBytes, formatDuration, formatMs, formatPercent } from "../src/utils/format";
import { hasRole } from "../src/utils/roles";
import { passwordSchema } from "../src/utils/password";

describe("formatting never fabricates values", () => {
  it("renders missing data as an em dash, not zero", () => {
    expect(formatPercent(null)).toBe(DASH);
    expect(formatPercent(undefined)).toBe(DASH);
    expect(formatMs(null)).toBe(DASH);
    expect(formatBytes(null)).toBe(DASH);
    expect(formatDuration(null)).toBe(DASH);
  });
  it("keeps a real zero as zero", () => {
    expect(formatPercent(0)).toContain("0");
    expect(formatPercent(0)).not.toBe(DASH);
  });
});

describe("roles", () => {
  it("is hierarchical", () => {
    expect(hasRole(["ADMIN"], "OPERATOR")).toBe(true);
    expect(hasRole(["OPERATOR"], "ADMIN")).toBe(false);
    expect(hasRole(["VIEWER"], "VIEWER")).toBe(true);
    expect(hasRole([], "VIEWER")).toBe(false);
  });
});

describe("password policy", () => {
  it.each(["short1A", "alllowercase123", "ALLUPPERCASE123", "NoDigitsHereAtAll"])("rejects %s", (p) => {
    expect(passwordSchema.safeParse(p).success).toBe(false);
  });
  it("accepts a compliant password", () => { expect(passwordSchema.safeParse("Correct-Horse-42x").success).toBe(true); });
});
