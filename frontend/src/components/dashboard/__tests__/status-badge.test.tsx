import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  CategoryBadge,
  PriorityBadge,
  StatusBadge,
} from "@/components/dashboard/status-badge";

afterEach(cleanup);

describe("status-badge", () => {
  it("renders a human label for AI workflow statuses", () => {
    render(<StatusBadge value="AI_ANALYZING" />);
    expect(screen.getByText("AI Analyzing")).toBeTruthy();
  });

  it("falls back to the raw value for unknown statuses", () => {
    render(<StatusBadge value="MYSTERY" />);
    expect(screen.getByText("MYSTERY")).toBeTruthy();
  });

  it("renders priority labels", () => {
    render(<PriorityBadge value="CRITICAL" />);
    expect(screen.getByText("Critical")).toBeTruthy();
  });

  it("renders category labels", () => {
    render(<CategoryBadge value="WATER" />);
    expect(screen.getByText("Water")).toBeTruthy();
  });
});