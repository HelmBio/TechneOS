import { describe, it, expect } from "vitest";
import {
  ALLOWED_TRANSITIONS,
  definitionEditable,
  nextStatusOptions,
} from "@/lib/version-lifecycle";

describe("nextStatusOptions", () => {
  it("offers the current status plus its legal targets, in canonical order", () => {
    expect(nextStatusOptions("draft")).toEqual(["draft", "testing"]);
    expect(nextStatusOptions("testing")).toEqual(["draft", "testing", "active"]);
    expect(nextStatusOptions("active")).toEqual(["active", "deprecated"]);
    expect(nextStatusOptions("deprecated")).toEqual(["active", "deprecated"]);
  });

  it("never offers an illegal jump", () => {
    expect(nextStatusOptions("draft")).not.toContain("active");
    // Deprecation is only reachable from active.
    expect(nextStatusOptions("draft")).not.toContain("deprecated");
    expect(nextStatusOptions("testing")).not.toContain("deprecated");
    expect(nextStatusOptions("active")).not.toContain("draft");
    expect(nextStatusOptions("active")).not.toContain("testing");
    expect(nextStatusOptions("deprecated")).not.toContain("testing");
  });

  it("always includes the current status so the select can render its value", () => {
    for (const status of ["draft", "testing", "active", "deprecated"]) {
      expect(nextStatusOptions(status)).toContain(status);
    }
  });

  it("mirrors ALLOWED_TRANSITIONS", () => {
    for (const [current, targets] of Object.entries(ALLOWED_TRANSITIONS)) {
      const opts = nextStatusOptions(current);
      for (const t of targets) expect(opts).toContain(t);
    }
  });
});

describe("definitionEditable", () => {
  it("is editable only for draft/testing without runs", () => {
    expect(definitionEditable("draft", false)).toBe(true);
    expect(definitionEditable("testing", false)).toBe(true);
    expect(definitionEditable("draft", true)).toBe(false);
    expect(definitionEditable("testing", true)).toBe(false);
    expect(definitionEditable("active", false)).toBe(false);
    expect(definitionEditable("deprecated", false)).toBe(false);
  });

  it("treats undefined has_runs as no runs", () => {
    expect(definitionEditable("draft", undefined)).toBe(true);
    expect(definitionEditable("active", undefined)).toBe(false);
  });
});
