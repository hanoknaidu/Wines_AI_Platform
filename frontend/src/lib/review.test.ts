import { describe, expect, it } from "vitest";
import { REVIEW_BADGE, isSigned, reviewStatusOf } from "./review";

describe("review status", () => {
  it("treats only a signed status as reviewed", () => {
    expect(isSigned("reviewed")).toBe(true);
    expect(isSigned("corrected")).toBe(true);
    // The whole reason this module exists: a fixture row carries producer names with
    // nobody's signature on them, so it is NOT reviewed.
    expect(isSigned("fixture")).toBe(false);
    expect(isSigned("unreviewed")).toBe(false);
  });

  it("degrades an unknown status to the cautious end, never the reassuring one", () => {
    expect(reviewStatusOf("audited-by-robots")).toBe("unreviewed");
    expect(reviewStatusOf("")).toBe("unreviewed");
    expect(isSigned("audited-by-robots")).toBe(false);
  });

  it("never gives an unsigned status an ok tone", () => {
    for (const status of ["fixture", "unreviewed"] as const) {
      expect(REVIEW_BADGE[status].tone).toBe("caution");
    }
    for (const status of ["reviewed", "corrected"] as const) {
      expect(REVIEW_BADGE[status].tone).toBe("ok");
    }
  });
});
