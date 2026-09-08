import {
  categoryLabel,
  formatDate,
  formatDateTime,
  initials,
  priorityLabel,
  statusLabel,
  timeAgo,
} from "@/components/dashboard/format";
import { describe, expect, it } from "vitest";

describe("format", () => {
  it("categoryLabel falls back to the raw value for unknown categories", () => {
    expect(categoryLabel("ROAD")).toBe("Roads");
    expect(categoryLabel("APOCALYPSE")).toBe("APOCALYPSE");
  });

  it("statusLabel maps known and unknown statuses", () => {
    expect(statusLabel("AI_ANALYZING")).toBe("AI Analyzing");
    expect(statusLabel("WEIRD")).toBe("WEIRD");
  });

  it("priorityLabel maps known priorities", () => {
    expect(priorityLabel("CRITICAL")).toBe("Critical");
    expect(priorityLabel("LOW")).toBe("Low");
  });

  it("formatDate returns the input unchanged for invalid dates", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
    expect(formatDate("")).toBe("");
  });

  it("formatDate formats valid ISO dates", () => {
    expect(formatDate("2026-01-02T10:30:00Z")).toMatch(/2026/);
  });

  it("formatDateTime formats valid ISO datetimes", () => {
    expect(formatDateTime("2026-01-02T10:30:00Z")).toMatch(/2026/i);
  });

  it("timeAgo returns 'just now' for the current timestamp", () => {
    expect(timeAgo(new Date().toISOString())).toBe("just now");
  });

  it("timeAgo returns '' for invalid dates", () => {
    expect(timeAgo("garbage")).toBe("");
  });

  it("timeAgo pluralizes", () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    expect(timeAgo(fiveMinutesAgo)).toBe("5 minutes ago");
  });

  it("initials builds up to two initials", () => {
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("Ada Lovelace Babbage")).toBe("AL");
    expect(initials(undefined)).toBe("?");
    expect(initials("")).toBe("?");
  });
});